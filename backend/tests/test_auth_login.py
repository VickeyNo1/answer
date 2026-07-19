# -*- coding: utf-8 -*-
"""测试 POST /api/auth/login - 用户登录"""


class TestAuthLogin:

    def test_login_admin_success(self, client):
        """管理员登录成功"""
        resp = client.post("/api/auth/login", json={
            "student_id": "admin",
            "password": "admin123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["token_type"] == "bearer"
        assert data["role"] == "admin"

    def test_login_student_success(self, client):
        """学生登录成功"""
        resp = client.post("/api/auth/login", json={
            "student_id": "2024001",
            "password": "student123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["role"] == "student"

    def test_login_wrong_password(self, client):
        """密码错误返回 401"""
        resp = client.post("/api/auth/login", json={
            "student_id": "admin",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401
        assert "学号或密码错误" in resp.json()["detail"]

    def test_login_nonexistent_user(self, client):
        """不存在的用户返回 401"""
        resp = client.post("/api/auth/login", json={
            "student_id": "nonexistent",
            "password": "anything",
        })
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        """缺少字段返回 422"""
        resp = client.post("/api/auth/login", json={
            "student_id": "admin",
        })
        assert resp.status_code == 422

    def test_login_empty_body(self, client):
        """空请求体返回 422"""
        resp = client.post("/api/auth/login", json={})
        assert resp.status_code == 422

    def test_login_wrong_content_type(self, client):
        """非 JSON 请求体返回 422"""
        resp = client.post("/api/auth/login", data="not json")
        assert resp.status_code == 422
