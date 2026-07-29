"""聊天并发控制（线程级，设计文档 §3.3 定调，勿改为 asyncio）

- 全局闸门：threading.BoundedSemaphore(chat_concurrency)，限制同时进行的 LLM 流式对话数；
- 单人串行：dict[user_id, threading.Lock]，非阻塞 acquire，拿不到即拒（429）；
- 有限等待队列：FIFO 票据列表，超出 chat_queue_size 拒绝（429）；
  等待期间通过 wait_slot 生成器产出队位（入队产出一次 + 每前进一位再产出一次）。

现有 stream_chat 为同步生成器、kb client 为 httpx 同步调用，FastAPI 在线程池中
运行同步代码，线程级信号量即可正确限流，无需全链路异步重构。
"""
import itertools
import threading

# 入队即拿到执行权（无需排队）时的票据
IMMEDIATE = -1

_sem: threading.BoundedSemaphore | None = None
_cond = threading.Condition()
_waiting: list[int] = []  # FIFO 排队票据
_ticket_seq = itertools.count(1)

_user_locks: dict[int, threading.Lock] = {}
_user_locks_guard = threading.Lock()


def init(concurrency: int) -> None:
    """启动时初始化全局闸门（并发数调整需重启生效）"""
    global _sem
    _sem = threading.BoundedSemaphore(max(1, concurrency))


def _get_sem() -> threading.BoundedSemaphore:
    global _sem
    if _sem is None:
        init(3)
    return _sem


# ========== 单人串行 ==========

def acquire_user_lock(user_id: int) -> bool:
    """非阻塞获取单人锁；False = 上一条回答还在进行中"""
    with _user_locks_guard:
        lock = _user_locks.setdefault(user_id, threading.Lock())
    return lock.acquire(blocking=False)


def release_user_lock(user_id: int) -> None:
    with _user_locks_guard:
        lock = _user_locks.get(user_id)
    if lock is not None and lock.locked():
        lock.release()


# ========== 全局闸门 + 等待队列 ==========

def try_enqueue(queue_size: int) -> int | None:
    """尝试进入执行/排队。

    返回 IMMEDIATE=立即获得执行权；正整数=排队票据；None=队列已满（429）。
    """
    with _cond:
        if not _waiting and _get_sem().acquire(blocking=False):
            return IMMEDIATE
        if len(_waiting) >= queue_size:
            return None
        ticket = next(_ticket_seq)
        _waiting.append(ticket)
        return ticket


def wait_slot(ticket: int):
    """等待执行权的生成器：入队产出一次队位，此后每前进一位再产出一次；
    获得执行权时正常结束（return）。调用方需在 finally 中配对 release_slot/cancel。
    """
    if ticket == IMMEDIATE:
        return
    last_pos = None
    while True:
        with _cond:
            if ticket not in _waiting:
                # 已被 cancel（防御性退出）
                return
            pos = _waiting.index(ticket) + 1
            if pos == 1 and _get_sem().acquire(blocking=False):
                _waiting.pop(0)
                _cond.notify_all()
                return
            if pos == last_pos:
                _cond.wait(timeout=1.0)
                continue
        yield pos
        last_pos = pos


def release_slot() -> None:
    """执行完毕释放全局闸门，并唤醒排队者"""
    with _cond:
        try:
            _get_sem().release()
        except ValueError:
            pass
        _cond.notify_all()


def cancel(ticket: int) -> None:
    """排队中途放弃（如客户端断开），从队列移除并唤醒后续排队者"""
    if ticket == IMMEDIATE:
        return
    with _cond:
        if ticket in _waiting:
            _waiting.remove(ticket)
            _cond.notify_all()
