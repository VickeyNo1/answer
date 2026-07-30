# -*- coding: utf-8 -*-
"""学生记忆路由测试：5 接口（设计 §5.4-5.5）

学生端：错题本列表 / 重练判分 / 我的画像
管理端：学生画像 / 错题统计
"""
import pytest

from app.database import get_db_ctx
from tests.conftest import make_wrong_question


pytestmark = pytest.mark.usefixtures("clean_profile", "clean_exams")


# ========== 辅助 ==========


@pytest.fixture
def memory_off():
    """关闭学生(user_id=2)记忆开关（用例后恢复 NULL）"""
    with get_db_ctx() as db:
        db.execute("UPDATE users SET memory_enabled = 0 WHERE id = 2")
        db.commit()
    yield
    with get_db_ctx() as db:
        db.execute("UPDATE users SET memory_enabled = NULL WHERE id = 2")
        db.commit()


# ========== 错题本列表 ==========


class TestWrongQuestionList:
    def test_list_returns_items(self, client, student_headers):
        """列表返回错题条目"""
        make_wrong_question(2, "Q-001", answer="B", my_answer="C")
        make_wrong_question(2, "Q-002", answer="A", my_answer="D")

        resp = client.get("/api/wrong-questions", headers=student_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        item = data["items"][0]
        assert "id" in item
        assert item["question_type"] is not None
        assert item["wrong_count"] >= 1
        assert item["mastered"] == 0
        assert "last_wrong_at" in item
        assert "knowledge_point_ids" in item
        assert "subject" in item

    def test_list_filter_by_subject(self, client, student_headers):
        """按科目筛选"""
        make_wrong_question(2, "Q-001", subject="cpa_acc")
        make_wrong_question(2, "Q-002", subject="cpa_audit")

        resp = client.get("/api/wrong-questions?subject=cpa_acc", headers=student_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["subject"] == "cpa_acc"

    def test_list_filter_by_mastered(self, client, student_headers):
        """按掌握状态筛选"""
        make_wrong_question(2, "Q-001", mastered=0)
        make_wrong_question(2, "Q-002", mastered=1)

        resp = client.get("/api/wrong-questions?mastered=0", headers=student_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["mastered"] == 0

    def test_list_pagination(self, client, student_headers):
        """分页"""
        for i in range(5):
            make_wrong_question(2, f"Q-{i:03d}")
        resp = client.get("/api/wrong-questions?page=1&page_size=2", headers=student_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2

        resp = client.get("/api/wrong-questions?page=2&page_size=2", headers=student_headers)
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2

    def test_list_403_memory_off(self, client, student_headers, memory_off):
        """记忆开关关时 → 403"""
        make_wrong_question(2, "Q-001")
        resp = client.get("/api/wrong-questions", headers=student_headers)
        assert resp.status_code == 403

    def test_list_without_token(self, client):
        """未认证 → 401"""
        resp = client.get("/api/wrong-questions")
        assert resp.status_code == 401


# ========== 重练判分 ==========


class TestWrongQuestionRetry:
    def test_retry_objective_correct(self, client, student_headers):
        """客观题答对 → mastered=1"""
        wq_id = make_wrong_question(2, "Q-001", answer="B", my_answer="C")
        resp = client.post(
            f"/api/wrong-questions/{wq_id}/retry",
            json={"answer": "B"},
            headers=student_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["correct"] is True
        assert data["mastered"] == 1
        assert data["correct_answer"] == "B"

    def test_retry_objective_wrong(self, client, student_headers):
        """客观题答错 → wrong_count+1"""
        wq_id = make_wrong_question(2, "Q-001", answer="B", my_answer="C",
                                     wrong_count=1)
        resp = client.post(
            f"/api/wrong-questions/{wq_id}/retry",
            json={"answer": "D"},
            headers=student_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["correct"] is False
        assert data["mastered"] == 0

    def test_retry_subjective_correct(self, client, student_headers, fake_llm):
        """主观题 score_rate≥0.6 → 答对"""
        wq_id = make_wrong_question(2, "S-001", question_type="计算",
                                     answer="参考答案")
        fake_llm([('{"score_rate": 0.8, "reason": "基本正确"}', 100, 20)])
        resp = client.post(
            f"/api/wrong-questions/{wq_id}/retry",
            json={"answer": "我的解答"},
            headers=student_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["correct"] is True
        assert data["mastered"] == 1

    def test_retry_not_found(self, client, student_headers):
        """不存在的错题 → 404"""
        resp = client.post(
            "/api/wrong-questions/9999/retry",
            json={"answer": "A"},
            headers=student_headers,
        )
        assert resp.status_code == 404

    def test_retry_other_user_403(self, client, admin_headers):
        """非本人错题 → 403（admin 尝试学生的错题）"""
        wq_id = make_wrong_question(2, "Q-001", answer="B", my_answer="C")
        resp = client.post(
            f"/api/wrong-questions/{wq_id}/retry",
            json={"answer": "B"},
            headers=admin_headers,
        )
        assert resp.status_code == 403

    def test_retry_403_memory_off(self, client, student_headers, memory_off):
        """记忆开关关时 → 403"""
        wq_id = make_wrong_question(2, "Q-001", answer="B", my_answer="C")
        resp = client.post(
            f"/api/wrong-questions/{wq_id}/retry",
            json={"answer": "B"},
            headers=student_headers,
        )
        assert resp.status_code == 403


# ========== 我的画像 ==========


class TestMyProfile:
    def test_profile_returns_data(self, client, student_headers):
        """画像含 style_profile / weak_kps / recent_exam / memory_enabled"""
        # 造画像数据
        with get_db_ctx() as db:
            from app.profile import store as profile_store
            profile_store.upsert_profile(db, 2, "偏好分录示例讲解，概念辨析题易错。")

        resp = client.get("/api/me/profile", headers=student_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["style_profile"] == "偏好分录示例讲解，概念辨析题易错。"
        assert isinstance(data["weak_kps"], list)
        assert data["recent_exam"] is None  # 无考试数据
        assert data["memory_enabled"] is True

    def test_profile_memory_enabled_default(self, client, student_headers):
        """默认记忆开关开启"""
        resp = client.get("/api/me/profile", headers=student_headers)
        assert resp.status_code == 200
        assert resp.json()["memory_enabled"] is True

    def test_profile_memory_disabled(self, client, student_headers, memory_off):
        """记忆开关关时仍可看画像，但 memory_enabled=false"""
        resp = client.get("/api/me/profile", headers=student_headers)
        assert resp.status_code == 200
        assert resp.json()["memory_enabled"] is False

    def test_profile_empty(self, client, student_headers):
        """无任何数据时返回空画像"""
        resp = client.get("/api/me/profile", headers=student_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["style_profile"] is None
        assert data["weak_kps"] == []
        assert data["recent_exam"] is None
        assert data["memory_enabled"] is True


# ========== 管理端学生画像 ==========


class TestAdminStudentProfile:
    def test_admin_profile_structure(self, client, admin_headers):
        """管理端学生画像结构正确"""
        # 造数据
        make_wrong_question(2, "Q-001", answer="B", my_answer="C")
        with get_db_ctx() as db:
            from app.profile import store as profile_store
            profile_store.upsert_profile(db, 2, "偏好图表辅助理解。")

        resp = client.get("/api/admin/students/2/profile", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["style_profile"] == "偏好图表辅助理解。"
        assert isinstance(data["weak_kps"], list)
        assert "wrong_stats" in data
        assert data["wrong_stats"]["total"] >= 1
        assert "unmastered" in data["wrong_stats"]
        assert isinstance(data["wrong_stats"]["hot_wrong_kps"], list)

    def test_admin_profile_not_found(self, client, admin_headers):
        """学生不存在 → 404"""
        resp = client.get("/api/admin/students/9999/profile", headers=admin_headers)
        assert resp.status_code == 404

    def test_admin_profile_forbidden_for_student(self, client, student_headers):
        """学生无权访问 → 403"""
        resp = client.get("/api/admin/students/2/profile", headers=student_headers)
        assert resp.status_code == 403


# ========== 管理端错题统计 ==========


class TestAdminWrongStats:
    def test_admin_stats_returns_top_kps(self, client, admin_headers):
        """错题统计返回 Top 知识点"""
        make_wrong_question(2, "Q-001", kp_ids=["ACC-01-03-01"])
        make_wrong_question(2, "Q-002", kp_ids=["ACC-01-03-01"])
        make_wrong_question(2, "Q-003", kp_ids=["ACC-02-01-01"])

        resp = client.get("/api/admin/wrong-questions/stats", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # ACC-01-03-01 出现 2 次，应排第一
        top = data[0]
        assert top["kp_id"] == "ACC-01-03-01"
        assert top["wrong_count"] == 2
        assert top["student_count"] == 1

    def test_admin_stats_forbidden_for_student(self, client, student_headers):
        """学生无权访问 → 403"""
        resp = client.get("/api/admin/wrong-questions/stats", headers=student_headers)
        assert resp.status_code == 403

    def test_admin_stats_days_top_params(self, client, admin_headers):
        """days/top 参数生效"""
        make_wrong_question(2, "Q-001", kp_ids=["KP-1"])
        make_wrong_question(2, "Q-002", kp_ids=["KP-2"])

        resp = client.get(
            "/api/admin/wrong-questions/stats?days=30&top=1",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1  # top=1
