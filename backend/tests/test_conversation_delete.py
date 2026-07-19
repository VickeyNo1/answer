# -*- coding: utf-8 -*-
"""测试 DELETE /api/conversations/{id} - 删除对话"""


class TestConversationDelete:

    def test_delete_success(self, client, student_headers):
        """删除自己的对话"""
        # 创建对话
        create_resp = client.post(
            "/api/conversations",
            json={"title": "待删除对话"},
            headers=student_headers,
        )
        conv_id = create_resp.json()["id"]

        # 删除
        resp = client.delete(f"/api/conversations/{conv_id}", headers=student_headers)
        assert resp.status_code == 200
        assert resp.json()["message"] == "ok"

        # 确认已删除
        list_resp = client.get("/api/conversations", headers=student_headers)
        ids = [c["id"] for c in list_resp.json()]
        assert conv_id not in ids

    def test_delete_not_found(self, client, student_headers):
        """删除不存在的对话返回 404"""
        resp = client.delete("/api/conversations/99999", headers=student_headers)
        assert resp.status_code == 404

    def test_delete_other_user(self, client, student_headers, admin_headers):
        """不能删除其他用户的对话"""
        # admin 创建对话
        admin_resp = client.post(
            "/api/conversations",
            json={"title": "管理员对话"},
            headers=admin_headers,
        )
        admin_conv_id = admin_resp.json()["id"]

        # student 尝试删除
        resp = client.delete(
            f"/api/conversations/{admin_conv_id}",
            headers=student_headers,
        )
        assert resp.status_code == 404

    def test_delete_without_token(self, client):
        """未认证返回 403"""
        resp = client.delete("/api/conversations/1")
        assert resp.status_code in (401, 403)

    def test_delete_cascades_messages(self, client, student_headers):
        """删除对话时级联删除消息"""
        # 创建对话
        create_resp = client.post(
            "/api/conversations",
            json={"title": "级联删除测试"},
            headers=student_headers,
        )
        conv_id = create_resp.json()["id"]

        # 插入消息
        from app.database import get_db_ctx
        with get_db_ctx() as db:
            db.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
                (conv_id, "user", "测试消息"),
            )
            db.commit()

        # 删除对话
        resp = client.delete(f"/api/conversations/{conv_id}", headers=student_headers)
        assert resp.status_code == 200

        # 确认消息也被删除
        with get_db_ctx() as db:
            cursor = db.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = ?",
                (conv_id,),
            )
            assert cursor.fetchone()["cnt"] == 0
