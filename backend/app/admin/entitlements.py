"""权益生效值封装：users 覆盖值 ?? app_settings 全局默认

生效值规则（设计文档 §3.1）：users 表覆盖列为 NULL 时跟随全局默认，
统一在此计算，避免 NULL 判断散落各处。
"""
from app import settings_store


def get_effective_limit(user: dict) -> int:
    """当前用户每日提问上限生效值"""
    override = user.get("daily_question_limit")
    if override is not None:
        return int(override)
    return settings_store.get_int("daily_question_limit_default")


def get_effective_memory_enabled(user: dict) -> bool:
    """当前用户记忆功能开关生效值（M1 仅预埋，M3 生效）"""
    override = user.get("memory_enabled")
    if override is not None:
        return bool(override)
    return settings_store.get_bool("memory_enabled_default")
