# -*- coding: utf-8 -*-
"""批量评测端点测试（v4.1，配套 backend/scripts/batch_eval.py）

分两组：

- **无 DB 组**：直接调 `answer_one()`，打桩三条作答链路，验证入参校验、意图路由、
  事件收集、`log_enabled` 抑制、`user_id` 传 NULL、用量记账口径。
- **DB 组**：TestClient + **真实** kb_client / solver / llm_store（只桩 `httpx.post`
  与 `create_client`），验证三条隔离保证真的落到了库上，而不是被桩绕过去。

⚠️ 打桩认准模块绑定（AGENTS.md §6 的同一课）：

- `eval.py` 写的是 `from app.chat.qwen_service import stream_chat` → `stream_chat` 是
  本模块局部名，**必须 patch `app.admin.eval.stream_chat`**，patch qwen_service 无效；
- `eval.py` 写的是 `from app.chat import solver` → solver 是模块对象，
  patch `solver.run_solve` / `solver.run_practice` 即可；
- `create_client` 在 solver 与 qwen_service **各自** import：solve 路径的作答与 verify
  都在 solver 命名空间内，patch `app.chat.solver.create_client` 就够；consult 路径
  另需 patch `app.chat.qwen_service.create_client`。
"""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.admin import eval as eval_mod
from app.models import EvalAnswerOut, EvalAnswerRequest

ADMIN = {"user_id": 1, "student_id": "admin", "role": "admin", "name": "管理员"}

# 基准题面是书面陈述句：无强 solve 标记、长度不足 60，classify_intent 判 consult
CONSULT_SHAPED = "企业会计确认、计量和报告原则上采用什么会计基础？"
SOLVE_SHAPED = "这道题怎么做？甲公司购入存货一批，价款100万元。"
PRACTICE_SHAPED = "给我出几道租赁的练习题"

DEFAULT_EVENTS = [
    {"kb_search": True},
    {"match": {"tier": "similar", "question_id": "Q-001",
               "verify_reason": "同知识点不同金额", "kb_scores": [0.5]}},
    {"kp_ids": ["ACC-01-01-01"]},
    {"kb_refs": [{"title": "题库 Q-001", "chapter": "第一章 总论"}]},
    {"content": "解答上半段"},
    {"content": "解答下半段"},
    {"suggestions": ["追问一"]},
    {"usage": {"prompt_tokens": 111, "completion_tokens": 22}},
]


@pytest.fixture
def chain(monkeypatch):
    """打桩三条作答链路 + 选模型 + 用量记账（无 DB）

    装配时即装默认桩，避免用例漏配时真连百炼。
    """
    state = {"events": list(DEFAULT_EVENTS)}
    calls = {"solve": [], "practice": [], "consult": []}
    usage_rows: list[dict] = []

    def _mk(key):
        def _stub(*args, **kwargs):
            calls[key].append({"args": args, "kwargs": kwargs})
            return iter(list(state["events"]))
        return _stub

    monkeypatch.setattr(eval_mod.solver, "run_solve", _mk("solve"))
    monkeypatch.setattr(eval_mod.solver, "run_practice", _mk("practice"))
    monkeypatch.setattr(eval_mod, "stream_chat", _mk("consult"))
    monkeypatch.setattr(eval_mod.llm_store, "get_model_for", lambda t: "eval-model")
    monkeypatch.setattr(
        eval_mod.llm_store, "record_usage",
        lambda model, uid, cid, tin, tout, task_type="chat": usage_rows.append(
            {"model": model, "user_id": uid, "conversation_id": cid,
             "in": tin, "out": tout, "task_type": task_type}),
    )

    return SimpleNamespace(
        calls=calls, usage=usage_rows,
        set_events=lambda events: state.__setitem__("events", list(events)),
    )


def _call(question=CONSULT_SHAPED, **kw) -> EvalAnswerOut:
    return eval_mod.answer_one(EvalAnswerRequest(question=question, **kw), ADMIN)


def _only(chain_obj, key):
    """断言只走了 key 那条链路，返回其唯一一次调用记录"""
    used = [k for k, v in chain_obj.calls.items() if v]
    assert used == [key], f"应只走 {key}，实际走了 {used}"
    return chain_obj.calls[key][0]


# ========== 入参校验 ==========


class TestValidation:
    @pytest.mark.parametrize("bad", ["", "   ", "\n\t "])
    def test_blank_question_rejected(self, chain, bad):
        with pytest.raises(HTTPException) as ei:
            _call(question=bad)
        assert ei.value.status_code == 400
        assert not any(chain.calls.values()), "校验失败时不得触发任何作答链路"

    def test_unknown_intent_rejected(self, chain):
        with pytest.raises(HTTPException) as ei:
            _call(intent="practice")
        assert ei.value.status_code == 400
        assert "solve" in ei.value.detail and "auto" in ei.value.detail

    def test_question_is_stripped_before_use(self, chain):
        out = _call(question="  甲公司购入存货  ")
        assert out.question == "甲公司购入存货"
        # 检索 query 用的也是 stripped 后的文本
        assert _only(chain, "solve")["args"][5] == "甲公司购入存货"

    def test_invalid_subject_falls_back_not_400(self, chain):
        """科目非法属可恢复：回退默认枚举，不该让整批 400 题中断"""
        out = _call(subject="cpa_tax")
        assert _only(chain, "solve")["args"][2] == "cpa_acc"
        assert out.error is None


# ========== 意图路由 ==========


class TestIntentRouting:
    def test_default_intent_is_solve(self):
        assert EvalAnswerRequest(question="随便一句").intent == "solve"

    def test_forced_solve_never_calls_classifier(self, chain, monkeypatch):
        """**默认档的核心保证**：基准题面 86.5% 会被判成 consult，
        而 consult 路径没有三档命中、不碰题库，评测不到答题能力"""
        def _boom(*a, **kw):
            raise AssertionError("intent='solve' 时不得调用 classify_intent")
        monkeypatch.setattr(eval_mod, "classify_intent", _boom)
        out = _call(question=CONSULT_SHAPED)
        assert out.intent == "solve"
        _only(chain, "solve")

    def test_auto_routes_consult_shaped_to_stream_chat(self, chain):
        out = _call(question=CONSULT_SHAPED, intent="auto")
        assert out.intent == "consult"
        _only(chain, "consult")

    def test_auto_routes_solve_shaped_to_run_solve(self, chain):
        out = _call(question=SOLVE_SHAPED, intent="auto")
        assert out.intent == "solve"
        _only(chain, "solve")

    def test_auto_routes_practice_shaped_to_run_practice(self, chain):
        out = _call(question=PRACTICE_SHAPED, intent="auto")
        assert out.intent == "practice"
        _only(chain, "practice")

    def test_solve_prompt_used_for_solve_intent(self, chain):
        """solve 走 SOLVE_SYSTEM_PROMPT（含「必须给出完整解答」），consult 保持默认"""
        from app.chat import solver
        _call(question=SOLVE_SHAPED)
        msgs = chain.calls["solve"][-1]["args"][0]
        assert msgs[0]["content"].startswith(solver.SOLVE_SYSTEM_PROMPT)

    def test_consult_keeps_default_system_prompt(self, chain):
        _call(question=CONSULT_SHAPED, intent="auto")
        msgs = chain.calls["consult"][-1]["args"][0]
        from app.chat.qwen_service import SYSTEM_PROMPT
        assert msgs[0]["content"].startswith(SYSTEM_PROMPT)


# ========== 事件收集 ==========


class TestDrain:
    def test_all_structured_fields_collected(self, chain):
        out = _call()
        assert out.answer == "解答上半段解答下半段"
        assert out.tier == "similar"
        assert out.question_id == "Q-001"
        assert out.verify_reason == "同知识点不同金额"
        assert out.kp_ids == ["ACC-01-01-01"]
        assert out.kb_refs == [{"title": "题库 Q-001", "chapter": "第一章 总论"}]
        assert out.suggestions == ["追问一"]
        assert (out.prompt_tokens, out.completion_tokens) == (111, 22)
        assert out.model == "eval-model"
        assert out.error is None
        assert out.elapsed_ms >= 0

    def test_unknown_event_keys_ignored(self, chain):
        """kb_search 这类进度事件在评测里没有对应字段，不得因此崩"""
        chain.set_events([{"kb_search": True}, {"content": "正文"}])
        assert _call().answer == "正文"

    def test_no_match_event_leaves_tier_none(self, chain):
        """consult 路径不发 match，tier 必须留空而不是报错"""
        chain.set_events([{"content": "正文"},
                          {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}])
        out = _call(intent="auto")
        assert out.tier is None and out.question_id is None
        assert out.verify_reason == ""

    def test_error_event_stops_drain_and_is_reported(self, chain):
        chain.set_events([{"content": "开头"}, {"error": "连接被重置"}, {"content": "不该出现"}])
        out = _call()
        assert out.error == "连接被重置"
        assert out.answer == "开头"          # 已产出的正文保留，便于排查
        assert "不该出现" not in out.answer

    def test_empty_content_yields_empty_answer(self, chain):
        chain.set_events([{"content": ""}, {"usage": {"prompt_tokens": 0,
                                                      "completion_tokens": 0}}])
        assert _call().answer == ""


# ========== 链路入参：隔离契约 ==========


class TestChainArguments:
    def test_solve_gets_null_identity_and_suppressed_logging(self, chain):
        _call()
        rec = _only(chain, "solve")
        args, kw = rec["args"], rec["kwargs"]
        assert args[2] == "cpa_acc"
        assert args[3] is None, "user_id 必须传 None（usage_logs 该列可空、无外键）"
        assert args[4] is None, "conversation_id 必须传 None（不落库对话）"
        assert args[5] == CONSULT_SHAPED, "query_text 必须是题干原文"
        assert kw == {"log_enabled": False, "disable_kb": False, "verify_model": None}

    def test_practice_gets_null_identity_and_suppressed_logging(self, chain):
        _call(question=PRACTICE_SHAPED, intent="auto")
        rec = _only(chain, "practice")
        assert rec["args"][3] is None and rec["args"][4] is None
        assert rec["kwargs"] == {"log_enabled": False}

    def test_consult_gets_null_identity_and_suppressed_logging(self, chain):
        _call(intent="auto")
        rec = _only(chain, "consult")
        assert rec["args"][3] is None and rec["args"][4] is None
        assert rec["kwargs"] == {"log_enabled": False}

    def test_model_comes_from_eval_task_type(self, chain, monkeypatch):
        """评测固定用 EVAL_MODEL 档，不受生产对话切换激活模型影响"""
        seen = []
        monkeypatch.setattr(eval_mod.llm_store, "get_model_for",
                            lambda t: seen.append(t) or "cheap-model")
        out = _call()
        assert seen == ["eval"]
        assert out.model == "cheap-model"
        assert chain.calls["solve"][0]["args"][1] == "cheap-model"

    def test_no_history_and_no_memory_injected(self, chain):
        """评测必须单轮、无记忆：多轮历史与画像注入会让 400 题互相污染"""
        _call()
        msgs = _only(chain, "solve")["args"][0]
        assert [m["role"] for m in msgs] == ["system", "user"]
        assert msgs[-1]["content"] == CONSULT_SHAPED


# ========== 用量记账 ==========


class TestUsageAccounting:
    def test_recorded_as_eval_task_with_null_owner(self, chain):
        _call()
        assert chain.usage == [{"model": "eval-model", "user_id": None,
                                "conversation_id": None, "in": 111, "out": 22,
                                "task_type": "eval"}]

    def test_zero_tokens_not_recorded(self, chain):
        chain.set_events([{"content": "正文"},
                          {"usage": {"prompt_tokens": 0, "completion_tokens": 0}}])
        _call()
        assert chain.usage == []

    def test_missing_usage_event_not_recorded(self, chain):
        chain.set_events([{"content": "正文"}])
        _call()
        assert chain.usage == []

    def test_still_recorded_when_stream_errored(self, chain):
        """出错也要记账：token 已真实消耗，静默丢掉会让评测成本对不上账"""
        chain.set_events([{"usage": {"prompt_tokens": 50, "completion_tokens": 5}},
                          {"error": "上游 500"}])
        out = _call()
        assert out.error == "上游 500"
        assert len(chain.usage) == 1 and chain.usage[0]["in"] == 50

    def test_record_failure_does_not_break_response(self, chain, monkeypatch):
        def _boom(*a, **kw):
            raise RuntimeError("DB 不可达")
        monkeypatch.setattr(eval_mod.llm_store, "record_usage", _boom)
        out = _call()
        assert out.answer == "解答上半段解答下半段" and out.error is None


# ========== 金标准隔离 ==========


class TestGoldIsolation:
    def test_request_has_exactly_one_content_field(self):
        """基准题库自带金标准答案与关键得分点，那些字段一旦进请求体就等于把答案
        喂给被测系统，评测结果直接作废。谁给这个 schema 加内容字段，这条就红。
        （mode/model_name 是实验控制参数，不是内容字段，2026-09-16 消融实验加入）
        """
        assert set(EvalAnswerRequest.model_fields) == {
            "question", "subject", "intent", "mode", "model_name",
        }

    def test_smuggled_gold_fields_never_reach_the_chain(self, chain):
        """脚本若误把金标准一起 POST 上来，必须在 schema 层被丢掉

        断言两件事：额外键不落进模型实例；真正送进作答链路的 user 消息只有题干。
        """
        req = EvalAnswerRequest.model_validate({
            "question": CONSULT_SHAPED,
            "gold": "权责发生制",
            "标准答案": "权责发生制",
            "key_points": "权责发生制；不是收付实现制",
        })
        assert not hasattr(req, "gold")
        assert not hasattr(req, "key_points")

        eval_mod.answer_one(req, ADMIN)
        msgs = _only(chain, "solve")["args"][0]
        assert msgs[-1]["content"] == CONSULT_SHAPED
        assert "权责发生制" not in msgs[0]["content"]
        assert "收付实现制" not in json.dumps(msgs, ensure_ascii=False)


# ========== DB 组：三条隔离保证落到库上 ==========


class _FakeHttpResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


KB_QUESTION = {
    "question_id": "ACC-2025-Q-01.1", "local_no": "1.1", "subject": "会计",
    "year": 2025, "chapter_id": "ACC-01", "chapter": "第一章 总论",
    "question_type": "single_choice", "knowledge_point_ids": ["ACC-01-01-03"],
    "stem": "企业会计确认、计量和报告采用的会计基础是（ ）。",
    "options": {"A": "权责发生制", "B": "收付实现制"},
    "answer": "A", "explanation": "企业会计以权责发生制为基础。",
    "materials": None, "sub_questions": None, "score": 1.0,
}

KB_TEXTBOOK = {
    "chunk_id": "ACC-2025-T-01-01-003", "subject": "会计", "year": 2025,
    "chapter_id": "ACC-01", "section_id": "ACC-01-01", "chapter": "第1章 总论",
    "section": "第1节 会计概述", "title": "会计基础", "content_type": "theory",
    "knowledge_point_ids": ["ACC-01-01-03"],
    "content": "企业会计的确认、计量和报告应当以权责发生制为基础。", "score": 1.0,
}


class _Usage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Delta:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None


class _StreamChoice:
    def __init__(self, content):
        self.delta = _Delta(content)
        self.finish_reason = "stop"


class _StreamChunk:
    def __init__(self, content, usage=None):
        self.choices = [_StreamChoice(content)] if content else []
        self.usage = usage


class _Msg:
    def __init__(self, content):
        self.content = content


class _NsChoice:
    def __init__(self, content):
        self.message = _Msg(content)


class _NsResp:
    def __init__(self, content, usage):
        self.choices = [_NsChoice(content)]
        self.usage = usage


class _Completions:
    """同一替身兼顾两种调用形态：verify 非流式、作答流式"""

    def create(self, **kwargs):
        if kwargs.get("stream"):
            return iter([_StreamChunk("权责发生制。"),
                         _StreamChunk("", _Usage(222, 33))])
        return _NsResp(
            json.dumps({"same": False, "index": None, "relevant_indexes": [1],
                        "reason": "同知识点，选项不同"}),
            _Usage(44, 6),
        )


@pytest.fixture
def live_chain(monkeypatch):
    """只桩 httpx.post 与 solver.create_client，其余全走真实代码

    kb_client._log_search 因此真的会执行到「落库前一行」，log_enabled 的抑制才是
    被真验证过；llm_store.record_usage 也真的写 usage_logs。
    """
    posts: list[dict] = []

    def _post(url, json=None, **kwargs):
        posts.append({"url": url, "payload": json})
        coll = (json or {}).get("collection")
        results = [KB_QUESTION] if coll == "questions" else [KB_TEXTBOOK]
        return _FakeHttpResponse(200, {"code": 0, "collection": coll,
                                       "results": results})

    monkeypatch.setattr("app.kb.client.httpx.post", _post)
    monkeypatch.setattr(
        "app.chat.solver.create_client",
        lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=_Completions())),
    )
    return posts


def _count(sql):
    from app.database import get_db_ctx
    with get_db_ctx() as db:
        return int(db.execute(sql).fetchone()["c"])


class TestIsolationOnRealDb:
    def test_student_forbidden(self, client, student_headers):
        r = client.post("/api/admin/eval/answer",
                        json={"question": CONSULT_SHAPED}, headers=student_headers)
        assert r.status_code == 403

    def test_anonymous_rejected(self, client):
        r = client.post("/api/admin/eval/answer", json={"question": CONSULT_SHAPED})
        assert r.status_code in (401, 403)

    def test_blank_question_400_over_http(self, client, admin_headers):
        r = client.post("/api/admin/eval/answer", json={"question": "  "},
                        headers=admin_headers)
        assert r.status_code == 400

    def test_bad_intent_400_over_http(self, client, admin_headers):
        r = client.post("/api/admin/eval/answer",
                        json={"question": CONSULT_SHAPED, "intent": "practice"},
                        headers=admin_headers)
        assert r.status_code == 400

    def test_no_side_effects_on_dialog_or_kb_report(self, client, admin_headers,
                                                    live_chain):
        """**本文件最重要的一条**：评测跑 400 题不得动对话数据与检索报表"""
        before = {
            "kb": _count("SELECT COUNT(*) c FROM kb_search_logs"),
            "conv": _count("SELECT COUNT(*) c FROM conversations"),
            "msg": _count("SELECT COUNT(*) c FROM messages"),
            "eval": _count("SELECT COUNT(*) c FROM usage_logs WHERE task_type='eval'"),
        }

        r = client.post("/api/admin/eval/answer",
                        json={"question": CONSULT_SHAPED}, headers=admin_headers)

        assert r.status_code == 200
        body = r.json()
        # 三次检索真的发生了（questions + textbook + standards），才谈得上「抑制」
        assert [p["payload"]["collection"] for p in live_chain] == ["questions",
                                                                   "textbook",
                                                                   "standards"]
        assert body["tier"] == "similar"
        assert "权责发生制。" in body["answer"]
        assert body["model"] and body["prompt_tokens"] == 222

        assert _count("SELECT COUNT(*) c FROM kb_search_logs") == before["kb"]
        assert _count("SELECT COUNT(*) c FROM conversations") == before["conv"]
        assert _count("SELECT COUNT(*) c FROM messages") == before["msg"]
        # 用量照记，且 user_id 为 NULL、可按 task_type 一次查出
        assert _count("SELECT COUNT(*) c FROM usage_logs WHERE task_type='eval'") \
            == before["eval"] + 1
        assert _count("SELECT COUNT(*) c FROM usage_logs WHERE task_type='eval' "
                      "AND user_id IS NULL") == before["eval"] + 1


# ========== 消融实验三组 mode（2026-09-16，专家对照设计） ==========


class TestModes:
    def test_invalid_mode_rejected(self, chain):
        with pytest.raises(HTTPException) as ei:
            _call(mode="banana")
        assert ei.value.status_code == 400
        assert "full" in ei.value.detail and "bare" in ei.value.detail

    def test_prompt_only_forces_solve_and_disables_kb(self, chain):
        """B 组：consult 形态的题面也强制 solve；auto 被忽略；disable_kb 必须透传"""
        out = _call(intent="auto", mode="prompt_only")
        call = _only(chain, "solve")
        assert call["kwargs"]["disable_kb"] is True
        assert out.intent == "solve"
        assert out.mode == "prompt_only"

    def test_full_keeps_retrieval(self, chain):
        _call(mode="full")
        call = _only(chain, "solve")
        assert call["kwargs"]["disable_kb"] is False

    def test_bare_mode_skips_all_chains(self, chain, monkeypatch):
        """A 组：单条 user 消息直答，无 system prompt、无检索、无后处理"""
        resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="裸答内容。"))],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7),
        )
        created: list[str] = []

        def _fake_client(model):
            created.append(model)
            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
                create=lambda **kw: resp)))

        monkeypatch.setattr(eval_mod, "create_client", _fake_client)
        out = _call(mode="bare")

        assert out.mode == "bare" and out.intent == "bare"
        assert out.tier is None and out.answer == "裸答内容。"
        assert out.model == "eval-model"
        assert out.prompt_tokens == 5 and out.completion_tokens == 7
        assert created == ["eval-model"]
        assert not any(chain.calls.values()), "bare 模式不得走任何作答链路"
        assert chain.usage == [{"model": "eval-model", "user_id": None,
                                "conversation_id": None, "in": 5, "out": 7,
                                "task_type": "eval"}]

    def test_bare_error_returned_not_raised(self, chain, monkeypatch):
        def _boom(model):
            raise RuntimeError("网络挂了")
        monkeypatch.setattr(eval_mod, "create_client", _boom)
        out = _call(mode="bare")
        assert out.error and "网络挂了" in out.error
        assert out.answer == "" and out.prompt_tokens == 0
        assert chain.usage == [], "没消耗 token 就不得记账"


class TestPinnedModel:
    def test_unknown_model_rejected(self, chain, monkeypatch):
        """幻影模型名会让整批评测 cost 恒记 0（P0-C 同款），必须 400 挡在门外"""
        monkeypatch.setattr(eval_mod.llm_store, "get_model_by_name", lambda n: None)
        with pytest.raises(HTTPException) as ei:
            _call(model_name="ghost-model")
        assert ei.value.status_code == 400
        assert "ghost-model" in ei.value.detail

    def test_pinned_model_flows_to_chain_and_verify(self, chain, monkeypatch):
        monkeypatch.setattr(eval_mod.llm_store, "get_model_by_name",
                            lambda n: {"model_name": n})
        out = _call(model_name="glm-5.2")
        call = _only(chain, "solve")
        assert call["args"][1] == "glm-5.2"
        assert call["kwargs"]["verify_model"] == "glm-5.2"
        assert out.model == "glm-5.2"

    def test_no_pinned_model_keeps_default_behavior(self, chain, monkeypatch):
        """不传 model_name 时不得查 model_configs（无 DB 单测也要能跑）"""
        called = []
        monkeypatch.setattr(eval_mod.llm_store, "get_model_by_name",
                            lambda n: called.append(n))
        out = _call()
        assert called == []
        assert out.model == "eval-model"
