# -*- coding: utf-8 -*-
"""测试 POST /api/conversations - 新建对话"""


class TestConversationCreate:

    def test_create_with_title(self, client, student_headers):
        """指定标题创建对话"""
        resp = client.post(
            "/api/conversations",
            json={"title": "关于固定资产的疑问"},
            headers=student_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] > 0
        assert data["title"] == "关于固定资产的疑问"
        assert "created_at" in data

    def test_create_default_title(self, client, student_headers):
        """不传标题使用默认值"""
        resp = client.post(
            "/api/conversations",
            json={},
            headers=student_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "新对话"

    def test_create_without_token(self, client):
        """未认证返回 403"""
        resp = client.post("/api/conversations", json={"title": "test"})
        assert resp.status_code in (401, 403)

    def test_create_empty_title(self, client, student_headers):
        """空字符串标题"""
        resp = client.post(
            "/api/conversations",
            json={"title": ""},
            headers=student_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == ""

    def test_create_response_model_fields(self, client, student_headers):
        """响应包含所有必要字段"""
        resp = client.post(
            "/api/conversations",
            json={"title": "字段测试"},
            headers=student_headers,
        )
        data = resp.json()
        assert {"id", "title", "created_at"}.issubset(set(data.keys()))
