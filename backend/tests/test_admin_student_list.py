# -*- coding: utf-8 -*-
"""测试 GET /api/admin/students - 学生列表（分页+搜索）"""
import pytest
from app.database import get_db_ctx


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with get_db_ctx() as db:
        db.execute("DELETE FROM users WHERE student_id LIKE 'list_test_%'")
        db.commit()


def _create_students(client, admin_headers, count=5):
    """批量创建测试学生"""
    for i in range(count):
        client.post("/api/admin/students", json={
            "student_id": f"list_test_{i:03d}",
            "name": f"列表学生{i}",
            "password": "pass123",
        }, headers=admin_headers)


class TestAdminStudentList:

    def test_list_returns_paginated(self, client, admin_headers):
        """返回分页结构"""
        _create_students(client, admin_headers, 3)
        resp = client.get("/api/admin/students?page=1&size=2", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "size" in data
        assert data["page"] == 1
        assert data["size"] == 2
        assert len(data["items"]) <= 2

    def test_list_pagination(self, client, admin_headers):
        """分页正确"""
        _create_students(client, admin_headers, 5)
        # 第一页
        resp = client.get("/api/admin/students?page=1&size=2", headers=admin_headers)
        page1 = resp.json()
        # 第二页
        resp = client.get("/api/admin/students?page=2&size=2", headers=admin_headers)
        page2 = resp.json()
        # 两页的 id 不重叠
        ids1 = {s["id"] for s in page1["items"]}
        ids2 = {s["id"] for s in page2["items"]}
        assert ids1.isdisjoint(ids2)

    def test_list_keyword_search(self, client, admin_headers):
        """关键词搜索"""
        client.post("/api/admin/students", json={
            "student_id": "list_test_keyword",
            "name": "搜索目标学生",
            "password": "pass123",
        }, headers=admin_headers)

        # 按学号搜索
        resp = client.get(
            "/api/admin/students?keyword=list_test_keyword",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert any(s["student_id"] == "list_test_keyword" for s in resp.json()["items"])

    def test_list_without_token(self, client):
        """未认证返回 403"""
        resp = client.get("/api/admin/students")
        assert resp.status_code in (401, 403)

    def test_list_student_forbidden(self, client, student_headers):
        """学生无权访问返回 403"""
        resp = client.get("/api/admin/students", headers=student_headers)
        assert resp.status_code == 403

    def test_list_default_page_size(self, client, admin_headers):
        """默认分页参数"""
        resp = client.get("/api/admin/students", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["size"] == 20

    def test_list_response_fields(self, client, admin_headers):
        """每条记录包含必要字段"""
        _create_students(client, admin_headers, 1)
        resp = client.get("/api/admin/students?page=1&size=100", headers=admin_headers)
        for student in resp.json()["items"]:
            assert "id" in student
            assert "student_id" in student
            assert "name" in student
            assert "role" in student
            assert "created_at" in student

    def test_list_excludes_admin(self, client, admin_headers):
        """列表不包含管理员"""
        resp = client.get("/api/admin/students?page=1&size=100", headers=admin_headers)
        roles = [s["role"] for s in resp.json()["items"]]
        assert "admin" not in roles
