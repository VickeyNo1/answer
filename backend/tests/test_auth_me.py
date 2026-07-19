# -*- coding: utf-8 -*-
"""测试 GET /api/auth/me - 获取当前用户信息"""


class TestAuthMe:

    def test_me_with_valid_token(self, client, admin_headers):
        """携带有效 Token 获取用户信息"""
        resp = client.get("/api/auth/me", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["student_id"] == "admin"
        assert data["role"] == "admin"
        assert data["name"] == "管理员"
        assert "id" in data
        assert "created_at" in data

    def test_me_with_student_token(self, client, student_headers):
        """学生 Token 获取学生信息"""
        resp = client.get("/api/auth/me", headers=student_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["student_id"] == "2024001"
        assert data["role"] == "student"

    def test_me_without_token(self, client):
        """未携带 Token 返回 401"""
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401
        # HTTPBearer 返回 403 当没有 credentials
        # 但 FastAPI 默认返回 403

    def test_me_with_invalid_token(self, client):
        """无效 Token 返回 401"""
        headers = {"Authorization": "Bearer invalid_token_12345"}
        resp = client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 401
        assert "Token" in resp.json()["detail"]

    def test_me_with_malformed_header(self, client):
        """格式错误的 Authorization 头"""
        headers = {"Authorization": "NotBearer token"}
        resp = client.get("/api/auth/me", headers=headers)
        assert resp.status_code in (401, 403)  # HTTPBearer 返回 401 或 403

    def test_me_response_model_fields(self, client, admin_headers):
        """响应模型包含所有必要字段"""
        resp = client.get("/api/auth/me", headers=admin_headers)
        data = resp.json()
        required_fields = {"id", "student_id", "name", "role", "created_at"}
        assert required_fields.issubset(set(data.keys()))
