# -*- coding: utf-8 -*-
"""测试 GET /api/health - 健康检查"""


class TestHealth:

    def test_health_ok(self, client):
        """健康检查返回 ok"""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_health_no_auth_required(self, client):
        """健康检查不需要认证"""
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_response_format(self, client):
        """健康检查响应格式正确"""
        resp = client.get("/api/health")
        data = resp.json()
        assert isinstance(data, dict)
        assert "status" in data
