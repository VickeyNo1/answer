# -*- coding: utf-8 -*-
"""测试 GET /api/admin/stats - 获取统计数据"""
import pytest
from app.database import get_db_ctx


class TestAdminStats:

    def test_stats_success(self, client, admin_headers):
        """获取统计数据成功"""
        resp = client.get("/api/admin/stats", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_students" in data
        assert "total_conversations" in data
        assert "today_active_users" in data

    def test_stats_types(self, client, admin_headers):
        """统计数据类型正确"""
        resp = client.get("/api/admin/stats", headers=admin_headers)
        data = resp.json()
        assert isinstance(data["total_students"], int)
        assert isinstance(data["total_conversations"], int)
        assert isinstance(data["today_active_users"], int)

    def test_stats_total_students(self, client, admin_headers):
        """学生总数正确（不含管理员）"""
        resp = client.get("/api/admin/stats", headers=admin_headers)
        data = resp.json()
        # 至少有 1 个测试学生
        assert data["total_students"] >= 1

    def test_stats_without_token(self, client):
        """未认证返回 403"""
        resp = client.get("/api/admin/stats")
        assert resp.status_code in (401, 403)

    def test_stats_student_forbidden(self, client, student_headers):
        """学生无权访问返回 403"""
        resp = client.get("/api/admin/stats", headers=student_headers)
        assert resp.status_code == 403

    def test_stats_reflects_new_student(self, client, admin_headers):
        """创建学生后统计数字增加"""
        # 获取当前数字
        resp1 = client.get("/api/admin/stats", headers=admin_headers)
        before = resp1.json()["total_students"]

        # 创建学生
        client.post("/api/admin/students", json={
            "student_id": "stats_test_001",
            "name": "统计测试",
            "password": "pass123",
        }, headers=admin_headers)

        # 再次获取
        resp2 = client.get("/api/admin/stats", headers=admin_headers)
        after = resp2.json()["total_students"]
        assert after == before + 1

        # 清理
        with get_db_ctx() as db:
            db.execute("DELETE FROM users WHERE student_id = 'stats_test_001'")
            db.commit()
