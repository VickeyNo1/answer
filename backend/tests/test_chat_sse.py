# -*- coding: utf-8 -*-
"""测试 POST /api/chat - SSE 流式对话（mock dashscope + 知识库）

覆盖：
- 直答不触发检索（无 kb_search 事件）
- tool_call → 知识库检索 → 二轮回答 + kp_ids 落库
- 认证/参数校验
"""
import json
import pytest


def parse_sse_events(response_text: str) -> list[dict]:
    """解析 SSE 响应文本，返回事件列表"""
    events = []
    for line in response_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


class FakeResponse:
    """模拟 dashscope Generation.call 的流式响应块"""

    def __init__(self, status_code=200, content="", tool_calls=None,
                 finish_reason=None, usage=None, code="", message=""):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.usage = usage
        msg: dict = {}
        if content:
            msg["content"] = content
        if tool_calls is not None:
            msg["tool_calls"] = tool_calls
        self.output = {"choices": [{"message": msg, "finish_reason": finish_reason}]}


def _direct_answer_gen(*args, **kwargs):
    """直答：无工具调用，直接返回内容"""
    yield FakeResponse(content="1 + 1 ")
    yield FakeResponse(content="等于 2。", finish_reason="stop",
                       usage={"input_tokens": 10, "output_tokens": 5})


class TestChatDirectAnswer:
    """直答场景：模型不触发知识库检索"""

    @pytest.fixture(autouse=True)
    def _mock(self, monkeypatch):
        monkeypatch.setattr(
            "app.chat.qwen_service.Generation.call",
            staticmethod(_direct_answer_gen),
        )

    def test_chat_without_token(self, client):
        resp = client.post("/api/chat", json={"message": "你好"})
        assert resp.status_code in (401, 403)

    def test_chat_missing_message(self, client, student_headers):
        resp = client.post("/api/chat", json={"conversation_id": None},
                           headers=student_headers)
        assert resp.status_code == 422

    def test_chat_auto_create_conversation(self, client, student_headers):
        resp = client.post("/api/chat", json={
            "conversation_id": None, "message": "1+1等于几？",
        }, headers=student_headers)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events = parse_sse_events(resp.text)
        types = [e.get("type") for e in events]
        assert "start" in types
        assert "delta" in types
        assert "done" in types
        # 直答不应触发知识库检索
        assert "kb_search" not in types

    def test_chat_delta_content(self, client, student_headers):
        resp = client.post("/api/chat", json={
            "conversation_id": None, "message": "1+1等于几？",
        }, headers=student_headers)
        events = parse_sse_events(resp.text)
        content = "".join(
            e.get("content", "") for e in events if e.get("type") == "delta"
        )
        assert "等于 2" in content

    def test_chat_default_subject(self, client, student_headers):
        """未传 subject 时默认 cpa_acc，并持久化到对话"""
        resp = client.post("/api/chat", json={
            "conversation_id": None, "message": "你好",
        }, headers=student_headers)
        conv_id = parse_sse_events(resp.text)[0]["conversation_id"]

        from app.database import get_db_ctx
        with get_db_ctx() as db:
            row = db.execute(
                "SELECT subject FROM conversations WHERE id = %s", (conv_id,)
            ).fetchone()
        assert row["subject"] == "cpa_acc"

    def test_chat_invalid_subject_fallback(self, client, student_headers):
        """非法 subject 回退到默认科目"""
        resp = client.post("/api/chat", json={
            "conversation_id": None, "message": "你好", "subject": "not_exist",
        }, headers=student_headers)
        conv_id = parse_sse_events(resp.text)[0]["conversation_id"]

        from app.database import get_db_ctx
        with get_db_ctx() as db:
            row = db.execute(
                "SELECT subject FROM conversations WHERE id = %s", (conv_id,)
            ).fetchone()
        assert row["subject"] == "cpa_acc"


class TestChatToolCall:
    """工具调用场景：模型触发知识库检索并二轮作答"""

    @pytest.fixture(autouse=True)
    def _mock(self, monkeypatch):
        # 两轮 Generation.call：第 1 轮返回 tool_calls，第 2 轮返回最终答案
        state = {"n": 0}

        def fake_call(*args, **kwargs):
            state["n"] += 1
            if state["n"] == 1:
                def gen1():
                    yield FakeResponse(
                        tool_calls=[{
                            "index": 0,
                            "id": "call_1",
                            "function": {
                                "name": "search_cpa_knowledge",
                                "arguments": '{"query": "存货计价", "collection": "textbook"}',
                            },
                        }],
                        finish_reason="tool_calls",
                        usage={"input_tokens": 20, "output_tokens": 8},
                    )
                return gen1()

            def gen2():
                yield FakeResponse(content="存货应按成本计量。")
                yield FakeResponse(content="依据知识点 KP-001。",
                                   finish_reason="stop",
                                   usage={"input_tokens": 50, "output_tokens": 12})
            return gen2()

        def fake_search(query, subject, collection="textbook", top_k=5,
                        user_id=0, conversation_id=None):
            assert subject == "cpa_acc"  # subject 由后端注入
            return {
                "code": 0,
                "collection": "textbook",
                "results": [{
                    "knowledge_point_ids": ["KP-001", "KP-002"],
                    "chapter": "第一章", "section": "第一节",
                    "title": "存货计价", "content": "存货应按成本计量。",
                }],
            }

        monkeypatch.setattr("app.chat.qwen_service.Generation.call",
                            staticmethod(fake_call))
        monkeypatch.setattr("app.chat.qwen_service.kb_client.search", fake_search)

    def test_chat_triggers_kb_search(self, client, student_headers):
        resp = client.post("/api/chat", json={
            "conversation_id": None, "message": "存货怎么计价？", "subject": "cpa_acc",
        }, headers=student_headers)
        assert resp.status_code == 200

        events = parse_sse_events(resp.text)
        types = [e.get("type") for e in events]
        assert "kb_search" in types
        assert "kp_ids" in types

        # kp_ids 事件应包含检索到的知识点
        kp_event = next(e for e in events if e.get("type") == "kp_ids")
        assert kp_event["kp_ids"] == ["KP-001", "KP-002"]

        # 最终答案来自第二轮
        content = "".join(
            e.get("content", "") for e in events if e.get("type") == "delta"
        )
        assert "存货应按成本计量" in content

    def test_kp_ids_persisted(self, client, student_headers):
        """kp_ids 落库到 messages.knowledge_point_ids"""
        resp = client.post("/api/chat", json={
            "conversation_id": None, "message": "存货怎么计价？", "subject": "cpa_acc",
        }, headers=student_headers)
        conv_id = parse_sse_events(resp.text)[0]["conversation_id"]

        from app.database import get_db_ctx
        with get_db_ctx() as db:
            row = db.execute(
                "SELECT knowledge_point_ids FROM messages "
                "WHERE conversation_id = %s AND role = 'assistant' "
                "ORDER BY id DESC LIMIT 1",
                (conv_id,),
            ).fetchone()
        assert row is not None
        assert json.loads(row["knowledge_point_ids"]) == ["KP-001", "KP-002"]
