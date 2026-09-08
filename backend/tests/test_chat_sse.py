# -*- coding: utf-8 -*-
"""测试 POST /api/chat - SSE 流式对话（mock OpenAI 兼容客户端 + 知识库）

覆盖：
- 直答不触发检索（无 kb_search 事件）
- tool_call → 知识库检索 → 二轮回答 + kp_ids 落库
- 认证/参数校验
- v4.1 意图三分流：solve → solver.run_solve、practice → solver.run_practice、
  consult 仍走 stream_chat；run_solve 的 match 事件被转发为 SSE

⚠️ 前两组（TestChatDirectAnswer / TestChatToolCall）同时是 `stream_answer` 抽取
重构的护栏：那 8 个用例必须全绿，任一挂了就说明抽取改变了外部行为。
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


# ===== 场景 3：意图三分流（v4.1） =====

class TestChatIntentRouting:
    """router 必须按意图把请求交给正确的流水线

    用哨兵生成器替换真实实现：既避免真连百炼/知识库，又能明确断言「哪条路被走了」。
    """

    @staticmethod
    def _sentinel(tag):
        def _gen():
            yield {"kb_search": True}
            yield {"content": f"来自{tag}的解答"}
            yield {"usage": {"prompt_tokens": 3, "completion_tokens": 4}}
        return _gen

    @pytest.fixture
    def spies(self, monkeypatch):
        """替换三条流水线，返回记录调用情况的 dict"""
        from app.chat import qwen_service, router as chat_router, solver
        seen = {"solve": [], "practice": [], "consult": []}

        def _spy(tag):
            body = TestChatIntentRouting._sentinel(tag)

            def _gen(*args, **kwargs):
                seen[tag].append({"args": args, "kwargs": kwargs})
                yield from body()
            return _gen

        monkeypatch.setattr(solver, "run_solve", _spy("solve"))
        monkeypatch.setattr(solver, "run_practice", _spy("practice"))
        # router 用 from ... import stream_chat 直接持有绑定；两处都替换，
        # 日后若改回 qwen_service.stream_chat(...) 调用，本用例仍守得住
        monkeypatch.setattr(chat_router, "stream_chat", _spy("consult"))
        monkeypatch.setattr(qwen_service, "stream_chat", _spy("consult"))
        return seen

    def _post(self, client, student_headers, message):
        resp = client.post("/api/chat", json={
            "conversation_id": None, "message": message, "subject": "cpa_acc",
        }, headers=student_headers)
        assert resp.status_code == 200
        return parse_sse_events(resp.text)

    def test_solve_intent_routed_to_run_solve(self, client, student_headers, spies):
        events = self._post(client, student_headers, "这道题怎么做？甲公司购入存货一批。")
        assert len(spies["solve"]) == 1
        assert not spies["practice"] and not spies["consult"]
        content = "".join(e.get("content", "") for e in events if e.get("type") == "delta")
        assert "来自solve的解答" in content

    def test_practice_intent_routed_to_run_practice(self, client, student_headers, spies):
        events = self._post(client, student_headers, "给我几道租赁的练习题")
        assert len(spies["practice"]) == 1
        assert not spies["solve"] and not spies["consult"]
        content = "".join(e.get("content", "") for e in events if e.get("type") == "delta")
        assert "来自practice的解答" in content

    def test_consult_intent_keeps_legacy_path(self, client, student_headers, spies):
        """**回归锚点**：概念性问题必须仍走 Function Calling 老路径，行为与 v4.0 一致"""
        events = self._post(client, student_headers, "存货怎么计价？")
        assert len(spies["consult"]) == 1
        assert not spies["solve"] and not spies["practice"]
        types = [e.get("type") for e in events]
        assert "match" not in types          # 档位事件是 solve 专属

    def test_solve_receives_clean_retrieval_query(self, client, student_headers, spies):
        """run_solve 的 query_text 是检索用语料，必须是学生原话而非组合后的 effective_message"""
        self._post(client, student_headers, "本题要求编制会计分录")
        args = spies["solve"][0]["args"]
        assert args[-1] == "本题要求编制会计分录"

    def test_match_event_forwarded_as_sse(self, client, student_headers, monkeypatch):
        """run_solve 下发的 match 事件要被 router 转发

        前端 lib/sse.ts 的 switch 没有 default 分支，未知事件静默忽略，所以本轮
        前端零改动；下一轮批量答题工具直接消费该事件拿结构化档位。
        """
        from app.chat import solver

        def _gen(*args, **kwargs):
            yield {"match": {"tier": "similar", "question_id": None,
                             "verify_reason": "金额不同", "kb_scores": [0.71]}}
            yield {"content": "解答"}
            yield {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}

        monkeypatch.setattr(solver, "run_solve", _gen)
        events = self._post(client, student_headers, "这道题怎么解？")
        match = next(e for e in events if e.get("type") == "match")
        assert match == {"type": "match", "tier": "similar", "question_id": None,
                         "verify_reason": "金额不同", "kb_scores": [0.71]}

    def test_solve_usage_still_recorded(self, client, student_headers, spies):
        """三条流水线都 yield {"usage": ...}，router 的记账代码无需感知意图"""
        from app.database import get_db_ctx
        events = self._post(client, student_headers, "这道题怎么做？")
        assert [e.get("type") for e in events][-1] == "done"
        with get_db_ctx() as db:
            row = db.execute(
                "SELECT prompt_tokens, completion_tokens FROM usage_logs "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["prompt_tokens"] == 3 and row["completion_tokens"] == 4
