# -*- coding: utf-8 -*-
"""测试 GET /api/health - 健康检查（v4.0：status/mysql/kb 三字段）"""
import pytest


class TestHealth:

    @pytest.fixture(autouse=True)
    def _mock_kb_probe(self, monkeypatch):
        """kb 探测走真实 HTTP，测试环境统一 mock 为可用"""
        monkeypatch.setattr("app.main.kb_client.probe", lambda: True)

    def test_health_ok(self, client):
        """MySQL 与 kb 均可用时 status=ok"""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["mysql"] == "ok"
        assert data["kb"] == "ok"

    def test_health_no_auth_required(self, client):
        """健康检查不需要认证"""
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_response_format(self, client):
        """健康检查响应包含 status/mysql/kb 三字段"""
        resp = client.get("/api/health")
        data = resp.json()
        assert isinstance(data, dict)
        assert set(data.keys()) == {"status", "mysql", "kb"}

    def test_health_kb_fail_degraded_http_200(self, client, monkeypatch):
        """kb 探测失败时 status=degraded，HTTP 仍 200"""
        monkeypatch.setattr("app.main.kb_client.probe", lambda: False)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["mysql"] == "ok"
        assert data["kb"] == "fail"
