# -*- coding: utf-8 -*-
"""E2E: 认证模块 - POST /api/auth/login, GET /api/auth/me"""
import pytest
from tests.e2e.conftest import api_request


class TestE2EAuthLogin:

    def test_admin_login(self, server_available):
        """管理员登录成功"""
        code, body = api_request("POST", "/api/auth/login", data={
            "student_id": "admin",
            "password": "admin123",
        })
        assert code == 200
        assert body["role"] == "admin"
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    def test_student_login(self, server_available, test_student):
        """学生登录成功"""
        code, body = api_request("POST", "/api/auth/login", data={
            "student_id": test_student["student_id"],
            "password": test_student["password"],
        })
        assert code == 200
        assert body["role"] == "student"
        assert "access_token" in body

    def test_login_wrong_password(self, server_available, test_student):
        """密码错误返回 401"""
        code, body = api_request("POST", "/api/auth/login", data={
            "student_id": test_student["student_id"],
            "password": "wrong_password",
        })
        assert code == 401
        assert "detail" in body

    def test_login_nonexistent_user(self, server_available):
        """不存在的用户返回 401"""
        code, body = api_request("POST", "/api/auth/login", data={
            "student_id": "nonexistent_user_xyz",
            "password": "x",
        })
        assert code == 401

    def test_login_missing_fields(self, server_available):
        """缺少字段返回 422"""
        code, body = api_request("POST", "/api/auth/login", data={})
        assert code == 422


class TestE2EAuthMe:

    def test_me_with_valid_admin_token(self, server_available, admin_token):
        """管理员 Token 获取用户信息"""
        code, body = api_request("GET", "/api/auth/me", token=admin_token)
        assert code == 200
        assert body["role"] == "admin"
        assert "id" in body
        assert "student_id" in body
        assert "name" in body
        assert "created_at" in body

    def test_me_with_valid_student_token(self, server_available, test_student):
        """学生 Token 获取用户信息"""
        code, body = api_request("GET", "/api/auth/me", token=test_student["token"])
        assert code == 200
        assert body["role"] == "student"
        assert body["student_id"] == test_student["student_id"]

    def test_me_with_invalid_token(self, server_available):
        """无效 Token 返回 401"""
        code, body = api_request("GET", "/api/auth/me", token="invalid.token.here")
        assert code == 401

    def test_me_without_token(self, server_available):
        """无 Token 返回 401 或 403"""
        code, _ = api_request("GET", "/api/auth/me")
        assert code in (401, 403)
