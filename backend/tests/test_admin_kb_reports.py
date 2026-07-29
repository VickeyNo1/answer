# -*- coding: utf-8 -*-
"""测试检索可观测报表：GET /api/admin/kb/stats + GET /api/admin/kb/hot-kps

覆盖：
- stats：total/empty_rate/degraded_count/avg_elapsed_ms/by_day/by_status（六态齐全）
- hot-kps：kp_ids JSON 应用层展开计数 TopN
- 权限：非管理员 403
"""
import pytest

from app.database import get_db_ctx


@pytest.fixture(scope="module")
def kb_logs(client):
    """造数：清空后写入 4 条已知状态的检索日志（created_at 默认今天）"""
    with get_db_ctx() as db:
        db.execute("DELETE FROM kb_search_logs")
        rows = [
            # (status, result_count, kp_ids, elapsed_ms)
            ("ok", 2, '["KP-001", "KP-002"]', 100),
            ("ok", 1, '["KP-001"]', 300),
            ("empty", 0, None, 50),
            ("degraded", 0, None, 2000),
        ]
        for status_, count, kp_ids, elapsed in rows:
            db.execute(
                """INSERT INTO kb_search_logs
                   (user_id, conversation_id, subject, collection, query,
                    result_count, kp_ids, status, elapsed_ms)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (2, None, "cpa_acc", "textbook", "存货计价",
                 count, kp_ids, status_, elapsed),
            )
        db.commit()
    yield


class TestKbStats:
    """GET /api/admin/kb/stats"""

    def test_requires_admin(self, client, student_headers):
        resp = client.get("/api/admin/kb/stats", headers=student_headers)
        assert resp.status_code == 403

    def test_stats_aggregation(self, client, admin_headers, kb_logs):
        resp = client.get("/api/admin/kb/stats?days=7", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()

        assert data["total"] == 4
        assert data["empty_count"] == 1
        assert data["empty_rate"] == 0.25
        assert data["degraded_count"] == 1
        # (100+300+50+2000)/4 = 612.5 → int 截断
        assert data["avg_elapsed_ms"] == 612

        # by_status 六态键齐全，未出现的状态为 0
        assert data["by_status"] == {
            "ok": 2, "empty": 1, "timeout": 0,
            "http_error": 0, "code_error": 0, "degraded": 1,
        }

        # by_day：4 条均为今天，聚合为 1 天
        assert len(data["by_day"]) == 1
        day = data["by_day"][0]
        assert day["total"] == 4
        assert day["empty"] == 1
        assert day["degraded"] == 1
        assert isinstance(day["date"], str)

    def test_stats_empty_window(self, client, admin_headers, kb_logs):
        """无数据时间窗：total=0，empty_rate=0.0 不除零"""
        with get_db_ctx() as db:
            db.execute("DELETE FROM kb_search_logs")
            db.commit()
        try:
            resp = client.get("/api/admin/kb/stats?days=7", headers=admin_headers)
            data = resp.json()
            assert data["total"] == 0
            assert data["empty_rate"] == 0.0
            assert data["avg_elapsed_ms"] == 0
            assert data["by_day"] == []
        finally:
            # 恢复造数供后续用例使用（fixture 为 module 级不会重建）
            with get_db_ctx() as db:
                for status_, count, kp_ids, elapsed in [
                    ("ok", 2, '["KP-001", "KP-002"]', 100),
                    ("ok", 1, '["KP-001"]', 300),
                    ("empty", 0, None, 50),
                    ("degraded", 0, None, 2000),
                ]:
                    db.execute(
                        """INSERT INTO kb_search_logs
                           (user_id, conversation_id, subject, collection, query,
                            result_count, kp_ids, status, elapsed_ms)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (2, None, "cpa_acc", "textbook", "存货计价",
                         count, kp_ids, status_, elapsed),
                    )
                db.commit()


class TestKbHotKps:
    """GET /api/admin/kb/hot-kps"""

    def test_requires_admin(self, client, student_headers):
        resp = client.get("/api/admin/kb/hot-kps", headers=student_headers)
        assert resp.status_code == 403

    def test_hot_kps_topn(self, client, admin_headers, kb_logs):
        resp = client.get(
            "/api/admin/kb/hot-kps?days=30&top=10", headers=admin_headers
        )
        assert resp.status_code == 200
        items = resp.json()
        # KP-001 出现 2 次 > KP-002 出现 1 次
        assert items[0] == {"kp_id": "KP-001", "count": 2}
        assert items[1] == {"kp_id": "KP-002", "count": 1}

    def test_hot_kps_top_limit(self, client, admin_headers, kb_logs):
        resp = client.get(
            "/api/admin/kb/hot-kps?days=30&top=1", headers=admin_headers
        )
        items = resp.json()
        assert len(items) == 1
        assert items[0]["kp_id"] == "KP-001"
