# -*- coding: utf-8 -*-
"""E2E: 健康检查接口 GET /api/health"""
import pytest
from tests.e2e.conftest import api_request


class TestE2EHealth:

    def test_health_ok(self, server_available):
        """GET /api/health 返回 ok"""
        code, body = api_request("GET", "/api/health")
        assert code == 200
        assert body["status"] == "ok"

    def test_health_no_auth_required(self, server_available):
        """健康检查不需要认证"""
        code, _ = api_request("GET", "/api/health")
        assert code == 200
