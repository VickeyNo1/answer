"""多轮对话记忆管理：从 SQLite 加载历史消息拼入 prompt"""
from app.database import get_db_ctx


def get_conversation_history(conversation_id: int, limit: int = 10) -> list[dict]:
    """
    从数据库加载指定对话的最近 N 条消息，用于拼入 prompt。
    返回格式: [{"role": "user"/"assistant", "content": "..."}]
    """
    with get_db_ctx() as db:
        cursor = db.execute(
            """SELECT role, content FROM messages
               WHERE conversation_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (conversation_id, limit),
        )
        rows = cursor.fetchall()

    # 反转为时间正序（最早在前）
    rows.reverse()
    return [{"role": row["role"], "content": row["content"]} for row in rows]
