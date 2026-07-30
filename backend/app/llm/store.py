"""大模型配置与用量的数据访问层：模型 CRUD、当前模型、用量记录与费用计算、统计"""
from datetime import date, timedelta
from app.database import get_db_ctx
from app.config import get_settings


def _row_to_model(row) -> dict:
    return {
        "id": row["id"],
        "provider": row["provider"],
        "model_name": row["model_name"],
        "display_name": row["display_name"],
        "price_in": float(row["price_in"]),
        "price_out": float(row["price_out"]),
        "enabled": bool(row["enabled"]),
        "is_active": bool(row["is_active"]),
        "created_at": str(row["created_at"]),
    }


# ========== 模型配置 ==========

def list_models() -> list[dict]:
    with get_db_ctx() as db:
        cursor = db.execute(
            "SELECT * FROM model_configs ORDER BY is_active DESC, id ASC"
        )
        return [_row_to_model(r) for r in cursor.fetchall()]


def get_model(model_id: int) -> dict | None:
    with get_db_ctx() as db:
        cursor = db.execute("SELECT * FROM model_configs WHERE id = %s", (model_id,))
        row = cursor.fetchone()
        return _row_to_model(row) if row else None


def get_model_by_name(model_name: str) -> dict | None:
    with get_db_ctx() as db:
        cursor = db.execute(
            "SELECT * FROM model_configs WHERE model_name = %s", (model_name,)
        )
        row = cursor.fetchone()
        return _row_to_model(row) if row else None


def create_model(provider: str, model_name: str, display_name: str,
                 price_in: float, price_out: float, enabled: bool = True) -> dict:
    with get_db_ctx() as db:
        cursor = db.execute(
            """INSERT INTO model_configs
               (provider, model_name, display_name, price_in, price_out, enabled, is_active)
               VALUES (%s, %s, %s, %s, %s, %s, 0)""",
            (provider, model_name, display_name, price_in, price_out, int(enabled)),
        )
        db.commit()
        cursor = db.execute("SELECT * FROM model_configs WHERE id = %s", (cursor.lastrowid,))
        return _row_to_model(cursor.fetchone())


def update_model(model_id: int, fields: dict) -> dict | None:
    allowed = {"provider", "model_name", "display_name", "price_in", "price_out", "enabled"}
    updates = []
    params = []
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        if key == "enabled":
            value = int(bool(value))
        updates.append(f"{key} = %s")
        params.append(value)

    with get_db_ctx() as db:
        cursor = db.execute("SELECT id FROM model_configs WHERE id = %s", (model_id,))
        if cursor.fetchone() is None:
            return None
        if updates:
            params.append(model_id)
            db.execute(f"UPDATE model_configs SET {', '.join(updates)} WHERE id = %s", params)
            db.commit()
        cursor = db.execute("SELECT * FROM model_configs WHERE id = %s", (model_id,))
        return _row_to_model(cursor.fetchone())


def delete_model(model_id: int) -> bool:
    with get_db_ctx() as db:
        cursor = db.execute("SELECT id FROM model_configs WHERE id = %s", (model_id,))
        if cursor.fetchone() is None:
            return False
        db.execute("DELETE FROM model_configs WHERE id = %s", (model_id,))
        db.commit()
        return True


def activate_model(model_id: int) -> dict | None:
    with get_db_ctx() as db:
        cursor = db.execute("SELECT id FROM model_configs WHERE id = %s", (model_id,))
        if cursor.fetchone() is None:
            return None
        db.execute("UPDATE model_configs SET is_active = 0")
        db.execute(
            "UPDATE model_configs SET is_active = 1, enabled = 1 WHERE id = %s",
            (model_id,),
        )
        db.commit()
        cursor = db.execute("SELECT * FROM model_configs WHERE id = %s", (model_id,))
        return _row_to_model(cursor.fetchone())


def get_active_model() -> str:
    """返回当前启用的模型名称，无则回退配置默认值"""
    with get_db_ctx() as db:
        cursor = db.execute(
            "SELECT model_name FROM model_configs WHERE is_active = 1 AND enabled = 1 LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            return row["model_name"]
    return get_settings().CHAT_MODEL


# ========== 用量与费用 ==========

def compute_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    """按模型单价（元/千 token）计算费用"""
    model = get_model_by_name(model_name)
    price_in = model["price_in"] if model else 0.0
    price_out = model["price_out"] if model else 0.0
    return round(prompt_tokens / 1000 * price_in + completion_tokens / 1000 * price_out, 6)


def record_usage(model_name: str, user_id: int | None, conversation_id: int | None,
                 prompt_tokens: int, completion_tokens: int,
                 task_type: str = "chat") -> None:
    total = prompt_tokens + completion_tokens
    cost = compute_cost(model_name, prompt_tokens, completion_tokens)
    with get_db_ctx() as db:
        db.execute(
            """INSERT INTO usage_logs
               (model_name, user_id, conversation_id, prompt_tokens, completion_tokens, total_tokens, cost, task_type)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (model_name, user_id, conversation_id, prompt_tokens, completion_tokens, total, cost, task_type),
        )
        db.commit()


def get_usage_stats(days: int = 7) -> dict:
    """用量与费用统计：累计、今日、按模型明细、最近 days 天趋势"""
    with get_db_ctx() as db:
        # 累计
        cursor = db.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) AS tokens, COALESCE(SUM(cost), 0) AS cost FROM usage_logs"
        )
        row = cursor.fetchone()
        total_tokens, total_cost = int(row["tokens"]), round(float(row["cost"]), 6)

        # 今日
        cursor = db.execute(
            """SELECT COALESCE(SUM(total_tokens), 0) AS tokens, COALESCE(SUM(cost), 0) AS cost
               FROM usage_logs WHERE DATE(created_at) = CURDATE()"""
        )
        row = cursor.fetchone()
        today_tokens, today_cost = int(row["tokens"]), round(float(row["cost"]), 6)

        # 按模型
        cursor = db.execute(
            """SELECT model_name, COALESCE(SUM(total_tokens), 0) AS tokens, COALESCE(SUM(cost), 0) AS cost
               FROM usage_logs GROUP BY model_name ORDER BY tokens DESC"""
        )
        by_model = [
            {"model_name": r["model_name"], "tokens": int(r["tokens"]), "cost": round(float(r["cost"]), 6)}
            for r in cursor.fetchall()
        ]

        # 最近 days 天（补齐无数据的日期为 0）
        cursor = db.execute(
            """SELECT DATE(created_at) AS d,
                      COALESCE(SUM(total_tokens), 0) AS tokens,
                      COALESCE(SUM(cost), 0) AS cost
               FROM usage_logs
               WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
               GROUP BY d""",
            (days - 1,),
        )
        day_map = {str(r["d"]): (int(r["tokens"]), round(float(r["cost"]), 6)) for r in cursor.fetchall()}

    today = date.today()
    daily = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        tokens, cost = day_map.get(d, (0, 0.0))
        daily.append({"date": d, "tokens": tokens, "cost": cost})

    return {
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "today_tokens": today_tokens,
        "today_cost": today_cost,
        "by_model": by_model,
        "daily": daily,
    }
