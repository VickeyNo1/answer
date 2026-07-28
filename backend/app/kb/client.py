"""知识库检索服务 HTTP 客户端（机器A /kb/search，契约见 doc/知识库对接文档.md）"""
import httpx

from app.config import get_settings


def search(
    query: str,
    subject: str,
    collection: str = "textbook",
    top_k: int = 5,
) -> dict | None:
    """
    调用知识库检索接口。
    - 成功（code=0）返回响应 dict（results 可能为空数组）
    - 参数错误（400）不重试，直接返回 None
    - 5001/超时/网络异常重试 1 次，仍失败返回 None（调用方降级为大模型直答）
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

    for _attempt in range(2):
        try:
            resp = httpx.post(
                url, json=payload, headers=headers, timeout=settings.KB_TIMEOUT
            )
            data = resp.json()
            if data.get("code") == 0:
                return data
            if resp.status_code == 400:
                # 参数错误属对接 bug，重试无意义
                return None
            # 5001 等内部错误 → 进入下一次重试
        except Exception:
            # 超时/网络异常 → 进入下一次重试
            pass
    return None
