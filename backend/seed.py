"""初始化脚本：默认管理员账号 + 默认大模型配置 + 全局设置初始键值（MySQL）"""
import sys
import os

# 确保可以导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bcrypt
from app.database import init_db, get_db_ctx
from app.settings_store import SETTING_DEFAULTS

ADMIN_STUDENT_ID = "admin"
ADMIN_PASSWORD = "admin123"
ADMIN_NAME = "管理员"

# 默认大模型配置：(provider, model_name, display_name, price_in, price_out, is_active)
# 单价单位：元/千 token（默认值仅供参考，管理员可在管理页调整）
DEFAULT_MODELS = [
    ("ali", "qwen3.7-flash", "通义千问 3.7 Flash", 0.0008, 0.002, 1),
    ("ali", "qwen3.7-plus", "通义千问 3.7 Plus", 0.0008, 0.002, 0),
    ("ali", "qwen3.7-max", "通义千问 3.7 Max", 0.0024, 0.0096, 0),
    ("deepseek", "deepseek-v3", "DeepSeek V3", 0.002, 0.008, 0),
    ("deepseek", "deepseek-r1", "DeepSeek R1", 0.004, 0.016, 0),
]


def _seed_admin(db) -> None:
    cursor = db.execute(
        "SELECT id FROM users WHERE student_id = %s", (ADMIN_STUDENT_ID,)
    )
    if cursor.fetchone() is not None:
        print(f"管理员账号已存在 (student_id={ADMIN_STUDENT_ID})，跳过创建")
        return

    password_hash = bcrypt.hashpw(
        ADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    db.execute(
        """INSERT INTO users (student_id, password_hash, name, role)
           VALUES (%s, %s, %s, %s)""",
        (ADMIN_STUDENT_ID, password_hash, ADMIN_NAME, "admin"),
    )
    print("管理员账号创建成功！")
    print(f"  学号: {ADMIN_STUDENT_ID}")
    print(f"  密码: {ADMIN_PASSWORD}")
    print("请妥善保管密码，首次登录后建议修改。")


# 模型名迁移映射：旧名 → (新名, 新显示名)
_MODEL_RENAME = {
    "qwen-plus": ("qwen3.7-plus", "通义千问 3.7 Plus"),
    "qwen-max": ("qwen3.7-max", "通义千问 3.7 Max"),
}


def _migrate_model_names(db) -> None:
    """将旧模型名原地更新为百炼当前有效名（幂等）"""
    renamed = 0
    for old_name, (new_name, new_display) in _MODEL_RENAME.items():
        cursor = db.execute(
            "SELECT id FROM model_configs WHERE model_name = %s", (old_name,)
        )
        if cursor.fetchone() is None:
            continue
        # 若新名已存在则删旧行，否则原地改名
        cur2 = db.execute(
            "SELECT id FROM model_configs WHERE model_name = %s", (new_name,)
        )
        if cur2.fetchone() is not None:
            db.execute("DELETE FROM model_configs WHERE model_name = %s", (old_name,))
        else:
            db.execute(
                "UPDATE model_configs SET model_name = %s, display_name = %s WHERE model_name = %s",
                (new_name, new_display, old_name),
            )
        renamed += 1
    if renamed:
        print(f"模型名迁移完成：{renamed} 条旧名已更新")


def _seed_models(db) -> None:
    created = 0
    for provider, model_name, display_name, price_in, price_out, is_active in DEFAULT_MODELS:
        cursor = db.execute(
            "SELECT id FROM model_configs WHERE model_name = %s", (model_name,)
        )
        if cursor.fetchone() is not None:
            continue
        db.execute(
            """INSERT INTO model_configs
               (provider, model_name, display_name, price_in, price_out, enabled, is_active)
               VALUES (%s, %s, %s, %s, %s, 1, %s)""",
            (provider, model_name, display_name, price_in, price_out, is_active),
        )
        created += 1
    if created:
        print(f"默认大模型配置写入 {created} 条")
    else:
        print("大模型配置已存在，跳过")


def _seed_settings(db) -> None:
    """幂等写入 app_settings 初始键值（已存在的键不覆盖）"""
    created = 0
    for key, value in SETTING_DEFAULTS.items():
        cursor = db.execute(
            "SELECT id FROM app_settings WHERE setting_key = %s", (key,)
        )
        if cursor.fetchone() is not None:
            continue
        db.execute(
            "INSERT INTO app_settings (setting_key, setting_value) VALUES (%s, %s)",
            (key, str(value)),
        )
        created += 1
    if created:
        print(f"全局设置初始键值写入 {created} 条")
    else:
        print("全局设置已存在，跳过")


def seed():
    """初始化数据库并写入默认数据"""
    # 先建库建表
    init_db()

    with get_db_ctx() as db:
        _seed_admin(db)
        _migrate_model_names(db)
        _seed_models(db)
        _seed_settings(db)
        db.commit()


if __name__ == "__main__":
    seed()
