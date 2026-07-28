# -*- coding: utf-8 -*-
"""测试 GET /api/conversations/{id} - 获取对话消息历史"""


class TestConversationMessages:

    def test_get_messages_empty(self, client, student_headers):
        """空对话返回空数组"""
        # 创建空对话
        create_resp = client.post(
            "/api/conversations",
            json={"title": "空对话"},
            headers=student_headers,
        )
        conv_id = create_resp.json()["id"]

        resp = client.get(f"/api/conversations/{conv_id}", headers=student_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_messages_with_data(self, client, student_headers):
        """有消息的对话返回消息列表"""
        # 创建对话
        create_resp = client.post(
            "/api/conversations",
            json={"title": "有消息对话"},
            headers=student_headers,
        )
        conv_id = create_resp.json()["id"]

        # 手动插入消息
        from app.database import get_db_ctx
        with get_db_ctx() as db:
            db.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conv_id, "user", "什么是借贷记账法？"),
            )
            db.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conv_id, "assistant", "借贷记账法是一种复式记账方法。"),
            )
            db.commit()

        resp = client.get(f"/api/conversations/{conv_id}", headers=student_headers)
        assert resp.status_code == 200
        messages = resp.json()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_get_messages_not_found(self, client, student_headers):
        """不存在的对话返回 404"""
        resp = client.get("/api/conversations/99999", headers=student_headers)
        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    def test_get_messages_other_user(self, client, student_headers, admin_headers):
        """不能查看其他用户的对话"""
        # admin 创建对话
        admin_resp = client.post(
            "/api/conversations",
            json={"title": "管理员私密对话"},
            headers=admin_headers,
        )
        admin_conv_id = admin_resp.json()["id"]

        # student 尝试访问
        resp = client.get(f"/api/conversations/{admin_conv_id}", headers=student_headers)
        assert resp.status_code == 404

    def test_get_messages_without_token(self, client):
        """未认证返回 403"""
        resp = client.get("/api/conversations/1")
        assert resp.status_code in (401, 403)

    def test_get_messages_order_ascending(self, client, student_headers):
        """消息按时间升序排列"""
        create_resp = client.post(
            "/api/conversations",
            json={"title": "排序测试"},
            headers=student_headers,
        )
        conv_id = create_resp.json()["id"]

        from app.database import get_db_ctx
        with get_db_ctx() as db:
            db.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conv_id, "user", "第一条"),
            )
            db.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conv_id, "assistant", "第二条"),
            )
            db.commit()

        resp = client.get(f"/api/conversations/{conv_id}", headers=student_headers)
        messages = resp.json()
        assert messages[0]["content"] == "第一条"
        assert messages[1]["content"] == "第二条"
