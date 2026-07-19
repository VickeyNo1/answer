"""初始化脚本：默认管理员账号 + 默认大模型配置 + 默认科目"""
import sys
import os

# 确保可以导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bcrypt
from app.database import init_db, get_db_ctx

ADMIN_STUDENT_ID = "admin"
ADMIN_PASSWORD = "admin123"
ADMIN_NAME = "管理员"

# 默认大模型配置：(provider, model_name, display_name, price_in, price_out, is_active)
# 单价单位：元/千 token（默认值仅供参考，管理员可在管理页调整）
DEFAULT_MODELS = [
    ("ali", "qwen-plus", "通义千问 Plus", 0.0008, 0.002, 1),
    ("ali", "qwen-max", "通义千问 Max", 0.0024, 0.0096, 0),
    ("deepseek", "deepseek-v3", "DeepSeek V3", 0.002, 0.008, 0),
    ("deepseek", "deepseek-r1", "DeepSeek R1", 0.004, 0.016, 0),
]

# 默认科目：(name, category, description, sort_order)
DEFAULT_SUBJECTS = [
    ("会计常识", "general", "会计基础常识与通用概念", 1),
    ("企业会计准则", "general", "企业会计准则与相关法规", 2),
    ("初级会计学", "professional", "初级会计职称相关课程", 10),
    ("中级会计学", "professional", "中级会计职称相关课程", 11),
]


def _seed_admin(db) -> None:
    cursor = db.execute(
        "SELECT id FROM users WHERE student_id = ?", (ADMIN_STUDENT_ID,)
    )
    if cursor.fetchone() is not None:
        print(f"管理员账号已存在 (student_id={ADMIN_STUDENT_ID})，跳过创建")
        return

    password_hash = bcrypt.hashpw(
        ADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    db.execute(
        """INSERT INTO users (student_id, password_hash, name, role)
           VALUES (?, ?, ?, ?)""",
        (ADMIN_STUDENT_ID, password_hash, ADMIN_NAME, "admin"),
    )
    print("管理员账号创建成功！")
    print(f"  学号: {ADMIN_STUDENT_ID}")
    print(f"  密码: {ADMIN_PASSWORD}")
    print("请妥善保管密码，首次登录后建议修改。")


def _seed_models(db) -> None:
    created = 0
    for provider, model_name, display_name, price_in, price_out, is_active in DEFAULT_MODELS:
        cursor = db.execute(
            "SELECT id FROM model_configs WHERE model_name = ?", (model_name,)
        )
        if cursor.fetchone() is not None:
            continue
        db.execute(
            """INSERT INTO model_configs
               (provider, model_name, display_name, price_in, price_out, enabled, is_active)
               VALUES (?, ?, ?, ?, ?, 1, ?)""",
            (provider, model_name, display_name, price_in, price_out, is_active),
        )
        created += 1
    if created:
        print(f"默认大模型配置写入 {created} 条")
    else:
        print("大模型配置已存在，跳过")


def _seed_subjects(db) -> None:
    created = 0
    for name, category, description, sort_order in DEFAULT_SUBJECTS:
        cursor = db.execute("SELECT id FROM subjects WHERE name = ?", (name,))
        if cursor.fetchone() is not None:
            continue
        db.execute(
            """INSERT INTO subjects (name, category, description, sort_order)
               VALUES (?, ?, ?, ?)""",
            (name, category, description, sort_order),
        )
        created += 1
    if created:
        print(f"默认科目写入 {created} 条")
    else:
        print("科目已存在，跳过")


def seed():
    """初始化数据库并写入默认数据"""
    # 先建表
    init_db()

    with get_db_ctx() as db:
        _seed_admin(db)
        _seed_models(db)
        _seed_subjects(db)
        db.commit()


if __name__ == "__main__":
    seed()
