# -*- coding: utf-8 -*-
"""测试全局设置与单个学生权益（v4.0 M1）

覆盖：
- GET /api/admin/settings：5 键齐全、类型转换（memory_enabled_default 为 bool）
- PUT /api/admin/settings：部分更新 + 内存缓存刷新（测后恢复默认值）
- PUT /api/admin/students/{id}/entitlements：覆盖值设置 / null 恢复跟随全局 / 404
- 权限：非管理员 403
"""
from app.database import get_db_ctx
from app.settings_store import SETTING_DEFAULTS


class TestAppSettings:
    """GET/PUT /api/admin/settings"""

    def test_get_requires_admin(self, client, student_headers):
        resp = client.get("/api/admin/settings", headers=student_headers)
        assert resp.status_code == 403

    def test_get_all_keys_and_types(self, client, admin_headers):
        resp = client.get("/api/admin/settings", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == set(SETTING_DEFAULTS.keys())
        assert isinstance(data["daily_question_limit_default"], int)
        assert isinstance(data["memory_enabled_default"], bool)
        assert isinstance(data["chat_concurrency"], int)

    def test_put_partial_update_and_refresh(self, client, admin_headers):
        """只传要改的键；更新后 GET 立即可见（缓存已刷新）"""
        resp = client.put("/api/admin/settings", json={
            "chat_queue_size": 8,
        }, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == {"message": "ok"}

        data = client.get("/api/admin/settings", headers=admin_headers).json()
        assert data["chat_queue_size"] == 8
        # 未传的键不受影响
        assert data["daily_question_limit_default"] == SETTING_DEFAULTS["daily_question_limit_default"]

        # 落库校验（值以字符串存储）
        with get_db_ctx() as db:
            row = db.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = %s",
                ("chat_queue_size",),
            ).fetchone()
        assert row["setting_value"] == "8"

        # 恢复默认，避免影响其他测试
        resp = client.put("/api/admin/settings", json={
            "chat_queue_size": SETTING_DEFAULTS["chat_queue_size"],
        }, headers=admin_headers)
        assert resp.status_code == 200

    def test_put_requires_admin(self, client, student_headers):
        resp = client.put("/api/admin/settings", json={
            "chat_queue_size": 9,
        }, headers=student_headers)
        assert resp.status_code == 403


class TestEntitlements:
    """PUT /api/admin/students/{id}/entitlements"""

    def test_requires_admin(self, client, student_headers):
        resp = client.put("/api/admin/students/2/entitlements", json={
            "daily_question_limit": 5,
        }, headers=student_headers)
        assert resp.status_code == 403

    def test_student_not_found(self, client, admin_headers):
        resp = client.put("/api/admin/students/999999/entitlements", json={
            "daily_question_limit": 5,
        }, headers=admin_headers)
        assert resp.status_code == 404

    def test_set_override_then_reset_null(self, client, admin_headers):
        """设置覆盖值 → users 落列；显式 null → 恢复跟随全局"""
        resp = client.put("/api/admin/students/2/entitlements", json={
            "daily_question_limit": 5, "memory_enabled": False,
        }, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == {"message": "ok"}

        with get_db_ctx() as db:
            row = db.execute(
                "SELECT daily_question_limit, memory_enabled FROM users WHERE id = 2"
            ).fetchone()
        assert row["daily_question_limit"] == 5
        assert row["memory_enabled"] == 0

        # 显式传 null 恢复跟随全局
        resp = client.put("/api/admin/students/2/entitlements", json={
            "daily_question_limit": None, "memory_enabled": None,
        }, headers=admin_headers)
        assert resp.status_code == 200

        with get_db_ctx() as db:
            row = db.execute(
                "SELECT daily_question_limit, memory_enabled FROM users WHERE id = 2"
            ).fetchone()
        assert row["daily_question_limit"] is None
        assert row["memory_enabled"] is None

    def test_effective_value_helpers(self, client, admin_headers):
        """生效值封装：覆盖值优先，NULL 跟随全局默认"""
        from app.admin.entitlements import get_effective_limit, get_effective_memory_enabled

        assert get_effective_limit({"daily_question_limit": 3}) == 3
        assert get_effective_limit({"daily_question_limit": None}) == \
            SETTING_DEFAULTS["daily_question_limit_default"]
        assert get_effective_memory_enabled({"memory_enabled": 0}) is False
        assert get_effective_memory_enabled({"memory_enabled": None}) is \
            bool(SETTING_DEFAULTS["memory_enabled_default"])
