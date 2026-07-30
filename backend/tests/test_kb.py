# -*- coding: utf-8 -*-
"""测试知识库客户端、结果拼接与 GET /api/subjects（契约见 doc/知识库对接文档.md）"""
import pytest

from app.kb import client as kb_client
from app.kb.prompt import format_results, collect_kp_ids, FALLBACK_TEXT


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
        text = format_results(data)
        assert "Q-100" in text
        assert "存货" in text
        assert "答案" in text

    def test_collect_kp_ids_dedup_order(self):
        data = {"results": [
            {"knowledge_point_ids": ["KP-001", "KP-002"]},
            {"knowledge_point_ids": ["KP-002", "KP-003"]},
        ]}
        assert collect_kp_ids(data) == ["KP-001", "KP-002", "KP-003"]

    def test_collect_kp_ids_none(self):
        assert collect_kp_ids(None) == []


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
