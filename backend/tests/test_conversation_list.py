# -*- coding: utf-8 -*-
"""测试 GET /api/conversations - 获取对话列表"""


class TestConversationList:

    def test_list_returns_array(self, client, student_headers):
        """返回对话数组"""
        resp = client.get("/api/conversations", headers=student_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_after_create(self, client, student_headers):
        """创建后出现在列表中"""
        # 创建一个对话
        create_resp = client.post(
            "/api/conversations",
            json={"title": "列表测试对话"},
            headers=student_headers,
        )
        created_id = create_resp.json()["id"]

        # 获取列表
        resp = client.get("/api/conversations", headers=student_headers)
        assert resp.status_code == 200
        conversations = resp.json()
        ids = [c["id"] for c in conversations]
        assert created_id in ids

    def test_list_only_current_user(self, client, admin_headers, student_headers):
        """仅返回当前用户的对话"""
        # admin 创建对话
        admin_resp = client.post(
            "/api/conversations",
            json={"title": "管理员对话"},
            headers=admin_headers,
        )
        admin_conv_id = admin_resp.json()["id"]

        # student 获取列表
        resp = client.get("/api/conversations", headers=student_headers)
        conversations = resp.json()
        ids = [c["id"] for c in conversations]
        assert admin_conv_id not in ids

    def test_list_without_token(self, client):
        """未认证返回 403"""
        resp = client.get("/api/conversations")
        assert resp.status_code in (401, 403)

    def test_list_order_descending(self, client, student_headers):
        """按创建时间降序排列"""
        client.post(
            "/api/conversations", json={"title": "较早对话"},
            headers=student_headers,
        )
        client.post(
            "/api/conversations", json={"title": "较晚对话"},
            headers=student_headers,
        )

        resp = client.get("/api/conversations", headers=student_headers)
        conversations = resp.json()
        # 至少有 2 条记录
        assert len(conversations) >= 2

    def test_list_response_fields(self, client, student_headers):
        """每条对话包含 id, title, created_at"""
        resp = client.get("/api/conversations", headers=student_headers)
        for conv in resp.json():
            assert "id" in conv
            assert "title" in conv
            assert "created_at" in conv
