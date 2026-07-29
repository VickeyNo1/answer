# -*- coding: utf-8 -*-
"""测试学生自助修改密码：PUT /api/me/password

使用独立账号，避免影响 student(2024001) 的登录相关测试。
"""
import bcrypt
import pytest

from app.database import get_db_ctx
from app.auth.jwt_handler import create_access_token


@pytest.fixture(scope="module")
def pwd_user(client):
    """创建独立测试用户（初始密码 oldpass123），返回 (user_id, headers)"""
    password_hash = bcrypt.hashpw(b"oldpass123", bcrypt.gensalt()).decode("utf-8")
    with get_db_ctx() as db:
        cursor = db.execute(
            "INSERT INTO users (student_id, password_hash, name, role) "
            "VALUES (%s, %s, %s, 'student')",
            ("pwd_test_user", password_hash, "改密测试"),
        )
        db.commit()
        user_id = cursor.lastrowid
    token = create_access_token(user_id=user_id, role="student")
    return user_id, {"Authorization": f"Bearer {token}"}


class TestChangePassword:
    """PUT /api/me/password"""

    def test_without_token(self, client):
        resp = client.put("/api/me/password", json={
            "old_password": "x", "new_password": "y12345",
        })
        assert resp.status_code in (401, 403)

    def test_wrong_old_password(self, client, pwd_user):
        _, headers = pwd_user
        resp = client.put("/api/me/password", json={
            "old_password": "wrongpass", "new_password": "newpass123",
        }, headers=headers)
        assert resp.status_code == 400
        assert "旧密码" in resp.json()["detail"]

    def test_new_password_too_short(self, client, pwd_user):
        _, headers = pwd_user
        resp = client.put("/api/me/password", json={
            "old_password": "oldpass123", "new_password": "12345",
        }, headers=headers)
        assert resp.status_code == 400
        assert "6" in resp.json()["detail"]

    def test_change_success_and_login(self, client, pwd_user):
        """改密成功后：新密码可登录、旧密码失效"""
        _, headers = pwd_user
        resp = client.put("/api/me/password", json={
            "old_password": "oldpass123", "new_password": "newpass456",
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json() == {"message": "ok"}

        resp = client.post("/api/auth/login", json={
            "student_id": "pwd_test_user", "password": "newpass456",
        })
        assert resp.status_code == 200

        resp = client.post("/api/auth/login", json={
            "student_id": "pwd_test_user", "password": "oldpass123",
        })
        assert resp.status_code == 401
