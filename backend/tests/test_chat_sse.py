# -*- coding: utf-8 -*-
"""测试 POST /api/chat - SSE 流式对话"""
import json
import pytest


def parse_sse_events(response_text: str) -> list[dict]:
    """解析 SSE 响应文本，返回事件列表"""
    events = []
    for line in response_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            data_str = line[6:]
            try:
                events.append(json.loads(data_str))
            except json.JSONDecodeError:
                pass
    return events


class TestChatSSE:

    def test_chat_without_token(self, client):
        """未认证返回 403"""
        resp = client.post("/api/chat", json={"message": "你好"})
        assert resp.status_code in (401, 403)

    def test_chat_auto_create_conversation(self, client, student_headers):
        """conversation_id 为 null 时自动新建对话"""
        resp = client.post("/api/chat", json={
            "conversation_id": None,
            "message": "你好",
        }, headers=student_headers)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events = parse_sse_events(resp.text)
        # 应该有 start 事件
        start_events = [e for e in events if e.get("type") == "start"]
        assert len(start_events) >= 1
        assert "conversation_id" in start_events[0]

    def test_chat_returns_delta_and_done(self, client, student_headers):
        """SSE 流式返回 delta 和 done 事件"""
        resp = client.post("/api/chat", json={
            "conversation_id": None,
            "message": "1+1等于几？",
        }, headers=student_headers)
        assert resp.status_code == 200

        events = parse_sse_events(resp.text)
        types = [e.get("type") for e in events]
        assert "start" in types
        assert "delta" in types
        assert "done" in types

        # delta 事件应有内容
        delta_contents = "".join(
            e.get("content", "") for e in events if e.get("type") == "delta"
        )
        assert len(delta_contents) > 0

    def test_chat_with_existing_conversation(self, client, student_headers):
        """在已有对话中继续提问"""
        # 先创建对话
        create_resp = client.post(
            "/api/conversations", json={"title": "测试对话"},
            headers=student_headers,
        )
        conv_id = create_resp.json()["id"]

        # 在该对话中提问
        resp = client.post("/api/chat", json={
            "conversation_id": conv_id,
            "message": "你好",
        }, headers=student_headers)
        assert resp.status_code == 200

        events = parse_sse_events(resp.text)
        start_events = [e for e in events if e.get("type") == "start"]
        assert start_events[0]["conversation_id"] == conv_id

    def test_chat_missing_message(self, client, student_headers):
        """缺少 message 字段返回 422"""
        resp = client.post("/api/chat", json={
            "conversation_id": None,
        }, headers=student_headers)
        assert resp.status_code == 422
