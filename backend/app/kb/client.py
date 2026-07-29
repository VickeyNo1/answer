"""知识库检索服务 HTTP 客户端（机器A /kb/search，契约见 doc/知识库对接文档.md）

v4.0：每次 /kb/search 调用后写 kb_search_logs（含失败情形，六态状态），
日志写失败不影响主链路；另提供 probe() 供 /api/health 探测。
"""
import json
import logging
import time

import httpx

from app.config import get_settings
from app.database import get_db_ctx
from app.kb.prompt import collect_kp_ids

logger = logging.getLogger(__name__)


def _log_search(
    user_id: int,
    conversation_id: int | None,
    subject: str,
    collection: str,
    query: str,
    result_count: int,
    kp_ids: list[str],
    status: str,
    elapsed_ms: int,
) -> None:
    """写 kb_search_logs（检索可观测）；写失败吞掉异常，不影响主链路"""
    try:
        with get_db_ctx() as db:
            db.execute(
                """INSERT INTO kb_search_logs
                   (user_id, conversation_id, subject, collection, query,
                    result_count, kp_ids, status, elapsed_ms)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    user_id, conversation_id, subject, collection, query[:255],
                    result_count,
                    json.dumps(kp_ids, ensure_ascii=False) if kp_ids else None,
                    status, elapsed_ms,
                ),
            )
            db.commit()
    except Exception as e:
        logger.warning("kb_search_logs 写入失败（不影响主链路）: %s", e)

    # 日志分级：info（ok/empty）/ warning（timeout/http_error/code_error）/ error（degraded）
    line = (
        f"kb_search status={status} subject={subject} collection={collection} "
        f"query={query[:50]!r} results={result_count} elapsed={elapsed_ms}ms"
    )
    if status in ("ok", "empty"):
        logger.info(line)
    elif status == "degraded":
        logger.error(line)
    else:
        logger.warning(line)


def search(
    query: str,
    subject: str,
    collection: str = "textbook",
    top_k: int = 5,
    user_id: int = 0,
    conversation_id: int | None = None,
) -> dict | None:
    """
    调用知识库检索接口。
    - 成功（code=0）返回响应 dict（results 可能为空数组）
    - 参数错误（400）不重试，直接返回 None
    - 5001/超时/网络异常重试 1 次，仍失败返回 None（调用方降级为大模型直答）
    每次尝试均记录 kb_search_logs：ok/empty=成功；timeout/http_error/code_error=单次失败；
    degraded=重试后仍失败（最终降级）。
    """
    settings = get_settings()
    url = f"{settings.KB_BASE_URL.rstrip('/')}/kb/search"
    payload = {
        "query": query,
        "subject": subject,
        "collection": collection,
        "top_k": top_k,
    }
    headers = {}
    if settings.KB_TOKEN:
        headers["X-KB-Token"] = settings.KB_TOKEN

    for attempt in range(2):
        start = time.monotonic()
        fail_status = "timeout"
        try:
            resp = httpx.post(
                url, json=payload, headers=headers, timeout=settings.KB_TIMEOUT
            )
            data = resp.json()
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if data.get("code") == 0:
                results = data.get("results") or []
                _log_search(
                    user_id, conversation_id, subject, collection, query,
                    len(results), collect_kp_ids(data),
                    "ok" if results else "empty", elapsed_ms,
                )
                return data
            if resp.status_code == 400:
                # 参数错误属对接 bug，重试无意义
                _log_search(
                    user_id, conversation_id, subject, collection, query,
                    0, [], "http_error", elapsed_ms,
                )
                return None
            # 5001 等内部错误 → 进入下一次重试
            fail_status = "code_error" if resp.status_code == 200 else "http_error"
        except Exception:
            # 超时/网络异常 → 进入下一次重试
            fail_status = "timeout"
        elapsed_ms = int((time.monotonic() - start) * 1000)
        # 最后一次尝试仍失败 → 记 degraded（链路降级为大模型直答）
        _log_search(
            user_id, conversation_id, subject, collection, query,
            0, [], fail_status if attempt == 0 else "degraded", elapsed_ms,
        )
    return None


def probe() -> bool:
    """健康探测（供 GET /api/health）：优先 GET /health（3s 超时），
    404 时降级轻量 POST /kb/search（top_k=1，query 传固定词，勿传空串触发 4001）。
    """
    settings = get_settings()
    base = settings.KB_BASE_URL.rstrip("/")
    headers = {}
    if settings.KB_TOKEN:
        headers["X-KB-Token"] = settings.KB_TOKEN

    try:
        resp = httpx.get(f"{base}/health", headers=headers, timeout=3)
        if resp.status_code == 200:
            return True
        if resp.status_code != 404:
            return False
    except Exception:
        return False

    # /health 不存在（404）→ 轻量检索探测
    try:
        resp = httpx.post(
            f"{base}/kb/search",
            json={"query": "会计", "subject": "cpa_acc",
                  "collection": "textbook", "top_k": 1},
            headers=headers,
            timeout=3,
        )
        return resp.status_code == 200 and resp.json().get("code") == 0
    except Exception:
        return False
