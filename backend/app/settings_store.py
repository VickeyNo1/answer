"""app_settings 全局设置：内存缓存 + 类型转换 + 更新刷新

- 值统一以字符串落库（app_settings.setting_value），读取时按键转 int/bool；
- 启动时（app/main.py lifespan）全量加载到内存缓存，PUT 更新后刷新，避免每次对话查库；
- 更新用 UPDATE 语句保证 ON UPDATE CURRENT_TIMESTAMP 生效（键缺失时兜底 INSERT）。
"""
import threading

from app.database import get_db_ctx

# 全部设置键及默认值（缺行/未 seed 时的兜底，与 seed.py 初始值一致）
SETTING_DEFAULTS: dict[str, int] = {
    "daily_question_limit_default": 20,
    "memory_enabled_default": 1,
    "chat_concurrency": 3,
    "chat_queue_size": 5,
    "profile_update_interval": 20,
}

# 响应时按 bool 输出的键
BOOL_KEYS = {"memory_enabled_default"}

_cache: dict[str, int] = dict(SETTING_DEFAULTS)
_cache_lock = threading.Lock()


def load_settings() -> None:
    """从数据库全量加载设置到内存缓存（缺键回落默认值；DB 异常时保持现有缓存）"""
    values = dict(SETTING_DEFAULTS)
    try:
        with get_db_ctx() as db:
            cursor = db.execute("SELECT setting_key, setting_value FROM app_settings")
            for row in cursor.fetchall():
                key = row["setting_key"]
                if key in SETTING_DEFAULTS:
                    try:
                        values[key] = int(row["setting_value"])
                    except (TypeError, ValueError):
                        pass
    except Exception:
        return
    with _cache_lock:
        _cache.clear()
        _cache.update(values)


def get_int(key: str) -> int:
    """读取整型设置值（内存缓存）"""
    with _cache_lock:
        return _cache.get(key, SETTING_DEFAULTS[key])


def get_bool(key: str) -> bool:
    """读取布尔设置值（内存缓存）"""
    return bool(get_int(key))


def get_all() -> dict:
    """返回全部设置（按键做 int/bool 类型转换，供 GET /api/admin/settings）"""
    with _cache_lock:
        snapshot = dict(_cache)
    return {
        key: bool(value) if key in BOOL_KEYS else value
        for key, value in snapshot.items()
    }


def update_settings(db, updates: dict[str, int]) -> None:
    """部分更新设置（值转字符串落库；UPDATE 保 ON UPDATE 生效），完成后刷新缓存"""
    for key, value in updates.items():
        cursor = db.execute(
            "UPDATE app_settings SET setting_value = %s WHERE setting_key = %s",
            (str(int(value)), key),
        )
        if cursor.rowcount == 0:
            # 键缺失（如 seed 未跑）时兜底插入，保证 PUT 语义完整
            db.execute(
                "INSERT INTO app_settings (setting_key, setting_value) VALUES (%s, %s)",
                (key, str(int(value))),
            )
    db.commit()
    load_settings()
