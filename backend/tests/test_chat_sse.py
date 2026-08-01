# -*- coding: utf-8 -*-
"""测试 POST /api/chat - SSE 流式对话（mock OpenAI 兼容客户端 + 知识库）

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


# ===== 模拟 OpenAI 流式响应结构 =====

class FakeFunction:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class FakeToolCallDelta:
    def __init__(self, index=0, id=None, function=None):
        self.index = index
        self.id = id
        self.function = function


class FakeDelta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, delta=None, finish_reason=None):
        self.delta = delta or FakeDelta()
        self.finish_reason = finish_reason


class FakeUsage:
    def __init__(self, prompt_tokens=0, completion_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeChunk:
    """模拟 OpenAI 流式 chunk"""
    def __init__(self, content=None, tool_calls=None, finish_reason=None, usage=None):
        delta = FakeDelta(content=content, tool_calls=tool_calls)
        self.choices = [FakeChoice(delta=delta, finish_reason=finish_reason)]
        self.usage = usage


class FakeCompletions:
    def __init__(self, streams):
        """streams: list of iterables（每次 create() 消费一个）"""
        self._streams = list(streams)
        self._idx = 0

    def create(self, **kwargs):
        stream = self._streams[self._idx]
        self._idx += 1
        return iter(stream)


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeClient:
    def __init__(self, streams):
        self.chat = FakeChat(FakeCompletions(streams))


# ===== 场景 1：直答 =====

def _direct_answer_streams():
    """直答：无工具调用，直接返回内容"""
    return [[
        FakeChunk(content="1 + 1 "),
        FakeChunk(content="等于 2。", finish_reason="stop",
                  usage=FakeUsage(prompt_tokens=10, completion_tokens=5)),
    ]]


class TestChatDirectAnswer:
    """直答场景：模型不触发知识库检索"""

    @pytest.fixture(autouse=True)
    def _mock(self, monkeypatch):
        monkeypatch.setattr(
            "app.chat.qwen_service.create_client",
            lambda: FakeClient(_direct_answer_streams()),
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


# ===== 场景 2：工具调用 → 知识库检索 → 二轮回答 =====

def _tool_call_streams():
    """两轮：第 1 轮返回 tool_calls，第 2 轮返回最终答案"""
    round1 = [
        FakeChunk(
            tool_calls=[FakeToolCallDelta(
                index=0, id="call_1",
                function=FakeFunction(
                    name="search_cpa_knowledge",
                    arguments='{"query": "存货计价", "collection": "textbook"}',
                ),
            )],
            finish_reason="tool_calls",
            usage=FakeUsage(prompt_tokens=20, completion_tokens=8),
        ),
    ]
    round2 = [
        FakeChunk(content="存货应按成本计量。"),
        FakeChunk(content="依据知识点 KP-001。", finish_reason="stop",
                  usage=FakeUsage(prompt_tokens=50, completion_tokens=12)),
    ]
    return [round1, round2]


class TestChatToolCall:
    """工具调用场景：模型触发知识库检索并二轮作答"""

    @pytest.fixture(autouse=True)
    def _mock(self, monkeypatch):
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

        monkeypatch.setattr("app.chat.qwen_service.create_client",
                            lambda: FakeClient(_tool_call_streams()))
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
