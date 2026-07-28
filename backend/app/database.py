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


# 建表 SQL（MySQL 8.x / InnoDB / utf8mb4）
TABLES_SQL = [
    """CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        student_id VARCHAR(64) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        name VARCHAR(64) NOT NULL,
        role VARCHAR(16) NOT NULL DEFAULT 'student',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS conversations (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        title VARCHAR(255) NOT NULL DEFAULT '新对话',
        subject VARCHAR(32) NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_conversations_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS messages (
        id INT AUTO_INCREMENT PRIMARY KEY,
        conversation_id INT NOT NULL,
        role VARCHAR(16) NOT NULL,
        content MEDIUMTEXT NOT NULL,
        knowledge_point_ids TEXT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_messages_conv (conversation_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS model_configs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        provider VARCHAR(16) NOT NULL DEFAULT 'ali',
        model_name VARCHAR(64) NOT NULL UNIQUE,
        display_name VARCHAR(64) NOT NULL,
        price_in DOUBLE NOT NULL DEFAULT 0,
        price_out DOUBLE NOT NULL DEFAULT 0,
        enabled TINYINT NOT NULL DEFAULT 1,
        is_active TINYINT NOT NULL DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS usage_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        model_name VARCHAR(64) NOT NULL,
        user_id INT NULL,
        conversation_id INT NULL,
        prompt_tokens INT NOT NULL DEFAULT 0,
        completion_tokens INT NOT NULL DEFAULT 0,
        total_tokens INT NOT NULL DEFAULT 0,
        cost DOUBLE NOT NULL DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_usage_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
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
