# -*- coding: utf-8 -*-
"""测试 POST /api/chat - SSE 流式对话（mock OpenAI 兼容客户端 + 知识库）

覆盖：
- 直答不触发检索（无 kb_search 事件）
- tool_call → 知识库检索 → 二轮回答 + kp_ids 落库
- 认证/参数校验
- v4.1 意图三分流：solve → solver.run_solve、practice → solver.run_practice、
  consult 仍走 stream_chat；run_solve 的 match 事件被转发为 SSE
- consult 二轮 tool 消息的 prompt 组装（标头防泄漏说明，不依赖数据库）
- consult 出处纪律：直答跳过检索却声称教材出处时的末尾标注 + SYSTEM_PROMPT 硬约束
  （P1-D，不依赖数据库）

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
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
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
            lambda *a, **k: FakeClient(_direct_answer_streams()),
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
                        user_id=0, conversation_id=None, log_enabled=True):
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
                            lambda *a, **k: FakeClient(_tool_call_streams()))
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


# ===== 场景 4：consult 二轮 tool 消息（不依赖数据库） =====

class TestConsultToolResult:
    """直接驱动 stream_chat 生成器，只看发给模型的第二轮 messages

    刻意不用 client/student_headers 夹具：本组验的是 prompt 组装，不碰会话与落库，
    MySQL 不可达时也应当跑（见 AGENTS.md §5「纯函数/生成器类用例不依赖 DB」）。
    """

    def _run(self, monkeypatch, kb_data):
        from app.chat import qwen_service
        fake = FakeClient(_tool_call_streams())
        monkeypatch.setattr(qwen_service, "create_client", lambda *a, **k: fake)
        monkeypatch.setattr(qwen_service.kb_client, "search", lambda *a, **kw: kb_data)
        events = list(qwen_service.stream_chat(
            [{"role": "system", "content": qwen_service.SYSTEM_PROMPT},
             {"role": "user", "content": "存货怎么计价？"}],
            "m", "cpa_acc",
        ))
        return fake.chat.completions.calls, events

    def test_tool_message_carries_marker_notice(self, monkeypatch):
        """P1-B：线上实测模型把「【资料1｜…】」标头行原样抄进了给学生的答案

        说明必须**紧跟在资料之后**，「上方资料」的指代才成立。
        """
        from app.kb.prompt import MARKER_NOTICE
        calls, _ = self._run(monkeypatch, {
            "collection": "textbook",
            "results": [{"knowledge_point_ids": ["KP-001"], "chapter": "第一章",
                         "section": "第一节", "title": "存货计价",
                         "content": "存货应按成本计量。"}],
        })
        content = calls[1]["messages"][-1]["content"]
        assert calls[1]["messages"][-1]["role"] == "tool"
        assert "【资料1｜" in content
        assert MARKER_NOTICE in content
        assert content.index("【资料1｜") < content.index(MARKER_NOTICE)

    def test_empty_kb_result_gets_no_marker_notice(self, monkeypatch):
        """空结果时 tool 内容是 FALLBACK_TEXT，压根没有标头行，不该附说明"""
        from app.kb.prompt import FALLBACK_TEXT, MARKER_NOTICE
        calls, _ = self._run(monkeypatch, {"collection": "textbook", "results": []})
        content = calls[1]["messages"][-1]["content"]
        assert content == FALLBACK_TEXT
        assert MARKER_NOTICE not in content


# ===== 场景 5：consult 出处纪律（P1-D，不依赖数据库） =====

class TestClaimsSource:
    """`claims_source` 的判定边界：只在正文**声称了教材出处**时为真

    判假的代价是漏贴标注（退回到修复前的行为），判真的代价是给闲聊贴一句废话，
    所以两侧都要有明确用例钉住，别日后为了多抓一种形态把寒暄也扫进来。
    """

    @pytest.mark.parametrize("text", [
        "根据《企业会计准则第4号——固定资产》的规定，折旧应当……",
        "《初级会计实务教材》对此有明确说明。",
        "详见教材第21章。",
        "第三章讲了权责发生制。",
        "依据知识点 ACC-21-01-01，融资租赁应确认为……",
        "该考点 ACC-05-02-01 近年常考。",
        "根据教材，存货应按成本计量。",
        "据讲义所述，该处理不正确。",
    ])
    def test_positive(self, text):
        from app.chat import qwen_service
        assert qwen_service.claims_source(text)

    @pytest.mark.parametrize("text", [
        "",
        "你好！有什么可以帮你？",
        "1 + 1 等于 2。",
        "折旧额 = 100 × 40% = 40 万元，最后两年改用年限平均法。",
        # 学生自己贴的案例材料，模型说「根据资料」不是编造教材出处
        "根据资料中给出的入账价值，第一年折旧为 40 万元。",
    ])
    def test_negative(self, text):
        from app.chat import qwen_service
        assert not qwen_service.claims_source(text)


class TestConsultUnverifiedSuffix:
    """模型跳过检索直接作答时的末尾标注（P1-D 的确定性护栏）"""

    def _run(self, monkeypatch, round1_chunks):
        from app.chat import qwen_service
        fake = FakeClient([list(round1_chunks)])
        monkeypatch.setattr(qwen_service, "create_client", lambda *a, **k: fake)
        events = list(qwen_service.stream_chat(
            [{"role": "system", "content": qwen_service.SYSTEM_PROMPT},
             {"role": "user", "content": "存货怎么计价？"}],
            "m", "cpa_acc",
        ))
        return "".join(e.get("content", "") for e in events), events

    def test_fabricated_source_gets_suffix(self, monkeypatch):
        from app.chat import qwen_service
        text, events = self._run(monkeypatch, [
            FakeChunk(content="根据《中级会计教材》第5章，"),
            FakeChunk(content="存货应按成本计量。", finish_reason="stop",
                      usage=FakeUsage(prompt_tokens=9, completion_tokens=4)),
        ])
        assert text.endswith(qwen_service.UNVERIFIED_SUFFIX)
        # 确实没查过知识库：这正是标注要说的事
        assert not [e for e in events if "kb_search" in e]
        assert events[-1]["usage"] == {"prompt_tokens": 9, "completion_tokens": 4}

    def test_plain_direct_answer_gets_no_suffix(self, monkeypatch):
        """寒暄与纯计算不该被贴标注，否则每条闲聊都多一句废话"""
        from app.chat import qwen_service
        text, _ = self._run(monkeypatch, [
            FakeChunk(content="1 + 1 "),
            FakeChunk(content="等于 2。", finish_reason="stop",
                      usage=FakeUsage(prompt_tokens=9, completion_tokens=4)),
        ])
        assert text == "1 + 1 等于 2。"
        assert qwen_service.UNVERIFIED_SUFFIX not in text

    def test_source_claim_split_across_chunks(self, monkeypatch):
        """出处形态跨块到达也要认出来——流式分片切在哪我们说了不算"""
        from app.chat import qwen_service
        text, _ = self._run(monkeypatch, [
            FakeChunk(content="详见《企业会计准"),
            FakeChunk(content="则第4号——固定资产》。", finish_reason="stop",
                      usage=FakeUsage(prompt_tokens=1, completion_tokens=1)),
        ])
        assert text.endswith(qwen_service.UNVERIFIED_SUFFIX)

    def test_retrieval_path_never_uses_this_suffix(self, monkeypatch):
        """查过知识库就归 DEGRADED/EMPTY 两档，第三种标注不得混进来"""
        from app.chat import qwen_service
        fake = FakeClient(_tool_call_streams())
        monkeypatch.setattr(qwen_service, "create_client", lambda *a, **k: fake)
        monkeypatch.setattr(qwen_service.kb_client, "search",
                            lambda *a, **kw: {"collection": "textbook", "results": []})
        events = list(qwen_service.stream_chat(
            [{"role": "system", "content": qwen_service.SYSTEM_PROMPT},
             {"role": "user", "content": "存货怎么计价？"}],
            "m", "cpa_acc",
        ))
        text = "".join(e.get("content", "") for e in events)
        assert qwen_service.UNVERIFIED_SUFFIX not in text
        assert text.endswith(qwen_service.EMPTY_SUFFIX)

    def test_three_no_context_suffixes_are_distinct(self):
        """「没查」「查挂了」「查空了」三态必须可区分，否则运维报表无法归因"""
        from app.chat import qwen_service as q
        assert len({q.UNVERIFIED_SUFFIX, q.DEGRADED_SUFFIX, q.EMPTY_SUFFIX}) == 3


class TestConsultSourceDisciplinePrompt:
    """SYSTEM_PROMPT 的出处纪律（P1-D 的提示词侧修复）"""

    def test_forbids_inventing_sources(self):
        from app.chat import qwen_service
        prompt = qwen_service.SYSTEM_PROMPT
        assert "只能逐字取自检索结果" in prompt
        assert "不得声称任何教材依据" in prompt
        assert "编造" in prompt           # 准则名可提，条文号不许编

    def test_retrieval_no_longer_worded_as_optional(self):
        """旧措辞「优先调用」被模型读成可不调用——这是实测跳过检索的直接原因"""
        from app.chat import qwen_service
        assert "优先调用" not in qwen_service.SYSTEM_PROMPT

    def test_discipline_is_consult_only(self):
        """solve/practice 的资料由后端确定性注入，不适用「先调用检索工具」这套措辞"""
        from app.chat import solver
        for prompt in (solver.SOLVE_SYSTEM_PROMPT, solver.PRACTICE_SYSTEM_PROMPT):
            assert "出处纪律" not in prompt

    def test_round2_system_message_keeps_discipline(self, monkeypatch):
        """编造发生在二轮，纪律必须原样带到二轮 system（只在其后追加建议指令）"""
        from app.chat import qwen_service
        fake = FakeClient(_tool_call_streams())
        monkeypatch.setattr(qwen_service, "create_client", lambda *a, **k: fake)
        monkeypatch.setattr(qwen_service.kb_client, "search", lambda *a, **kw: {
            "collection": "textbook",
            "results": [{"knowledge_point_ids": ["KP-001"], "chapter": "第一章",
                         "section": "第一节", "title": "存货计价",
                         "content": "存货应按成本计量。"}],
        })
        list(qwen_service.stream_chat(
            [{"role": "system", "content": qwen_service.SYSTEM_PROMPT},
             {"role": "user", "content": "存货怎么计价？"}],
            "m", "cpa_acc",
        ))
        round2_system = fake.chat.completions.calls[1]["messages"][0]["content"]
        assert round2_system.startswith(qwen_service.SYSTEM_PROMPT)
        assert round2_system.endswith(qwen_service.SUGGESTIONS_INSTRUCTION)
        assert "出处纪律" in round2_system
