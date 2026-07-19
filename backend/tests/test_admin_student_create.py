# -*- coding: utf-8 -*-
"""测试 POST /api/admin/students - 创建学生"""
import pytest
from app.database import get_db_ctx


@pytest.fixture(autouse=True)
def cleanup():
    """测试后清理创建的学生"""
    yield
    with get_db_ctx() as db:
        db.execute("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id IN (SELECT id FROM users WHERE student_id LIKE 'test_create_%'))")
        db.execute("DELETE FROM conversations WHERE user_id IN (SELECT id FROM users WHERE student_id LIKE 'test_create_%')")
        db.execute("DELETE FROM users WHERE student_id LIKE 'test_create_%'")
        db.commit()


class TestAdminStudentCreate:

    def test_create_success(self, client, admin_headers):
        """创建学生成功"""
        resp = client.post("/api/admin/students", json={
            "student_id": "test_create_001",
            "name": "测试学生A",
            "password": "123456",
        }, headers=admin_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["student_id"] == "test_create_001"
        assert data["name"] == "测试学生A"
        assert data["role"] == "student"
        assert "id" in data
        assert "created_at" in data

    def test_create_duplicate(self, client, admin_headers):
        """学号重复返回 400"""
        client.post("/api/admin/students", json={
            "student_id": "test_create_002",
            "name": "学生B",
            "password": "pass123",
        }, headers=admin_headers)

        resp = client.post("/api/admin/students", json={
            "student_id": "test_create_002",
            "name": "重复学生",
            "password": "pass456",
        }, headers=admin_headers)
        assert resp.status_code == 400
        assert "已存在" in resp.json()["detail"]

    def test_create_without_token(self, client):
        """未认证返回 403"""
        resp = client.post("/api/admin/students", json={
            "student_id": "test_create_003",
            "name": "学生C",
            "password": "pass789",
        })
        assert resp.status_code in (401, 403)

    def test_create_student_forbidden(self, client, student_headers):
        """学生无权创建返回 403"""
        resp = client.post("/api/admin/students", json={
            "student_id": "test_create_004",
            "name": "学生D",
            "password": "pass000",
        }, headers=student_headers)
        assert resp.status_code == 403

    def test_create_missing_fields(self, client, admin_headers):
        """缺少字段返回 422"""
        resp = client.post("/api/admin/students", json={
            "student_id": "test_create_005",
        }, headers=admin_headers)
        assert resp.status_code == 422

    def test_create_can_login(self, client, admin_headers):
        """创建的学生可以登录"""
        client.post("/api/admin/students", json={
            "student_id": "test_create_006",
            "name": "可登录学生",
            "password": "login123",
        }, headers=admin_headers)

        resp = client.post("/api/auth/login", json={
            "student_id": "test_create_006",
            "password": "login123",
        })
        assert resp.status_code == 200
        assert resp.json()["role"] == "student"
