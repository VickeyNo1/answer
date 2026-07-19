# -*- coding: utf-8 -*-
"""测试科目接口：公开列表 + 管理员 CRUD + 权限"""
import pytest
from app.database import get_db_ctx


@pytest.fixture(autouse=True)
def cleanup():
    """每个测试后清理创建的测试科目"""
    yield
    with get_db_ctx() as db:
        db.execute("DELETE FROM subjects WHERE name LIKE 'test_%'")
        db.commit()


class TestSubjectList:

    def test_list_public_for_student(self, client, student_headers):
        """学生可查看科目列表"""
        resp = client.get("/api/subjects", headers=student_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_without_token(self, client):
        """未认证返回 401/403"""
        resp = client.get("/api/subjects")
        assert resp.status_code in (401, 403)

    def test_list_contains_seed(self, client, admin_headers):
        """列表项包含 category 字段"""
        resp = client.get("/api/subjects", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        if data:
            assert "category" in data[0]
            assert data[0]["category"] in ("general", "professional")


class TestSubjectCRUD:

    def test_create_success(self, client, admin_headers):
        """管理员新增科目成功"""
        resp = client.post("/api/admin/subjects", json={
            "name": "test_初级会计学",
            "category": "professional",
            "description": "测试科目",
            "sort_order": 5,
        }, headers=admin_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test_初级会计学"
        assert data["category"] == "professional"

    def test_create_invalid_category(self, client, admin_headers):
        """非法 category 返回 400"""
        resp = client.post("/api/admin/subjects", json={
            "name": "test_非法",
            "category": "invalid",
        }, headers=admin_headers)
        assert resp.status_code == 400

    def test_create_duplicate(self, client, admin_headers):
        """科目名重复返回 400"""
        payload = {"name": "test_重复科目", "category": "general"}
        client.post("/api/admin/subjects", json=payload, headers=admin_headers)
        resp = client.post("/api/admin/subjects", json=payload, headers=admin_headers)
        assert resp.status_code == 400
        assert "已存在" in resp.json()["detail"]

    def test_update_success(self, client, admin_headers):
        """修改科目成功"""
        created = client.post("/api/admin/subjects", json={
            "name": "test_待改科目",
            "category": "general",
        }, headers=admin_headers).json()

        resp = client.put(f"/api/admin/subjects/{created['id']}", json={
            "description": "已更新描述",
            "sort_order": 9,
        }, headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "已更新描述"
        assert data["sort_order"] == 9

    def test_update_not_found(self, client, admin_headers):
        """修改不存在的科目返回 404"""
        resp = client.put("/api/admin/subjects/999999", json={"description": "x"},
                          headers=admin_headers)
        assert resp.status_code == 404

    def test_delete_success(self, client, admin_headers):
        """删除科目成功"""
        created = client.post("/api/admin/subjects", json={
            "name": "test_待删科目",
            "category": "general",
        }, headers=admin_headers).json()
        resp = client.delete(f"/api/admin/subjects/{created['id']}", headers=admin_headers)
        assert resp.status_code == 200
        resp = client.delete(f"/api/admin/subjects/{created['id']}", headers=admin_headers)
        assert resp.status_code == 404


class TestSubjectPermission:

    def test_create_forbidden_for_student(self, client, student_headers):
        """学生无权新增科目返回 403"""
        resp = client.post("/api/admin/subjects", json={
            "name": "test_学生禁止",
            "category": "general",
        }, headers=student_headers)
        assert resp.status_code == 403

    def test_delete_forbidden_for_student(self, client, student_headers):
        """学生无权删除科目返回 403"""
        resp = client.delete("/api/admin/subjects/1", headers=student_headers)
        assert resp.status_code == 403
