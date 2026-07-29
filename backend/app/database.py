"""MySQL 数据访问层：连接封装 + 建表（机器A MySQL 8.4）"""
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

from app.config import get_settings


class DB:
    """连接包装：提供与旧 sqlite3.Connection 相近的 execute/commit 接口，降低迁移面"""

    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql: str, params=None):
        cursor = self.conn.cursor()
        cursor.execute(sql, params or None)
        return cursor

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        self.conn.close()


def _connect(with_db: bool = True):
    """建立 MySQL 连接；with_db=False 时不选库（用于建库）"""
    settings = get_settings()
    return pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DB if with_db else None,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=10,
    )


# 建表 SQL（MySQL 8.x / InnoDB / utf8mb4；存量库补注释见 scripts/add_table_comments.py）
TABLES_SQL = [
    """CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        student_id VARCHAR(64) NOT NULL UNIQUE COMMENT '学号（登录账号，唯一）',
        password_hash VARCHAR(255) NOT NULL COMMENT 'bcrypt 密码哈希',
        name VARCHAR(64) NOT NULL COMMENT '姓名',
        role VARCHAR(16) NOT NULL DEFAULT 'student' COMMENT '角色：student=学生 / admin=管理员',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表（学生与管理员）'""",
    """CREATE TABLE IF NOT EXISTS conversations (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        user_id INT NOT NULL COMMENT '所属用户 ID（users.id）',
        title VARCHAR(255) NOT NULL DEFAULT '新对话' COMMENT '会话标题（取首条提问前 30 字）',
        subject VARCHAR(32) NULL COMMENT '科目枚举值（如 cpa_acc，由知识库侧维护）',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        INDEX idx_conversations_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话会话表'""",
    """CREATE TABLE IF NOT EXISTS messages (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        conversation_id INT NOT NULL COMMENT '所属会话 ID（conversations.id）',
        role VARCHAR(16) NOT NULL COMMENT '消息角色：user=学生提问 / assistant=AI 回答',
        content MEDIUMTEXT NOT NULL COMMENT '消息正文（Markdown）',
        knowledge_point_ids TEXT NULL COMMENT '知识库命中知识点编号 JSON 数组（如 ["ACC-03-02-01"]）',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        INDEX idx_messages_conv (conversation_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话消息表'""",
    """CREATE TABLE IF NOT EXISTS model_configs (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        provider VARCHAR(16) NOT NULL DEFAULT 'ali' COMMENT '服务商：ali=通义千问 / deepseek=DeepSeek（均走百炼）',
        model_name VARCHAR(64) NOT NULL UNIQUE COMMENT '模型名（dashscope 调用标识，唯一）',
        display_name VARCHAR(64) NOT NULL COMMENT '展示名称',
        price_in DOUBLE NOT NULL DEFAULT 0 COMMENT '输入单价（元/千 token，管理员维护）',
        price_out DOUBLE NOT NULL DEFAULT 0 COMMENT '输出单价（元/千 token，管理员维护）',
        enabled TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用：1=启用 / 0=停用',
        is_active TINYINT NOT NULL DEFAULT 0 COMMENT '是否当前使用模型：1=是（全表唯一）',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='大模型配置表'""",
    """CREATE TABLE IF NOT EXISTS usage_logs (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        model_name VARCHAR(64) NOT NULL COMMENT '使用的模型名',
        user_id INT NULL COMMENT '发起用户 ID（可空）',
        conversation_id INT NULL COMMENT '所属会话 ID（可空）',
        prompt_tokens INT NOT NULL DEFAULT 0 COMMENT '输入 token 数（Function Calling 两轮累加）',
        completion_tokens INT NOT NULL DEFAULT 0 COMMENT '输出 token 数（Function Calling 两轮累加）',
        total_tokens INT NOT NULL DEFAULT 0 COMMENT '总 token 数',
        cost DOUBLE NOT NULL DEFAULT 0 COMMENT '费用（元）= tokens/1000 × 单价',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        INDEX idx_usage_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='大模型用量与费用日志表'""",
]


def init_db() -> None:
    """启动时执行：确保数据库存在并建表"""
    settings = get_settings()

    # 1. 确保数据库存在（需要账号有 CREATE 权限；已存在则跳过）
    conn = _connect(with_db=False)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.MYSQL_DB}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
    finally:
        conn.close()

    # 2. 建表
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            for sql in TABLES_SQL:
                cursor.execute(sql)
        conn.commit()
    finally:
        conn.close()


def get_db():
    """FastAPI 依赖注入：返回数据库连接（生成器）"""
    db = DB(_connect())
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_ctx():
    """用于脚本/服务层的上下文管理器版本（如 seed.py）"""
    db = DB(_connect())
    try:
        yield db
    finally:
        db.close()
