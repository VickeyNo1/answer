"""对话路由：SSE 流式对话（Function Calling + 知识库检索） + 对话 CRUD + 答案反馈"""
import json
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from app.auth.deps import get_current_user
from app.database import get_db, get_db_ctx
from app.models import (
    ChatRequest,
    ConversationCreate,
    ConversationOut,
    FeedbackCreate,
    MessageOut,
)
from app.chat import concurrency
from app.chat.memory import get_conversation_history
from app.chat.qwen_service import build_messages, stream_chat
from app.admin.entitlements import get_effective_limit
from app.kb.subjects import is_valid_subject, DEFAULT_SUBJECT
from app.llm import store as llm_store
from app import settings_store

router = APIRouter(prefix="/api", tags=["对话"])


# ========== SSE 流式对话 ==========

@router.post("/chat")
async def chat(
    req: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """SSE 流式对话：大模型 Function Calling 自主决定是否检索知识库

    v4.0 链路（设计文档 §3.3）：配额校验 → 单人串行 → 并发闸门（有限排队）
    → 流式生成（queue/kb_search/kb_refs/kp_ids/delta/suggestions/done）
    """
    user_id = current_user["id"]

    # 科目校验（不在注册表内则回退到默认科目）
    subject = req.subject if req.subject and is_valid_subject(req.subject) else DEFAULT_SUBJECT

    # 1. 配额校验：当日提问数 ≥ 生效上限 → 429
    limit = get_effective_limit(current_user)
    with get_db_ctx() as db:
        cursor = db.execute(
            """SELECT COUNT(*) AS cnt FROM messages m
               JOIN conversations c ON m.conversation_id = c.id
               WHERE c.user_id = %s AND m.role = 'user' AND m.created_at >= CURDATE()""",
            (user_id,),
        )
        used_today = int(cursor.fetchone()["cnt"])
    if used_today >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"今日提问次数已用完（{limit}/{limit}），明天再来吧",
        )

    # 2. 单人串行：上一条回答未完成时拒绝重复提问
    if not concurrency.acquire_user_lock(user_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="上一条回答还在进行中",
        )

    ticket = None
    try:
        # 3. 并发闸门：拿不到信号量时进入有限等待队列，队满 429
        ticket = concurrency.try_enqueue(settings_store.get_int("chat_queue_size"))
        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="当前提问人数较多，请稍后再试",
            )

        # 4. 确定对话 ID（null 则自动新建）
        conversation_id = req.conversation_id
        if conversation_id is None:
            with get_db_ctx() as db:
                cursor = db.execute(
                    "INSERT INTO conversations (user_id, title, subject) VALUES (%s, %s, %s)",
                    (user_id, req.message[:30] if req.message else "新对话", subject),
                )
                db.commit()
                conversation_id = cursor.lastrowid
        else:
            # 已有对话：同步更新所选科目
            with get_db_ctx() as db:
                db.execute(
                    "UPDATE conversations SET subject = %s WHERE id = %s AND user_id = %s",
                    (subject, conversation_id, user_id),
                )
                db.commit()

        # 5. 保存用户消息
        with get_db_ctx() as db:
            db.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conversation_id, "user", req.message),
            )
            db.commit()

        # 6. 构建消息列表（M3：注入记忆块）
        history = get_conversation_history(conversation_id, limit=10)
        # 排除刚存入的当前用户消息（因为还没得到回复）
        if history and history[-1]["role"] == "user" and history[-1]["content"] == req.message:
            history = history[:-1]

        memory_block = None
        try:
            from app.profile import store as profile_store
            with get_db_ctx() as mem_db:
                memory_block = profile_store.build_memory_block(mem_db, user_id, current_user)
        except Exception:
            pass

        messages = build_messages(req.message, history, memory_block)
        model_name = llm_store.get_active_model()
    except BaseException:
        # 预处理阶段失败：归还已持有的并发资源
        if ticket == concurrency.IMMEDIATE:
            concurrency.release_slot()
        elif ticket is not None:
            concurrency.cancel(ticket)
        concurrency.release_user_lock(user_id)
        raise

    # 7. SSE 流式生成（同步生成器，FastAPI 在线程池中迭代，线程级锁可用）
    def event_generator():
        slot_acquired = ticket == concurrency.IMMEDIATE
        try:
            yield _sse({"type": "start", "conversation_id": conversation_id})

            # 排队等待：入队推一次 + 每前进一位再推一次
            for position in concurrency.wait_slot(ticket):
                yield _sse({"type": "queue", "position": position})
            slot_acquired = True

            full_content = ""
            error_occurred = False
            prompt_tokens = 0
            completion_tokens = 0
            kp_ids: list[str] = []
            suggestions: list[str] = []

            for chunk in stream_chat(messages, model_name, subject, user_id, conversation_id):
                if "error" in chunk:
                    yield _sse({"type": "error", "detail": chunk["error"]})
                    error_occurred = True
                    break
                if "kb_search" in chunk:
                    yield _sse({"type": "kb_search"})
                    continue
                if "kb_refs" in chunk:
                    yield _sse({"type": "kb_refs", "refs": chunk["kb_refs"]})
                    continue
                if "kp_ids" in chunk:
                    kp_ids = chunk["kp_ids"]
                    yield _sse({"type": "kp_ids", "kp_ids": kp_ids})
                    continue
                if "suggestions" in chunk:
                    suggestions = chunk["suggestions"]
                    continue
                if "usage" in chunk:
                    prompt_tokens = chunk["usage"].get("prompt_tokens", 0)
                    completion_tokens = chunk["usage"].get("completion_tokens", 0)
                    continue
                content = chunk.get("content", "")
                if content:
                    full_content += content
                    yield _sse({"type": "delta", "content": content})

            # 追问建议：正文结束后、done 之前推送
            if not error_occurred and suggestions:
                yield _sse({"type": "suggestions", "items": suggestions})

            # 记录用量（即使内容为空也记录 token 消耗）
            if not error_occurred and (prompt_tokens or completion_tokens):
                try:
                    llm_store.record_usage(
                        model_name, user_id, conversation_id,
                        prompt_tokens, completion_tokens,
                    )
                except Exception:
                    pass

            # 保存 AI 回复到数据库（含知识点编号，供掌握度归因）
            if not error_occurred and full_content:
                with get_db_ctx() as db:
                    cursor = db.execute(
                        "INSERT INTO messages (conversation_id, role, content, knowledge_point_ids) "
                        "VALUES (%s, %s, %s, %s)",
                        (
                            conversation_id, "assistant", full_content,
                            json.dumps(kp_ids, ensure_ascii=False) if kp_ids else None,
                        ),
                    )
                    db.commit()
                    message_id = cursor.lastrowid

                    # M3：记忆计数 +1，达到阈值触发画像总结
                    try:
                        from app.profile import store as profile_store
                        from app.profile.summarizer import submit_profile_summary
                        count = profile_store.increment_dialog_count(db, user_id)
                        threshold = settings_store.get_int("profile_update_interval")
                        if count >= threshold:
                            profile_store.reset_dialog_count(db, user_id)
                            submit_profile_summary(user_id)
                    except Exception:
                        pass

                yield _sse({"type": "done", "message_id": message_id})
            elif not error_occurred:
                yield _sse({"type": "done", "message_id": 0})
        finally:
            if slot_acquired:
                concurrency.release_slot()
            else:
                concurrency.cancel(ticket)
            concurrency.release_user_lock(user_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Nginx 关闭缓冲
        },
    )


def _sse(data: dict) -> str:
    """格式化 SSE 数据行"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ========== 答案反馈 ==========

@router.post("/feedback")
async def submit_feedback(
    req: FeedbackCreate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """提交消息级反馈（点赞/点踩）；同一消息重复提交覆盖更新（UPSERT）"""
    if req.rating not in ("up", "down"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="rating 仅支持 up / down",
        )
    reason = req.reason.strip() if req.reason else None
    if req.rating == "down" and not reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="点踩时请填写理由",
        )

    # 归属校验：message → conversation → user 三层关联
    cursor = db.execute(
        """SELECT m.id, m.role, c.user_id FROM messages m
           JOIN conversations c ON m.conversation_id = c.id
           WHERE m.id = %s""",
        (req.message_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="消息不存在",
        )
    if row["user_id"] != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权评价他人的消息",
        )
    if row["role"] != "assistant":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只能评价 AI 回答消息",
        )

    db.execute(
        """INSERT INTO feedbacks (message_id, user_id, rating, reason)
           VALUES (%s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE rating = %s, reason = %s""",
        (req.message_id, current_user["id"], req.rating, reason, req.rating, reason),
    )
    db.commit()
    return {"message": "ok"}


# ========== 对话 CRUD ==========

@router.post("/conversations", status_code=status.HTTP_201_CREATED, response_model=ConversationOut)
async def create_conversation(
    req: ConversationCreate,
    current_user: dict = Depends(get_current_user),
):
    """新建对话"""
    with get_db_ctx() as db:
        cursor = db.execute(
            "INSERT INTO conversations (user_id, title) VALUES (%s, %s)",
            (current_user["id"], req.title),
        )
        db.commit()
        conv_id = cursor.lastrowid

        cursor = db.execute(
            "SELECT id, title, created_at, subject FROM conversations WHERE id = %s",
            (conv_id,),
        )
        row = cursor.fetchone()
        return ConversationOut(
            id=row["id"],
            title=row["title"],
            created_at=str(row["created_at"]),
            subject=row["subject"],
        )


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    current_user: dict = Depends(get_current_user),
):
    """获取当前用户的对话列表（按时间降序）"""
    with get_db_ctx() as db:
        cursor = db.execute(
            """SELECT id, title, created_at, subject FROM conversations
               WHERE user_id = %s
               ORDER BY created_at DESC""",
            (current_user["id"],),
        )
        rows = cursor.fetchall()
        return [
            ConversationOut(
                id=r["id"], title=r["title"],
                created_at=str(r["created_at"]), subject=r["subject"],
            )
            for r in rows
        ]


@router.get("/conversations/{conversation_id}", response_model=list[MessageOut])
async def get_messages(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
):
    """获取对话的消息历史（按时间升序）"""
    with get_db_ctx() as db:
        # 验证对话属于当前用户
        cursor = db.execute(
            "SELECT id FROM conversations WHERE id = %s AND user_id = %s",
            (conversation_id, current_user["id"]),
        )
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="对话不存在或不属于当前用户",
            )

        cursor = db.execute(
            """SELECT id, role, content, created_at FROM messages
               WHERE conversation_id = %s
               ORDER BY created_at ASC""",
            (conversation_id,),
        )
        rows = cursor.fetchall()
        return [
            MessageOut(
                id=r["id"], role=r["role"],
                content=r["content"], created_at=str(r["created_at"]),
            )
            for r in rows
        ]


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
):
    """删除对话及其所有消息"""
    with get_db_ctx() as db:
        # 验证对话属于当前用户
        cursor = db.execute(
            "SELECT id FROM conversations WHERE id = %s AND user_id = %s",
            (conversation_id, current_user["id"]),
        )
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="对话不存在或不属于当前用户",
            )

        # 删除消息和对话
        db.execute("DELETE FROM messages WHERE conversation_id = %s", (conversation_id,))
        db.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
        db.commit()

    return {"message": "ok"}
