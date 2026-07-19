# -*- coding: utf-8 -*-
"""测试 PUT /api/admin/students/{id} - 修改学生信息"""
import pytest
from app.database import get_db_ctx


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with get_db_ctx() as db:
        db.execute("DELETE FROM users WHERE student_id LIKE 'update_test_%'")
        db.commit()


class TestAdminStudentUpdate:

    def test_update_name(self, client, admin_headers):
        """修改姓名"""
        create_resp = client.post("/api/admin/students", json={
            "student_id": "update_test_001",
            "name": "原名",
            "password": "pass123",
        }, headers=admin_headers)
        student_id = create_resp.json()["id"]

        resp = client.put(f"/api/admin/students/{student_id}", json={
            "name": "新名字",
        }, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "新名字"

    def test_update_password(self, client, admin_headers):
        """重置密码"""
        create_resp = client.post("/api/admin/students", json={
            "student_id": "update_test_002",
            "name": "密码测试",
            "password": "oldpass",
        }, headers=admin_headers)
        student_id = create_resp.json()["id"]

        resp = client.put(f"/api/admin/students/{student_id}", json={
            "password": "newpass123",
        }, headers=admin_headers)
        assert resp.status_code == 200

        # 验证新密码可以登录
        login_resp = client.post("/api/auth/login", json={
            "student_id": "update_test_002",
            "password": "newpass123",
        })
        assert login_resp.status_code == 200

    def test_update_both(self, client, admin_headers):
        """同时修改姓名和密码"""
        create_resp = client.post("/api/admin/students", json={
            "student_id": "update_test_003",
            "name": "原始",
            "password": "pass1",
        }, headers=admin_headers)
        student_id = create_resp.json()["id"]

        resp = client.put(f"/api/admin/students/{student_id}", json={
            "name": "已修改",
            "password": "pass2",
        }, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "已修改"

    def test_update_not_found(self, client, admin_headers):
        """修改不存在的学生返回 404"""
        resp = client.put("/api/admin/students/99999", json={
            "name": "不存在",
        }, headers=admin_headers)
        assert resp.status_code == 404

    def test_update_without_token(self, client):
        """未认证返回 403"""
        resp = client.put("/api/admin/students/1", json={"name": "test"})
        assert resp.status_code in (401, 403)

    def test_update_student_forbidden(self, client, student_headers):
        """学生无权修改返回 403"""
        resp = client.put("/api/admin/students/1", json={"name": "test"}, headers=student_headers)
        assert resp.status_code == 403

    def test_update_empty_body(self, client, admin_headers):
        """空请求体不报错"""
        create_resp = client.post("/api/admin/students", json={
            "student_id": "update_test_004",
            "name": "空修改",
            "password": "pass123",
        }, headers=admin_headers)
        student_id = create_resp.json()["id"]

        resp = client.put(f"/api/admin/students/{student_id}", json={}, headers=admin_headers)
        assert resp.status_code == 200
