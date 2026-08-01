"""学习风格画像总结（设计 §5.6）

触发机制：对话 SSE 完成后，dialog_count_since_update 达到 profile_update_interval 阈值时，
用与判卷同一个 ThreadPoolExecutor 提交画像总结任务。LLM 失败静默放弃（计数已清零）。
"""
import logging

from app.database import get_db_ctx
from app.llm import store as llm_store

logger = logging.getLogger(__name__)

MAX_PROFILE_CHARS = 200

PROFILE_SYSTEM_PROMPT = """你是学习分析师，根据学生的对话历史总结其学习风格。
只输出不超过 200 字符的画像文本，涵盖：偏好的讲解方式、易错概念类型、学习建议。
不要输出任何标题、标号或 JSON，只输出纯文本画像。"""


def build_summary_prompt(history: list[dict]) -> str:
    """从对话历史拼画像总结 prompt（取最近 40 条消息）"""
    lines = []
    for msg in history[-40:]:
        role = "学生" if msg["role"] == "user" else "老师"
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


def _call_llm(model: str, prompt: str) -> tuple[str, int, int]:
    """同步调用大模型，返回 (文本, input_tokens, output_tokens)；失败抛异常"""
    from app.llm.client import create_client
    client = create_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": PROFILE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        extra_body={"enable_thinking": False},
    )
    content = response.choices[0].message.content or ""
    usage = response.usage
    return content, (usage.prompt_tokens if usage else 0), (usage.completion_tokens if usage else 0)


def summarize_profile(user_id: int) -> None:
    """画像总结主流程（同步，供后台线程与测试调用）

    1. 取对话历史（最近 40 条消息）
    2. 调 LLM 生成画像
    3. 截断到 200 字符
    4. record_usage(task_type='profile')
    5. 写回 style_profile + 重置计数
    失败静默放弃（计数已清零，下个周期再试）。
    """
    from app.profile import store as profile_store
    from app.chat.memory import get_conversation_history

    # 取该用户最近的所有对话消息（跨会话）
    with get_db_ctx() as db:
        cursor = db.execute(
            """SELECT m.role, m.content FROM messages m
               JOIN conversations c ON m.conversation_id = c.id
               WHERE c.user_id = %s
               ORDER BY m.created_at DESC
               LIMIT 40""",
            (user_id,),
        )
        rows = list(cursor.fetchall())
    rows.reverse()
    history = [{"role": r["role"], "content": r["content"]} for r in rows]

    if not history:
        logger.info("画像总结跳过：无对话历史 user_id=%s", user_id)
        with get_db_ctx() as db:
            profile_store.reset_dialog_count(db, user_id)
        return

    model = llm_store.get_active_model()
    prompt = build_summary_prompt(history)

    try:
        text, tokens_in, tokens_out = _call_llm(model, prompt)
        if tokens_in or tokens_out:
            llm_store.record_usage(model, user_id, None, tokens_in, tokens_out,
                                   task_type="profile")
        profile_text = text.strip()[:MAX_PROFILE_CHARS]
        with get_db_ctx() as db:
            profile_store.upsert_profile(db, user_id, profile_text)
        logger.info("画像总结完成 user_id=%s chars=%d", user_id, len(profile_text))
    except Exception as e:
        logger.warning("画像总结失败 user_id=%s: %s（计数已清零，下个周期再试）", user_id, e)
        # 计数已在 increment_dialog_count 中清零（upsert_profile 会重置），
        # 但失败时没走 upsert_profile，需手动重置
        with get_db_ctx() as db:
            profile_store.reset_dialog_count(db, user_id)


def submit_profile_summary(user_id: int) -> None:
    """把画像总结任务丢进后台线程池（复用 judger._bg_executor）"""
    from app.exam.judger import _bg_executor
    _bg_executor.submit(_guarded, user_id)


def _guarded(user_id: int) -> None:
    try:
        summarize_profile(user_id)
    except Exception:
        logger.exception("画像总结任务异常 user_id=%s", user_id)
