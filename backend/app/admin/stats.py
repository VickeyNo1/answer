"""统计查询：总学生数、总对话数、今日活跃用户"""
from app.database import get_db_ctx


def get_stats() -> dict:
    """获取系统统计数据"""
    with get_db_ctx() as db:
        # 总学生数（不含管理员）
        cursor = db.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'student'")
        total_students = cursor.fetchone()["cnt"]

        # 总对话数
        cursor = db.execute("SELECT COUNT(*) as cnt FROM conversations")
        total_conversations = cursor.fetchone()["cnt"]

        # 今日活跃用户：今天有对话消息的学生数
        cursor = db.execute(
            """
            SELECT COUNT(DISTINCT c.user_id) as cnt
            FROM conversations c
            JOIN messages m ON m.conversation_id = c.id
            WHERE DATE(m.created_at) = DATE('now')
            """
        )
        today_active_users = cursor.fetchone()["cnt"]

    return {
        "total_students": total_students,
        "total_conversations": total_conversations,
        "today_active_users": today_active_users,
    }
