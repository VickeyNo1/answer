# -*- coding: utf-8 -*-
"""测试 DELETE /api/admin/students/{id} - 删除学生"""
import pytest
from app.database import get_db_ctx


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with get_db_ctx() as db:
        db.execute("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id IN (SELECT id FROM users WHERE student_id LIKE 'del_test_%'))")
        db.execute("DELETE FROM conversations WHERE user_id IN (SELECT id FROM users WHERE student_id LIKE 'del_test_%')")
        db.execute("DELETE FROM users WHERE student_id LIKE 'del_test_%'")
        db.commit()


class TestAdminStudentDelete:

    def test_delete_success(self, client, admin_headers):
        """删除学生成功"""
        create_resp = client.post("/api/admin/students", json={
            "student_id": "del_test_001",
            "name": "待删除",
            "password": "pass123",
        }, headers=admin_headers)
        student_id = create_resp.json()["id"]

        resp = client.delete(f"/api/admin/students/{student_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["message"] == "ok"

    def test_delete_not_found(self, client, admin_headers):
        """删除不存在的学生返回 404"""
        resp = client.delete("/api/admin/students/99999", headers=admin_headers)
        assert resp.status_code == 404

    def test_delete_admin_forbidden(self, client, admin_headers):
        """不能删除管理员账号"""
        # admin 的 id 是 1
        resp = client.delete("/api/admin/students/1", headers=admin_headers)
        assert resp.status_code == 403
        assert "管理员" in resp.json()["detail"]

    def test_delete_without_token(self, client):
        """未认证返回 403"""
        resp = client.delete("/api/admin/students/2")
        assert resp.status_code in (401, 403)

    def test_delete_student_forbidden(self, client, student_headers):
        """学生无权删除返回 403"""
        resp = client.delete("/api/admin/students/2", headers=student_headers)
        assert resp.status_code == 403

    def test_delete_cascades_conversations(self, client, admin_headers):
        """删除学生时级联删除对话和消息"""
        # 创建学生
        create_resp = client.post("/api/admin/students", json={
            "student_id": "del_test_002",
            "name": "级联删除测试",
            "password": "pass123",
        }, headers=admin_headers)
        student_id = create_resp.json()["id"]

        # 创建对话和消息
        with get_db_ctx() as db:
            cursor = db.execute(
                "INSERT INTO conversations (user_id, title) VALUES (%s, %s)",
                (student_id, "测试对话"),
            )
            conv_id = cursor.lastrowid
            db.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conv_id, "user", "测试消息"),
            )
            db.commit()

        # 删除学生
        resp = client.delete(f"/api/admin/students/{student_id}", headers=admin_headers)
        assert resp.status_code == 200

        # 确认对话和消息也被删除
        with get_db_ctx() as db:
            conv_count = db.execute(
                "SELECT COUNT(*) as cnt FROM conversations WHERE user_id = %s",
                (student_id,),
            ).fetchone()["cnt"]
            msg_count = db.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = %s",
                (conv_id,),
            ).fetchone()["cnt"]
            assert conv_count == 0
            assert msg_count == 0
