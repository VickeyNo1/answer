# -*- coding: utf-8 -*-
"""E2E: 大模型管理 - GET/POST/PUT/DELETE /api/admin/models, activate, usage"""
import time
import pytest
from tests.e2e.conftest import api_request


def _active_model_id(admin_token: str) -> int | None:
    """当前激活模型的 id；无激活模型返回 None"""
    code, body = api_request("GET", "/api/admin/models", token=admin_token)
    if code != 200:
        return None
    for m in body:
        if m.get("is_active"):
            return m["id"]
    return None


class TestE2EModelCRUD:

    def test_list_models(self, server_available, admin_token):
        """模型列表返回数组"""
        code, body = api_request("GET", "/api/admin/models", token=admin_token)
        assert code == 200
        assert isinstance(body, list)

    def test_create_update_activate_delete(self, server_available, admin_token):
        """完整生命周期：创建 → 修改 → 激活 → 激活态拒删 → 还原 → 删除

        ⚠️ activate 会把全表 is_active 清零，用例结束**必须还原**：否则库里再没有
        激活模型，get_active_model() 静默回退 .env 的 CHAT_MODEL，若该名不在
        model_configs 中，此后所有用量 cost 恒为 0 且无任何告警。
        """
        name = f"e2e_model_{int(time.time())}"
        prev_active = _active_model_id(admin_token)
        model_id = None
        try:
            # 创建
            code, created = api_request("POST", "/api/admin/models", token=admin_token, data={
                "provider": "ali",
                "model_name": name,
                "display_name": "E2E模型",
                "price_in": 0.001,
                "price_out": 0.002,
                "enabled": True,
            })
            assert code == 201
            model_id = created["id"]

            # 修改
            code, updated = api_request("PUT", f"/api/admin/models/{model_id}",
                                        token=admin_token, data={"price_in": 0.003})
            assert code == 200
            assert updated["price_in"] == 0.003

            # 激活
            code, activated = api_request("POST", f"/api/admin/models/{model_id}/activate",
                                          token=admin_token)
            assert code == 200
            assert activated["is_active"] is True

            # 激活态不可删（护栏：删了会让全系统失去激活模型）
            code, body = api_request("DELETE", f"/api/admin/models/{model_id}",
                                     token=admin_token)
            assert code == 409
            assert "当前使用" in body.get("detail", "")
        finally:
            # 先还原原激活模型，再删测试模型（顺序不可颠倒，否则还原会被 409 之外的
            # 状态干扰，且中间态可能无激活模型）
            if prev_active is not None:
                api_request("POST", f"/api/admin/models/{prev_active}/activate",
                            token=admin_token)
            if model_id is not None:
                api_request("DELETE", f"/api/admin/models/{model_id}", token=admin_token)

        assert _active_model_id(admin_token) == prev_active

    def test_create_student_forbidden(self, server_available, test_student):
        """学生无权创建模型"""
        code, _ = api_request("POST", "/api/admin/models", token=test_student["token"], data={
            "provider": "ali",
            "model_name": "e2e_forbidden",
            "display_name": "禁止",
            "price_in": 0.001,
            "price_out": 0.002,
        })
        assert code == 403


class TestE2EModelUsage:

    def test_usage_stats(self, server_available, admin_token):
        """用量统计返回结构完整"""
        code, body = api_request("GET", "/api/admin/models/usage?days=7", token=admin_token)
        assert code == 200
        for key in ("total_tokens", "total_cost", "today_tokens",
                    "today_cost", "by_model", "daily"):
            assert key in body
        assert len(body["daily"]) == 7

    def test_usage_student_forbidden(self, server_available, test_student):
        """学生无权查看用量"""
        code, _ = api_request("GET", "/api/admin/models/usage",
                              token=test_student["token"])
        assert code == 403
