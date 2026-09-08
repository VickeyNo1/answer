# -*- coding: utf-8 -*-
"""测试知识库客户端、结果拼接与 GET /api/subjects（契约见 doc/知识库对接文档.md）"""
import pytest

from app.kb import client as kb_client
from app.kb.prompt import (
    ANSWER_OMITTED_HINT,
    CONTENT_TYPE_LABELS,
    FALLBACK_TEXT,
    collect_kp_ids,
    format_results,
    sub_question_text,
)


class FakeHttpResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


# ========== KB client ==========

class TestKBClient:

    def test_search_success(self, monkeypatch):
        payload = {
            "code": 0, "collection": "textbook",
            "results": [{"knowledge_point_ids": ["KP-001"], "content": "存货"}],
        }
        monkeypatch.setattr(
            "app.kb.client.httpx.post",
            lambda *a, **k: FakeHttpResponse(200, payload),
        )
        data = kb_client.search("存货计价", "cpa_acc")
        assert data is not None
        assert data["code"] == 0
        assert len(data["results"]) == 1

    def test_search_empty_results(self, monkeypatch):
        payload = {"code": 0, "collection": "textbook", "results": []}
        monkeypatch.setattr(
            "app.kb.client.httpx.post",
            lambda *a, **k: FakeHttpResponse(200, payload),
        )
        data = kb_client.search("无关问题", "cpa_acc")
        assert data is not None
        assert data["results"] == []

    def test_search_timeout_degrades_to_none(self, monkeypatch):
        """超时/网络异常重试后仍失败，返回 None（调用方降级）"""
        calls = {"n": 0}

        def boom(*a, **k):
            calls["n"] += 1
            raise TimeoutError("connect timeout")

        monkeypatch.setattr("app.kb.client.httpx.post", boom)
        data = kb_client.search("存货", "cpa_acc")
        assert data is None
        assert calls["n"] == 2  # 重试 1 次

    def test_search_bad_request_no_retry(self, monkeypatch):
        """400 参数错误不重试，直接返回 None"""
        calls = {"n": 0}

        def bad(*a, **k):
            calls["n"] += 1
            return FakeHttpResponse(400, {"code": 400, "message": "bad"})

        monkeypatch.setattr("app.kb.client.httpx.post", bad)
        data = kb_client.search("存货", "cpa_acc")
        assert data is None
        assert calls["n"] == 1  # 不重试


# ========== 考试抽题 draw_exam（v4.0-M2） ==========

SAMPLE_QUESTION = {
    "score": 0.9, "knowledge_point_ids": ["ACC-01-03-01"],
    "question_id": "Q-0012", "chapter_id": "ACC-01", "chapter": "第一章 总论",
    "question_type": "单选", "stem": "下列哪项…", "options": {"A": "…", "B": "…"},
    "answer": "B", "explanation": "…", "materials": None, "sub_questions": None,
}


class TestDrawExam:

    def test_draw_success(self, monkeypatch):
        payload = {"code": 0, "questions": [SAMPLE_QUESTION]}
        captured = {}

        def fake_post(url, json=None, **k):
            captured["url"] = url
            captured["payload"] = json
            return FakeHttpResponse(200, payload)

        monkeypatch.setattr("app.kb.client.httpx.post", fake_post)
        questions = kb_client.draw_exam("cpa_acc", ["ACC-01"], {"单选": 1})
        assert len(questions) == 1
        assert questions[0]["question_id"] == "Q-0012"
        assert captured["url"].endswith("/kb/exam/draw")
        assert captured["payload"] == {
            "subject": "cpa_acc", "chapter_ids": ["ACC-01"], "counts": {"单选": 1},
        }

    def test_draw_insufficient_returns_actual(self, monkeypatch):
        """题量不足时按知识库实际返回数量，不报错"""
        payload = {"code": 0, "questions": [SAMPLE_QUESTION]}  # 请求 5 题只返 1 题
        monkeypatch.setattr(
            "app.kb.client.httpx.post", lambda *a, **k: FakeHttpResponse(200, payload)
        )
        questions = kb_client.draw_exam("cpa_acc", None, {"单选": 5})
        assert len(questions) == 1

    def test_draw_timeout_raises_no_retry(self, monkeypatch):
        """超时不降级不重试，直接抛 KbDrawError（与 search 刻意不同）"""
        calls = {"n": 0}

        def boom(*a, **k):
            calls["n"] += 1
            raise TimeoutError("connect timeout")

        monkeypatch.setattr("app.kb.client.httpx.post", boom)
        with pytest.raises(kb_client.KbDrawError):
            kb_client.draw_exam("cpa_acc", None, {"单选": 5})
        assert calls["n"] == 1

    def test_draw_code_error_raises(self, monkeypatch):
        """code≠0（5001 内部错）直接抛 KbDrawError"""
        monkeypatch.setattr(
            "app.kb.client.httpx.post",
            lambda *a, **k: FakeHttpResponse(500, {"code": 5001, "message": "内部错误"}),
        )
        with pytest.raises(kb_client.KbDrawError):
            kb_client.draw_exam("cpa_acc", None, {"单选": 5})

    def test_draw_http_error_raises(self, monkeypatch):
        """HTTP 4001 参数错也抛 KbDrawError（考试链路无降级）"""
        monkeypatch.setattr(
            "app.kb.client.httpx.post",
            lambda *a, **k: FakeHttpResponse(400, {"code": 4001, "message": "参数错误"}),
        )
        with pytest.raises(kb_client.KbDrawError):
            kb_client.draw_exam("cpa_acc", None, {})


# ========== 结果拼接 ==========

class TestFormatResults:

    def test_none_returns_fallback(self):
        assert format_results(None) == FALLBACK_TEXT

    def test_empty_results_returns_fallback(self):
        assert format_results({"collection": "textbook", "results": []}) == FALLBACK_TEXT

    def test_textbook_format(self):
        data = {
            "collection": "textbook",
            "results": [{
                "knowledge_point_ids": ["KP-001"],
                "chapter": "第一章", "section": "第一节",
                "title": "存货计价", "content": "存货应按成本计量。",
            }],
        }
        text = format_results(data)
        assert "KP-001" in text
        assert "存货应按成本计量" in text
        assert "第一章" in text

    def test_textbook_missing_kp_marked_unlabeled(self):
        data = {
            "collection": "textbook",
            "results": [{"knowledge_point_ids": [], "content": "无编号资料"}],
        }
        text = format_results(data)
        assert "未标注" in text

    def test_questions_format(self):
        data = {
            "collection": "questions",
            "results": [{
                "question_id": "Q-100", "question_type": "单选题",
                "knowledge_point_ids": ["KP-009"],
                "stem": "下列哪项属于流动资产？",
                "options": {"A": "存货", "B": "厂房"},
                "answer": "A", "explanation": "存货属于流动资产。",
            }],
        }
        text = format_results(data, include_answer=True)
        assert "Q-100" in text
        assert "存货" in text
        assert "答案：A" in text
        assert "存货属于流动资产。" in text

    def test_questions_answer_cut_by_default(self):
        """默认剪裁题库答案（契约见 doc/知识库对接文档.md：先答题后判卷场景务必剪裁）

        注意不能只断言 "答案" not in text —— 剪裁提示语本身就含「答案」二字。
        """
        data = {
            "collection": "questions",
            "results": [{
                "question_id": "Q-100", "question_type": "单选题",
                "stem": "下列哪项属于流动资产？",
                "answer": "A", "explanation": "存货属于流动资产。",
            }],
        }
        text = format_results(data)
        assert "答案：A" not in text
        assert "存货属于流动资产。" not in text
        assert "已省略" in text

    def test_questions_no_answer_no_hint(self):
        """题库本就缺答案的题（约 69 题原始资料缺失）不应谎称「已省略」"""
        data = {
            "collection": "questions",
            "results": [{"question_id": "Q-200", "stem": "何谓权责发生制？"}],
        }
        text = format_results(data)
        assert "已省略" not in text

    def test_collect_kp_ids_dedup_order(self):
        data = {"results": [
            {"knowledge_point_ids": ["KP-001", "KP-002"]},
            {"knowledge_point_ids": ["KP-002", "KP-003"]},
        ]}
        assert collect_kp_ids(data) == ["KP-001", "KP-002", "KP-003"]

    def test_collect_kp_ids_none(self):
        assert collect_kp_ids(None) == []


# ========== content_type 定向组装（v4.1） ==========

def _tb(title, ctype=None, content=None):
    r = {"title": title, "content": content or f"正文-{title}",
         "chapter": "第21章 租赁", "section": "第1节",
         "knowledge_point_ids": ["ACC-21-01-01"]}
    if ctype is not None:
        r["content_type"] = ctype
    return r


def _data(results):
    return {"collection": "textbook", "results": results}


class TestContentTypeOrdering:

    def test_label_rendered_in_chinese(self):
        text = format_results(_data([_tb("融资租赁的判断标准", "example")]))
        assert "例题" in text
        assert "【资料1｜例题｜" in text

    def test_unknown_and_missing_type_rendered_as_unclassified(self):
        text = format_results(_data([_tb("老数据", None), _tb("新类型", "video")]))
        assert text.count("未分类") == 2

    @pytest.mark.parametrize("ctype,label", sorted(CONTENT_TYPE_LABELS.items()))
    def test_every_enum_value_has_a_label(self, ctype, label):
        assert label in format_results(_data([_tb("t", ctype)]))

    def test_prefer_solve_moves_examples_before_theory(self):
        """分录题检索回一堆纯理论是没用的：例题/分录/公式/表格必须前置"""
        results = [_tb("理论A", "theory"), _tb("例题B", "example"),
                   _tb("原则C", "principle"), _tb("分录D", "entry")]
        text = format_results(_data(results), prefer="solve")
        assert text.index("例题B") < text.index("理论A")
        assert text.index("分录D") < text.index("理论A")
        assert text.index("例题B") < text.index("原则C")

    def test_prefer_solve_keeps_score_order_within_group(self):
        """同组内必须保持知识库返回的原 score 顺序（Python sorted 稳定）"""
        results = [_tb("理论1", "theory"), _tb("例题1", "example"),
                   _tb("理论2", "theory"), _tb("例题2", "example")]
        text = format_results(_data(results), prefer="solve")
        assert text.index("例题1") < text.index("例题2")
        assert text.index("理论1") < text.index("理论2")

    def test_missing_content_type_sorted_last_but_never_dropped(self):
        """**兜底**：现有测试假数据与线上老数据都没有 content_type，
        若筛选逻辑丢弃缺字段条目，这些资料会静默消失"""
        results = [_tb("无类型"), _tb("例题B", "example"), _tb("未知类型", "video")]
        text = format_results(_data(results), prefer="solve")
        assert "正文-无类型" in text and "正文-例题B" in text and "video" not in text
        assert "正文-未知类型" in text
        assert text.index("例题B") < text.index("正文-无类型")
        assert text.count("【资料") == 3          # 一条都没丢

    def test_no_prefer_keeps_original_order(self):
        """不传 prefer 时完全不排序，consult 老路径行为不变"""
        results = [_tb("理论A", "theory"), _tb("例题B", "example")]
        text = format_results(_data(results))
        assert text.index("理论A") < text.index("例题B")

    def test_prefer_ignored_for_questions_collection(self):
        data = {"collection": "questions",
                "results": [{"question_id": "Q-1", "stem": "题干"}]}
        assert format_results(data, prefer="solve") == format_results(data)


# ========== 子问渲染（对象数组兼容） ==========

class TestSubQuestionText:

    def test_plain_string_passthrough(self):
        assert sub_question_text("计算购入成本") == "计算购入成本"

    def test_object_renders_question_text(self):
        assert sub_question_text({"id": "q1", "question": "编制购入分录"}) == "编制购入分录"

    def test_object_answer_cut_by_default(self):
        """子问对象自带 answer，不剪裁就会从后门泄漏答案"""
        sub = {"question": "编制购入分录", "answer": "借：存货 100", "explanation": "略"}
        assert "借：存货" not in sub_question_text(sub)
        assert "借：存货 100" in sub_question_text(sub, include_answer=True)

    @pytest.mark.parametrize("sub", [None, "", {}, {"id": "q1"}, {"answer": "B"}])
    def test_unusable_sub_renders_empty_not_dict_repr(self, sub):
        """取不到文本时返回空串由调用方跳过，绝不能把 dict repr 塞进 prompt"""
        out = sub_question_text(sub)
        assert "{" not in out

    def test_object_answer_only_revealed_when_requested(self):
        assert sub_question_text({"answer": "B"}, include_answer=True) == "参考答案：B"

    def test_format_questions_renders_object_sub_questions(self):
        data = {"collection": "questions", "results": [{
            "question_id": "Q-300", "question_type": "综合题",
            "materials": "甲公司资料", "stem": None,
            "sub_questions": [{"question": "编制购入分录", "answer": "借：存货"},
                              "计算年末账面价值",
                              {"id": "q3"}],
            "answer": None, "explanation": None,
        }]}
        text = format_results(data)
        assert "子问1：编制购入分录" in text
        assert "子问2：计算年末账面价值" in text
        assert "子问3" not in text            # 空渲染跳过，编号保持连续
        assert "{" not in text
        assert "借：存货" not in text
        # 顶层 answer 为 null 但子问里藏着答案 → 仍须给出「已省略」提示
        assert ANSWER_OMITTED_HINT in text

    def test_format_questions_reveals_sub_answers_when_requested(self):
        data = {"collection": "questions", "results": [{
            "question_id": "Q-300", "sub_questions": [{"question": "编制分录", "answer": "借：存货"}],
        }]}
        assert "借：存货" in format_results(data, include_answer=True)


# ========== GET /api/subjects ==========

class TestSubjectsEndpoint:

    def test_list_subjects_requires_auth(self, client):
        resp = client.get("/api/subjects")
        assert resp.status_code in (401, 403)

    def test_list_subjects_returns_online_only(self, client, student_headers):
        resp = client.get("/api/subjects", headers=student_headers)
        assert resp.status_code == 200
        data = resp.json()
        # 当前仅 cpa_acc 上线
        assert len(data) == 1
        assert data[0]["subject"] == "cpa_acc"
        assert data[0]["status"] == "online"
        assert "name" in data[0]

    def test_list_subjects_admin_ok(self, client, admin_headers):
        resp = client.get("/api/subjects", headers=admin_headers)
        assert resp.status_code == 200
        assert all(s["status"] == "online" for s in resp.json())
