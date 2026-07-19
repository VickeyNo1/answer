# -*- coding: utf-8 -*-
"""共享测试 fixtures

在导入 app 之前设置测试环境变量，确保使用独立的测试数据库。
"""
import os
import sys
import shutil

# ---- 设置测试环境变量（必须在导入 app 之前）----
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(TEST_DIR)

# 测试用独立数据库和路径
os.environ["DATABASE_URL"] = "./data/test.db"
os.environ["CHROMA_DB_PATH"] = "./data/chroma_test"
os.environ["UPLOAD_DIR"] = "./uploads_test"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"

# 将 backend 加入 sys.path
sys.path.insert(0, BACKEND_DIR)

import pytest
import bcrypt
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import init_db, get_db_ctx
from app.auth.jwt_handler import create_access_token

# ---- 清理缓存，确保测试环境变量生效 ----
get_settings.cache_clear()

# 导入 app（此时会读取测试环境变量）
from app.main import app


@pytest.fixture(scope="session")
def settings():
    """返回测试环境配置"""
    return get_settings()


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """会话级：初始化测试数据库 + 创建 admin 和 student 账号"""
    db_path = get_settings().DATABASE_URL
    chroma_path = get_settings().CHROMA_DB_PATH
    upload_dir = get_settings().UPLOAD_DIR

    # 清理旧测试数据
    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.exists(chroma_path):
        shutil.rmtree(chroma_path, ignore_errors=True)
    if os.path.exists(upload_dir):
        shutil.rmtree(upload_dir, ignore_errors=True)
    os.makedirs(upload_dir, exist_ok=True)

    # 建表
    init_db()

    # 创建 admin 和 student 账号
    with get_db_ctx() as db:
        admin_hash = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode("utf-8")
        student_hash = bcrypt.hashpw(b"student123", bcrypt.gensalt()).decode("utf-8")

        db.execute(
            "INSERT INTO users (student_id, password_hash, name, role) VALUES (?, ?, ?, 'admin')",
            ("admin", admin_hash, "管理员"),
        )
        db.execute(
            "INSERT INTO users (student_id, password_hash, name, role) VALUES (?, ?, ?, 'student')",
            ("2024001", student_hash, "测试学生"),
        )
        db.commit()

    yield

    # 会话结束后清理
    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.exists(chroma_path):
        shutil.rmtree(chroma_path, ignore_errors=True)
    if os.path.exists(upload_dir):
        shutil.rmtree(upload_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def client(setup_database):
    """FastAPI 测试客户端"""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token():
    """管理员 JWT Token"""
    return create_access_token(user_id=1, role="admin")


@pytest.fixture(scope="session")
def student_token():
    """学生 JWT Token"""
    return create_access_token(user_id=2, role="student")


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    """管理员请求头"""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def student_headers(student_token):
    """学生请求头"""
    return {"Authorization": f"Bearer {student_token}"}
