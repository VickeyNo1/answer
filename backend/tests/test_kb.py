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
