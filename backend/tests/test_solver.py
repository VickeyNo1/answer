"""solve / practice 三档流水线测试（v4.1，生成器 + 打桩，不依赖数据库）

打桩点：
- `app.chat.solver.kb_client.search`  知识库检索（solver 与 qwen_service 共用同一模块对象）
- `app.chat.solver.create_client`     作答用的流式客户端
- `app.chat.solver.verify_same_question`  定档用的 LLM 校验
- `app.chat.solver.settings_store.get_bool`  practice 答案剪裁开关
"""
from types import SimpleNamespace

import pytest

from app.chat import solver
from app.chat.qwen_service import (
    DEGRADED_SUFFIX,
    EMPTY_SUFFIX,
    SUGGESTIONS_INSTRUCTION,
    build_messages,
)
from app.kb.prompt import MARKER_NOTICE
from app.chat.solver import (
    EXACT_SUFFIX,
    NONE_SUFFIX,
    PRACTICE_SUFFIX,
    SIMILAR_SUFFIX,
    run_practice,
    run_solve,
)

# ========== 打桩替身 ==========


class _Delta:
    def __init__(self, content): self.content = content; self.tool_calls = None


class _Choice:
    def __init__(self, content): self.delta = _Delta(content); self.finish_reason = "stop"


class _Chunk:
    def __init__(self, content): self.choices = [_Choice(content)]; self.usage = None


class _Completions:
    def __init__(self, chunks, calls): self._chunks = chunks; self._calls = calls

    def create(self, **kwargs):
        self._calls.append(kwargs)
        return iter([_Chunk(c) for c in self._chunks])


def _fake_client(chunks, calls):
    return SimpleNamespace(chat=SimpleNamespace(completions=_Completions(chunks, calls)))


def make_question(qid="Q-001", stem="甲公司购入存货一批，价款100万元", **extra):
    q = {
        "question_id": qid,
        "question_type": "单选",
        "chapter_id": "ACC-01",
        "chapter": "第一章 总论",
        "knowledge_point_ids": ["ACC-01-03-01"],
        "stem": stem,
        "options": {"A": "甲", "B": "乙"},
        "answer": "B",
        "explanation": "存货属于流动资产。",
        "materials": None,
        "sub_questions": None,
        "score": 0.87,
    }
    q.update(extra)
    return q


def make_textbook(title="融资租赁的判断标准", ctype="theory", content="教材正文内容"):
    return {
        "knowledge_point_ids": ["ACC-21-01-01"],
        "chapter": "第21章 租赁",
        "section": "第1节",
        "title": title,
        "content": content,
        "content_type": ctype,
        "score": 0.8,
    }


@pytest.fixture
def kb(monkeypatch):
    """打桩知识库检索：kb(questions=..., textbook=...)，返回调用记录列表

    questions / textbook 分别对应两个 collection 的返回值；传 None 模拟服务不可用。
    """
    calls: list[dict] = []
    state = {"questions": None, "textbook": None}

    def _search(query, subject, collection="textbook", top_k=5, **kwargs):
        calls.append({"query": query, "subject": subject,
                      "collection": collection, "top_k": top_k})
        return state.get(collection)

    monkeypatch.setattr(solver.kb_client, "search", _search)

    def _apply(questions=None, textbook=None):
        if questions is not None:
            state["questions"] = {"collection": "questions", "results": questions}
        if textbook is not None:
            state["textbook"] = {"collection": "textbook", "results": textbook}
        return calls

    return _apply


@pytest.fixture
def llm(monkeypatch):
    """打桩作答客户端：llm(["片段1", "片段2"]) 返回收到的 create() 参数列表

    装配时即打默认桩，避免用例漏调时真连百炼。
    """
    calls: list[dict] = []

    def _install(chunks):
        monkeypatch.setattr(solver, "create_client",
                            lambda: _fake_client(list(chunks), calls))

    _install(("这是完整解答。",))

    def _apply(chunks=("这是完整解答。",)):
        _install(chunks)
        return calls

    return _apply


@pytest.fixture
def verify(monkeypatch):
    """打桩 LLM 二次校验：verify({"same": ..., "index": ..., "reason": ...})

    装配时即打默认桩（same=False），避免用例漏调时真连百炼。
    """
    seen: list[dict] = []

    def _install(result):
        def _stub(question_text, candidates, *a, **kw):
            seen.append({"question_text": question_text, "candidates": candidates})
            return result
        monkeypatch.setattr(solver, "verify_same_question", _stub)

    _install({"same": False, "index": None, "reason": "默认桩：非同一道题"})

    def _apply(result):
        _install(result)
        return seen

    return _apply


def _messages(text="请解答这道题"):
    return build_messages(text, [], None, solver.SOLVE_SYSTEM_PROMPT)


def _practice_messages(text="给我几道租赁的练习题"):
    return build_messages(text, [], None, solver.PRACTICE_SYSTEM_PROMPT)


def _drain(gen):
    events = list(gen)
    text = "".join(e["content"] for e in events if "content" in e)
    return events, text


def _one(events, key):
    got = [e for e in events if key in e]
    assert len(got) == 1, f"事件 {key} 应恰好发一次，实际 {len(got)} 次"
    return got[0]


def _system_prompt(calls):
    return calls[-1]["messages"][0]["content"]


# ========== exact 档 ==========


class TestExactTier:
    def test_only_searches_questions_and_includes_answer(self, kb, llm, verify):
        calls = kb(questions=[make_question(), make_question("Q-002")])
        llm_calls = llm()
        verify({"same": True, "index": 1, "reason": "题干与数据完全一致"})

        events, text = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="甲公司购入存货"))

        # 命中原题走快路径：**跳过教材检索**，只查一次 questions
        assert [c["collection"] for c in calls] == ["questions"]
        assert calls[0]["top_k"] == 3
        prompt = _system_prompt(llm_calls)
        assert "答案：B" in prompt and "存货属于流动资产。" in prompt
        assert solver.EXACT_HEADING in prompt
        assert text.endswith(EXACT_SUFFIX)

    def test_match_event_reports_exact_with_question_id(self, kb, llm, verify):
        kb(questions=[make_question("Q-001"), make_question("Q-002")])
        llm()
        verify({"same": True, "index": 2, "reason": "第2条才是本题"})

        events, _ = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))

        match = _one(events, "match")["match"]
        assert match["tier"] == "exact"
        assert match["question_id"] == "Q-002"
        assert match["verify_reason"] == "第2条才是本题"
        assert match["kb_scores"] == [0.87, 0.87]

    def test_verify_gets_candidates_without_answers(self, kb, llm, verify):
        seen = verify({"same": True, "index": 1, "reason": "x"})
        kb(questions=[make_question()])
        llm()
        _drain(run_solve(_messages(), "m", "cpa_acc", query_text="甲公司购入存货"))
        assert seen[0]["candidates"][0]["question_id"] == "Q-001"
        assert seen[0]["question_text"] == "甲公司购入存货"

    def test_exact_still_emits_kp_ids_and_refs(self, kb, llm, verify):
        kb(questions=[make_question()])
        llm()
        verify({"same": True, "index": 1, "reason": "x"})
        events, _ = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        assert _one(events, "kp_ids")["kp_ids"] == ["ACC-01-03-01"]
        refs = _one(events, "kb_refs")["kb_refs"]
        assert refs[0]["title"] == "题库 Q-001"
        assert refs[0]["chapter"] == "第一章 总论"

    def test_exact_not_degraded_even_when_textbook_unavailable(self, kb, llm, verify):
        """exact 档本就不查教材，t_data 恒为 None，不得因此误报服务不可用"""
        kb(questions=[make_question()])
        llm()
        verify({"same": True, "index": 1, "reason": "x"})
        _, text = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        assert DEGRADED_SUFFIX not in text


# ========== similar 档 ==========


class TestSimilarTier:
    def test_searches_both_collections_and_forbids_copying(self, kb, llm, verify):
        calls = kb(questions=[make_question()], textbook=[make_textbook()])
        llm_calls = llm()
        verify({"same": False, "index": None, "reason": "金额不同"})

        events, text = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="乙公司购入存货"))

        assert [c["collection"] for c in calls] == ["questions", "textbook"]
        assert calls[1]["top_k"] == 5
        prompt = _system_prompt(llm_calls)
        assert "严禁照搬其数据、金额与答案" in prompt
        assert solver.SIMILAR_HEADING in prompt
        assert "答案：B" in prompt          # 相似题带答案作范例
        assert text.endswith(SIMILAR_SUFFIX)
        assert _one(events, "match")["match"]["tier"] == "similar"

    def test_verify_failure_degrades_to_similar_not_exact(self, kb, llm, verify):
        """**保守性回归**：校验失败时绝不允许宣称找到原题

        verify_same_question 内部吞掉异常并返回 same=False（见 TestVerifySameQuestion），
        run_solve 收到该结果后必须落到 similar 档，仍给出完整解答。
        """
        kb(questions=[make_question()], textbook=[make_textbook()])
        llm()
        verify({"same": False, "index": None, "reason": "校验失败：模型超时"})
        events, text = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        match = _one(events, "match")["match"]
        assert match["tier"] == "similar"
        assert match["question_id"] is None
        assert match["verify_reason"] == "校验失败：模型超时"
        assert EXACT_SUFFIX not in text
        assert text.endswith(SIMILAR_SUFFIX)

    def test_out_of_range_index_degrades_to_similar(self, kb, llm, verify):
        kb(questions=[make_question()], textbook=[make_textbook()])
        llm()
        verify({"same": True, "index": 9, "reason": "越界"})
        events, _ = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        match = _one(events, "match")["match"]
        assert match["tier"] == "similar" and match["question_id"] is None

    def test_textbook_query_uses_similar_question_topic(self, kb, llm, verify):
        """教材检索改用相似题的 chapter+题干（干净、同话题），不用 OCR 噪声原文"""
        calls = kb(questions=[make_question(stem="融资租赁租入固定资产的初始计量")],
                   textbook=[make_textbook()])
        llm()
        verify({"same": False, "index": None, "reason": "x"})
        noisy = "请解答\n\n【图片识别内容】\n" + "识别噪声" * 50
        _drain(run_solve(_messages(noisy), "m", "cpa_acc", query_text=noisy))
        assert calls[1]["query"] == "第一章 总论 融资租赁租入固定资产的初始计量"

    def test_topic_query_falls_back_when_candidates_have_no_stem(self, kb, llm, verify):
        calls = kb(questions=[make_question(stem=None, materials=None)],
                   textbook=[make_textbook()])
        llm()
        verify({"same": False, "index": None, "reason": "x"})
        _drain(run_solve(_messages(), "m", "cpa_acc", query_text="原始提问"))
        assert calls[1]["query"] == "原始提问"


# ========== none 档 ==========


class TestNoneTier:
    def test_empty_questions_skips_verify_and_widens_textbook(self, kb, llm, monkeypatch):
        calls = kb(questions=[], textbook=[make_textbook(ctype="example")])
        llm_calls = llm()

        def _boom(*a, **kw):
            raise AssertionError("题库无结果时不得触发校验调用（白花钱）")
        monkeypatch.setattr(solver, "verify_same_question", _boom)

        events, text = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))

        assert [c["collection"] for c in calls] == ["questions", "textbook"]
        assert calls[1]["top_k"] == 8
        assert _one(events, "match")["match"] == {
            "tier": "none", "question_id": None, "verify_reason": "", "kb_scores": [],
        }
        assert text.endswith(NONE_SUFFIX)
        assert solver.NONE_BLOCK in _system_prompt(llm_calls)

    def test_none_tier_prefers_examples_and_entries(self, kb, llm, verify):
        """prefer='solve'：例题/分录要排到纯理论前面，否则分录题检索回一堆理论仍不会做"""
        kb(questions=[], textbook=[
            make_textbook(title="理论A", ctype="theory"),
            make_textbook(title="例题B", ctype="example"),
            make_textbook(title="分录C", ctype="entry"),
        ])
        llm_calls = llm()
        _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        prompt = _system_prompt(llm_calls)
        assert prompt.index("例题B") < prompt.index("理论A")
        assert prompt.index("分录C") < prompt.index("理论A")

    def test_missing_content_type_kept_not_dropped(self, kb, llm, verify):
        """缺 content_type 的条目排最后但**绝不丢弃**（现有测试假数据都没这个字段）"""
        kb(questions=[], textbook=[
            {"title": "无类型", "content": "老数据"},
            make_textbook(title="例题B", ctype="example"),
        ])
        llm_calls = llm()
        _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        prompt = _system_prompt(llm_calls)
        assert "老数据" in prompt
        assert prompt.index("例题B") < prompt.index("老数据")


# ========== 相关性下限 ==========


class TestRelevanceFloor:
    """检索服务没有相关性下限，「题库返回了结果」≠「题库里有相关的题」

    乱码 query 也会返回满 top_k 条，score 又只是重排后的排序分、跨请求不可比，
    故相关性只能由校验模型在同一次调用里指认（relevant_indexes），零额外成本。
    """

    def test_irrelevant_candidates_drop_to_none_tier(self, kb, llm, verify):
        calls = kb(questions=[make_question("Q-001", stem="存货跌价准备"),
                              make_question("Q-002", stem="长期股权投资")],
                   textbook=[make_textbook()])
        llm_calls = llm()
        verify({"same": False, "index": None, "relevant_indexes": [],
                "reason": "均为其他章节"})

        events, text = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="融资租赁"))

        match = _one(events, "match")["match"]
        assert match["tier"] == "none"
        assert match["verify_reason"] == "均为其他章节"
        assert match["kb_scores"] == [0.87, 0.87]      # 检索确实返回了结果
        prompt = _system_prompt(llm_calls)
        assert "存货跌价准备" not in prompt
        assert "长期股权投资" not in prompt
        assert solver.SIMILAR_HEADING not in prompt     # 噪声没被塞进去
        assert calls[1]["top_k"] == 8                   # 走 none 档的教材定向检索
        assert text.endswith(NONE_SUFFIX)               # 仍然给出完整解答

    def test_only_relevant_subset_injected(self, kb, llm, verify):
        kb(questions=[
            make_question("Q-001", stem="存货跌价准备", knowledge_point_ids=["ACC-01-01-01"]),
            make_question("Q-002", stem="融资租赁初始计量", knowledge_point_ids=["ACC-21-02-02"]),
        ], textbook=[make_textbook()])
        llm_calls = llm()
        verify({"same": False, "index": None, "relevant_indexes": [2],
                "reason": "只有第2道同领域"})

        events, _ = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="融资租赁"))

        assert _one(events, "match")["match"]["tier"] == "similar"
        prompt = _system_prompt(llm_calls)
        assert "融资租赁初始计量" in prompt
        assert "存货跌价准备" not in prompt
        refs = _one(events, "kb_refs")["kb_refs"]
        assert [r["title"] for r in refs if r["title"].startswith("题库")] == ["题库 Q-002"]
        kp = _one(events, "kp_ids")["kp_ids"]
        assert "ACC-21-02-02" in kp and "ACC-01-01-01" not in kp

    def test_textbook_query_uses_only_relevant_subset(self, kb, llm, verify):
        """教材检索的 topic query 取自相关子集，排在首位的无关候选不得干扰"""
        calls = kb(questions=[
            make_question("Q-001", stem="存货跌价准备"),
            make_question("Q-002", stem="融资租赁初始计量"),
        ], textbook=[make_textbook()])
        llm()
        verify({"same": False, "index": None, "relevant_indexes": [2], "reason": "x"})
        _drain(run_solve(_messages(), "m", "cpa_acc", query_text="原始提问"))
        assert calls[1]["query"] == "第一章 总论 融资租赁初始计量"

    def test_no_signal_injects_all_candidates(self, kb, llm, verify):
        """没拿到相关性信号（字段缺失/校验失败）→ 沿用旧的保守行为，全量注入"""
        kb(questions=[make_question("Q-001"), make_question("Q-002")],
           textbook=[make_textbook()])
        llm_calls = llm()
        verify({"same": False, "index": None, "reason": "校验失败：模型超时"})

        events, text = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))

        assert _one(events, "match")["match"]["tier"] == "similar"
        prompt = _system_prompt(llm_calls)
        assert "Q-001" in prompt and "Q-002" in prompt
        assert text.endswith(SIMILAR_SUFFIX)


# ========== 服务不可用 ==========


class TestKbUnavailable:
    def test_both_searches_down_uses_degraded_suffix_without_stacking(self, kb, llm, verify):
        kb()                                   # 两个 collection 都保持 None
        llm_calls = llm()
        _, text = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        assert text.endswith(DEGRADED_SUFFIX)
        assert NONE_SUFFIX not in text and SIMILAR_SUFFIX not in text
        assert solver.KB_DOWN_TEXT in _system_prompt(llm_calls)

    def test_only_textbook_down_still_uses_tier_suffix(self, kb, llm, verify):
        """题库有结果、教材挂了 → 仍属 similar 档，不报服务不可用"""
        kb(questions=[make_question()])
        llm()
        verify({"same": False, "index": None, "reason": "x"})
        _, text = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        assert text.endswith(SIMILAR_SUFFIX)
        assert DEGRADED_SUFFIX not in text


# ========== 事件与用量 ==========


class TestEvents:
    def test_event_vocabulary_matches_stream_chat(self, kb, llm, verify):
        kb(questions=[make_question()], textbook=[make_textbook()])
        llm(["解答上半段", "解答下半段"])
        verify({"same": False, "index": None, "reason": "x"})
        events, text = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        keys = [next(iter(e)) for e in events]
        assert keys[0] == "kb_search"
        assert "解答上半段解答下半段" in text
        assert keys[-1] == "usage"
        # 除 match 外不得出现 stream_chat 词汇表之外的新键（router 才认识这些）
        assert set(keys) <= {"kb_search", "kb_refs", "kp_ids", "match",
                             "content", "suggestions", "usage", "error"}

    def test_usage_accumulated_and_suggestions_forwarded(self, kb, llm, verify):
        kb(questions=[], textbook=[])
        llm(["正文", "\n===SUGGESTIONS===\n[\"追问一\",\"追问二\"]"])
        events, text = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        assert "===SUGGESTIONS===" not in text
        assert _one(events, "suggestions")["suggestions"] == ["追问一", "追问二"]
        assert _one(events, "usage")["usage"] == {
            "prompt_tokens": 0, "completion_tokens": 0,
        }

    def test_query_text_truncated_to_1000(self, kb, llm, verify):
        calls = kb(questions=[], textbook=[])
        llm()
        _drain(run_solve(_messages(), "m", "cpa_acc", query_text="长" * 3000))
        assert len(calls[0]["query"]) == solver.QUERY_MAX_LEN

    def test_search_exception_yields_error_event(self, monkeypatch, llm):
        def _boom(**kwargs):
            raise RuntimeError("连接被重置")
        monkeypatch.setattr(solver.kb_client, "search", _boom)
        llm()
        events, _ = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        assert "连接被重置" in _one(events, "error")["error"]

    def test_history_and_question_preserved(self, kb, llm, verify):
        """档位说明与资料只追加到 system prompt，不得吞掉多轮历史与当前提问"""
        kb(questions=[], textbook=[])
        llm_calls = llm()
        msgs = build_messages("第二问怎么做", [{"role": "user", "content": "第一问"},
                                              {"role": "assistant", "content": "第一答"}],
                              "【记忆】薄弱点：租赁", solver.SOLVE_SYSTEM_PROMPT)
        _drain(run_solve(msgs, "m", "cpa_acc", query_text="第二问怎么做"))
        sent = llm_calls[-1]["messages"]
        assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
        assert sent[1]["content"] == "第一问" and sent[-1]["content"] == "第二问怎么做"
        assert sent[0]["content"].startswith(solver.SOLVE_SYSTEM_PROMPT)
        assert "【记忆】薄弱点：租赁" in sent[0]["content"]

    def test_enable_thinking_disabled(self, kb, llm, verify):
        kb(questions=[], textbook=[])
        llm_calls = llm()
        _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        assert llm_calls[-1]["extra_body"] == {"enable_thinking": False}


# ========== practice 档 ==========


class TestPractice:
    def test_questions_cut_by_default(self, kb, llm, monkeypatch):
        calls = kb(questions=[make_question()])
        llm_calls = llm()
        monkeypatch.setattr(solver.settings_store, "get_bool", lambda k: False)

        events, text = _drain(run_practice(_practice_messages("给我几道租赁的练习题"), "m", "cpa_acc"))

        assert calls[0] == {"query": "给我几道租赁的练习题", "subject": "cpa_acc",
                            "collection": "questions", "top_k": 5}
        prompt = _system_prompt(llm_calls)
        assert "绝对不要给出答案" in prompt
        assert "答案：B" not in prompt and "存货属于流动资产" not in prompt
        assert "已省略" in prompt              # 让模型知道答案存在但拿不到
        assert text.endswith(PRACTICE_SUFFIX)
        assert _one(events, "kb_refs")["kb_refs"][0]["title"] == "题库 Q-001"

    def test_reveal_switch_on_includes_answers(self, kb, llm, monkeypatch):
        kb(questions=[make_question()])
        llm_calls = llm()
        monkeypatch.setattr(solver.settings_store, "get_bool", lambda k: True)
        _, text = _drain(run_practice(_practice_messages("给我几道题"), "m", "cpa_acc"))
        prompt = _system_prompt(llm_calls)
        assert "答案：B" in prompt and "存货属于流动资产。" in prompt
        assert solver.PRACTICE_REVEAL_BLOCK in prompt
        assert text.endswith(PRACTICE_SUFFIX)

    def test_empty_questions_falls_back_to_textbook_composition(self, kb, llm, monkeypatch):
        calls = kb(questions=[], textbook=[make_textbook()])
        llm_calls = llm()
        monkeypatch.setattr(solver.settings_store, "get_bool", lambda k: False)
        _, text = _drain(run_practice(_practice_messages("来几道题"), "m", "cpa_acc"))
        assert [c["collection"] for c in calls] == ["questions", "textbook"]
        prompt = _system_prompt(llm_calls)
        assert solver.PRACTICE_COMPOSE_BLOCK in prompt
        assert "改编题" in prompt and "不得给出答案" in prompt
        assert text.endswith(PRACTICE_SUFFIX)
        assert EMPTY_SUFFIX not in text

    def test_both_collections_empty_uses_empty_suffix(self, kb, llm, monkeypatch):
        kb(questions=[], textbook=[])
        llm_calls = llm()
        monkeypatch.setattr(solver.settings_store, "get_bool", lambda k: False)
        _, text = _drain(run_practice(_practice_messages("来几道题"), "m", "cpa_acc"))
        assert text.endswith(EMPTY_SUFFIX)
        assert PRACTICE_SUFFIX not in text
        assert solver.NO_CONTEXT_TEXT in _system_prompt(llm_calls)

    def test_both_collections_down_uses_degraded_suffix(self, kb, llm, monkeypatch):
        kb()
        llm_calls = llm()
        monkeypatch.setattr(solver.settings_store, "get_bool", lambda k: False)
        _, text = _drain(run_practice(_practice_messages("来几道题"), "m", "cpa_acc"))
        assert text.endswith(DEGRADED_SUFFIX)
        assert solver.KB_DOWN_TEXT in _system_prompt(llm_calls)

    def test_no_kp_ids_event_when_results_lack_them(self, kb, llm, monkeypatch):
        kb(questions=[make_question(knowledge_point_ids=None)])
        llm()
        monkeypatch.setattr(solver.settings_store, "get_bool", lambda k: False)
        events, _ = _drain(run_practice(_practice_messages("来几道题"), "m", "cpa_acc"))
        assert not [e for e in events if "kp_ids" in e]


# ========== 标头行防泄漏（P1-B） ==========


class TestMarkerNotice:
    """检索资料的「【题目N｜…】」「【资料N｜…】」标头行曾被模型原样抄进答案

    说明必须紧跟资料之后（「上方资料」的指代才成立），且在追问建议指令之前——
    两条都是输出格式约束，谁压谁都会出问题，故各守其位。
    """

    def test_exact_prompt_has_notice_after_questions(self, kb, llm, verify):
        kb(questions=[make_question()])
        llm_calls = llm()
        verify({"same": True, "index": 1, "reason": "x"})
        _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        prompt = _system_prompt(llm_calls)
        assert MARKER_NOTICE in prompt
        assert prompt.index("【题目1｜") < prompt.index(MARKER_NOTICE)

    def test_similar_two_blocks_share_one_notice(self, kb, llm, verify):
        """题库 + 教材两段资料拼在一起时只说一遍，别把 prompt 撑肥"""
        kb(questions=[make_question()], textbook=[make_textbook()])
        llm_calls = llm()
        verify({"same": False, "index": None, "reason": "x"})
        _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        prompt = _system_prompt(llm_calls)
        assert prompt.count(MARKER_NOTICE) == 1
        assert prompt.index("【资料1｜") < prompt.index(MARKER_NOTICE)

    def test_notice_precedes_suggestions_instruction(self, kb, llm):
        kb(questions=[], textbook=[make_textbook()])
        llm_calls = llm()
        _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        prompt = _system_prompt(llm_calls)
        assert prompt.index(MARKER_NOTICE) < prompt.index(SUGGESTIONS_INSTRUCTION)

    def test_no_notice_without_any_context(self, kb, llm):
        """两次检索都空 → 只有 NO_CONTEXT_TEXT，没有标头行可交代"""
        kb(questions=[], textbook=[])
        llm_calls = llm()
        _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        prompt = _system_prompt(llm_calls)
        assert solver.NO_CONTEXT_TEXT in prompt
        assert MARKER_NOTICE not in prompt

    def test_no_notice_when_kb_down(self, kb, llm):
        kb()
        llm_calls = llm()
        _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        prompt = _system_prompt(llm_calls)
        assert solver.KB_DOWN_TEXT in prompt
        assert MARKER_NOTICE not in prompt

    def test_practice_prompt_has_notice(self, kb, llm, monkeypatch):
        kb(questions=[make_question()])
        llm_calls = llm()
        monkeypatch.setattr(solver.settings_store, "get_bool", lambda k: False)
        _drain(run_practice(_practice_messages("来几道题"), "m", "cpa_acc"))
        assert MARKER_NOTICE in _system_prompt(llm_calls)

    def test_practice_compose_prompt_has_notice(self, kb, llm, monkeypatch):
        """据教材命题时资料是「【资料N｜…】」，同样要交代"""
        kb(questions=[], textbook=[make_textbook()])
        llm_calls = llm()
        monkeypatch.setattr(solver.settings_store, "get_bool", lambda k: False)
        _drain(run_practice(_practice_messages("来几道题"), "m", "cpa_acc"))
        assert MARKER_NOTICE in _system_prompt(llm_calls)

    def test_notice_never_leaks_into_answer_text(self, kb, llm, verify):
        """说明只进 system prompt，不得混进下发给学生的正文"""
        kb(questions=[make_question()], textbook=[make_textbook()])
        llm(["这是解答。"])
        verify({"same": False, "index": None, "reason": "x"})
        _, text = _drain(run_solve(_messages(), "m", "cpa_acc", query_text="q"))
        assert MARKER_NOTICE not in text
        assert "内部标头不外泄" not in text


class _NSMsg:
    def __init__(self, content): self.content = content


class _NSChoice:
    def __init__(self, content): self.message = _NSMsg(content)


class _NSUsage:
    def __init__(self, prompt_tokens=11, completion_tokens=7):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _NSResp:
    def __init__(self, content, usage=None):
        self.choices = [_NSChoice(content)]
        self.usage = usage if usage is not None else _NSUsage()


class _NSCompletions:
    def __init__(self, resp, calls): self._resp = resp; self._calls = calls

    def create(self, **kwargs):
        self._calls.append(kwargs)
        if isinstance(self._resp, BaseException):
            raise self._resp
        return self._resp


@pytest.fixture
def verify_llm(monkeypatch):
    """打桩 verify_same_question 依赖的非流式客户端与用量记账"""
    calls: list[dict] = []
    usage_rows: list[dict] = []
    state = {"resp": _NSResp('{"same": true, "index": 1, "reason": "同一道题"}')}

    monkeypatch.setattr(
        solver, "create_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(
            completions=_NSCompletions(state["resp"], calls))),
    )
    monkeypatch.setattr(solver.llm_store, "get_model_for", lambda t: f"{t}-model")
    monkeypatch.setattr(
        solver.llm_store, "record_usage",
        lambda model, uid, cid, tin, tout, task_type="chat": usage_rows.append(
            {"model": model, "user_id": uid, "conversation_id": cid,
             "in": tin, "out": tout, "task_type": task_type}),
    )

    def _apply(resp):
        state["resp"] = resp

    _apply.calls = calls
    _apply.usage = usage_rows
    return _apply


class TestVerifySameQuestion:
    def test_returns_parsed_result_and_uses_verify_model(self, verify_llm):
        verify_llm(_NSResp('{"same": true, "index": 2, "reason": "数据一致"}'))
        out = solver.verify_same_question("题干", [make_question(), make_question("Q-2")])
        assert out == {"same": True, "index": 2, "relevant_indexes": None,
                       "reason": "数据一致"}
        kw = verify_llm.calls[0]
        assert kw["model"] == "verify-model"
        assert kw["extra_body"] == {"enable_thinking": False}
        assert "stream" not in kw                    # 校验必须非流式
        assert "Q-2" in kw["messages"][-1]["content"]

    def test_relevant_indexes_clamped_to_candidate_count(self, verify_llm):
        """越界序号在本层裁掉——parse_verify_result 不知道候选有几条"""
        verify_llm(_NSResp(
            '{"same": false, "index": null, "relevant_indexes": [1, 5, -2], "reason": "x"}'))
        out = solver.verify_same_question("题干", [make_question(), make_question("Q-2")])
        assert out["relevant_indexes"] == [1]

    def test_all_indexes_out_of_range_degrades_to_no_signal(self, verify_llm):
        """序号全部越界 = 模型幻觉，属「信号不可用」而非「明确无相关」"""
        verify_llm(_NSResp(
            '{"same": false, "index": null, "relevant_indexes": [7, 9], "reason": "x"}'))
        out = solver.verify_same_question("题干", [make_question(), make_question("Q-2")])
        assert out["relevant_indexes"] is None

    def test_exception_path_is_no_signal_not_empty(self, verify_llm):
        """校验挂掉必须是「无信号」(None)，不能是「明确无相关」([])

        否则每次校验超时都会让 run_solve 归 none 档、丢掉本来可用的相似题参考。
        """
        verify_llm(RuntimeError("连接超时"))
        out = solver.verify_same_question("题干", [make_question()])
        assert out["relevant_indexes"] is None

    def test_records_usage_as_verify_task(self, verify_llm):
        verify_llm(_NSResp('{"same": false, "index": null, "reason": "x"}',
                           usage=_NSUsage(120, 30)))
        solver.verify_same_question("题干", [make_question()], user_id=7, conversation_id=9)
        assert verify_llm.usage == [{"model": "verify-model", "user_id": 7,
                                     "conversation_id": 9, "in": 120, "out": 30,
                                     "task_type": "verify"}]

    @pytest.mark.parametrize("exc", [
        RuntimeError("连接超时"),
        ValueError("响应格式异常"),
        AttributeError("'NoneType' object has no attribute 'choices'"),
    ])
    def test_any_exception_swallowed_as_not_same(self, verify_llm, exc):
        """**校验内部异常绝不外泄**：外泄会让 run_solve 直接吐 error，学生拿不到解答，
        违背「三档全部产出解答」的核心要求"""
        verify_llm(exc)
        out = solver.verify_same_question("题干", [make_question()])
        assert out["same"] is False and out["index"] is None
        assert "校验失败" in out["reason"]

    def test_usage_failure_does_not_break_result(self, verify_llm, monkeypatch):
        def _boom(*a, **kw):
            raise RuntimeError("DB 不可达")
        monkeypatch.setattr(solver.llm_store, "record_usage", _boom)
        verify_llm(_NSResp('{"same": true, "index": 1, "reason": "x"}'))
        assert solver.verify_same_question("题干", [make_question()])["same"] is True

    def test_empty_candidates_skips_llm_call(self, verify_llm):
        """无候选直接判否，不浪费一次调用"""
        out = solver.verify_same_question("题干", [])
        assert out == {"same": False, "index": None, "relevant_indexes": [],
                       "reason": "无候选题"}
        assert verify_llm.calls == []

    def test_response_without_usage_attribute(self, verify_llm):
        """替身/旧 SDK 可能没有 usage 属性，不得因此崩"""
        resp = _NSResp('{"same": true, "index": 1, "reason": "x"}')
        del resp.usage
        verify_llm(resp)
        assert solver.verify_same_question("题干", [make_question()])["same"] is True
        assert verify_llm.usage[0]["in"] == 0 and verify_llm.usage[0]["out"] == 0

    def test_explicit_model_name_overrides(self, verify_llm):
        verify_llm(_NSResp('{"same": false, "index": null, "reason": "x"}'))
        solver.verify_same_question("题干", [make_question()], model_name="cheap-flash")
        assert verify_llm.calls[0]["model"] == "cheap-flash"


class TestSystemPromptFor:
    def test_consult_returns_none_to_keep_default(self):
        assert solver.system_prompt_for("consult") is None

    def test_solve_and_practice(self):
        assert solver.system_prompt_for("solve") == solver.SOLVE_SYSTEM_PROMPT
        assert solver.system_prompt_for("practice") == solver.PRACTICE_SYSTEM_PROMPT

    def test_solve_prompt_demands_a_real_answer(self):
        """「必须给出解答」是对既往分歧的固化：两阶段揭示方案已被否决"""
        assert "必须给出完整解答" in solver.SOLVE_SYSTEM_PROMPT
        assert "搪塞" in solver.SOLVE_SYSTEM_PROMPT
