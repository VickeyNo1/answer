# -*- coding: utf-8 -*-
"""创建试卷测试：POST /api/exams（抽题走 mock，不依赖知识库服务）"""
import pytest

from app.kb.client import KbDrawError
from tests.conftest import make_question

pytestmark = pytest.mark.usefixtures("clean_exams")


class TestExamCreate:
    """组卷：题量/满分计算、ongoing 唯一、参数校验、抽题失败"""

    def test_create_success(self, client, student_headers, fake_draw):
        """正常创卷：题号从 1 起、满分按题型累加、抽题参数正确透传"""
        questions = [make_question(f"Q-{i}") for i in range(5)]
        questions += [make_question(f"M-{i}", question_type="多选", answer="ABD")
                      for i in range(2)]
        calls = fake_draw(questions)

        resp = client.post(
            "/api/exams",
            json={"subject": "cpa_acc", "chapter_ids": ["ACC-01"],
                  "counts": {"单选": 5, "多选": 2, "计算": 0}},
            headers=student_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "ongoing"
        assert data["question_count"] == 7
        assert data["total_score"] == 9.0  # 5×1 + 2×2
        assert [q["seq"] for q in data["questions"]] == list(range(1, 8))
        assert data["questions"][0]["full_score"] == 1.0

        # 题量为 0 的题型不下发给知识库
        assert calls == [{"subject": "cpa_acc", "chapter_ids": ["ACC-01"],
                          "counts": {"单选": 5, "多选": 2}}]

    def test_create_response_hides_answer(self, client, student_headers, fake_draw):
        """创卷响应剔除参考答案与解析（快照仅落库）"""
        fake_draw([make_question("Q-1")])
        resp = client.post(
            "/api/exams",
            json={"counts": {"单选": 1}},
            headers=student_headers,
        )
        assert resp.status_code == 201
        question = resp.json()["questions"][0]
        assert "answer" not in question
        assert "explanation" not in question
        assert "解析" not in resp.text

    def test_create_cancels_previous_ongoing(self, client, student_headers, fake_draw):
        """已有未完成试卷时重新创建 → 旧卷自动作废，新卷正常 201"""
        fake_draw([make_question("Q-1")])
        first = client.post("/api/exams", json={"counts": {"单选": 1}},
                            headers=student_headers)
        assert first.status_code == 201
        first_id = first.json()["id"]

        fake_draw([make_question("Q-2")])
        resp = client.post("/api/exams", json={"counts": {"单选": 1}},
                           headers=student_headers)
        assert resp.status_code == 201
        assert resp.json()["id"] != first_id

    def test_create_subject_fallback(self, client, student_headers, fake_draw):
        """非法 subject 回退默认科目 cpa_acc"""
        calls = fake_draw([make_question("Q-1")])
        resp = client.post(
            "/api/exams",
            json={"subject": "not_exist", "counts": {"单选": 1}},
            headers=student_headers,
        )
        assert resp.status_code == 201
        assert calls[0]["subject"] == "cpa_acc"

    def test_create_counts_all_zero_400(self, client, student_headers, fake_draw):
        """题量全 0 → 400，且不调抽题"""
        calls = fake_draw([make_question("Q-1")])
        resp = client.post(
            "/api/exams",
            json={"counts": {"单选": 0, "多选": 0}},
            headers=student_headers,
        )
        assert resp.status_code == 400
        assert calls == []

    def test_create_counts_invalid_type_400(self, client, student_headers, fake_draw):
        """题型枚举非法 → 400"""
        fake_draw([make_question("Q-1")])
        resp = client.post("/api/exams", json={"counts": {"填空": 3}},
                           headers=student_headers)
        assert resp.status_code == 400

    def test_create_counts_over_limit_400(self, client, student_headers, fake_draw):
        """单题型超过 50 题上限 → 400"""
        fake_draw([make_question("Q-1")])
        resp = client.post("/api/exams", json={"counts": {"单选": 51}},
                           headers=student_headers)
        assert resp.status_code == 400

    def test_create_draw_failed_502_no_leftover(self, client, student_headers, fake_draw):
        """抽题失败 → 502（不降级），且不留下卡住学生的 ongoing 试卷"""
        fake_draw(KbDrawError("知识库抽题超时或网络异常"))
        resp = client.post("/api/exams", json={"counts": {"单选": 5}},
                           headers=student_headers)
        assert resp.status_code == 502
        assert "知识库暂时不可用" in resp.json()["detail"]

        assert client.get("/api/exams", headers=student_headers).json() == []

    def test_create_no_question_400(self, client, student_headers, fake_draw):
        """知识库返回 0 题（范围内题量不足）→ 400 提示调整范围"""
        fake_draw([])
        resp = client.post("/api/exams", json={"counts": {"单选": 5}},
                           headers=student_headers)
        assert resp.status_code == 400
        assert client.get("/api/exams", headers=student_headers).json() == []

    def test_create_skips_invalid_question(self, client, student_headers, fake_draw):
        """题型/题目 ID 不合规的题目跳过，按实际入卷题数组卷"""
        fake_draw([
            make_question("Q-1"),
            make_question("Q-2", question_type="填空"),  # 未知题型
            make_question("", question_type="单选"),      # 缺 question_id
        ])
        resp = client.post("/api/exams", json={"counts": {"单选": 3}},
                           headers=student_headers)
        assert resp.status_code == 201
        assert resp.json()["question_count"] == 1
        assert resp.json()["total_score"] == 1.0

    def test_create_insufficient_uses_actual_count(self, client, student_headers, fake_draw):
        """题量不足时按知识库实际返回数量组卷（不报错）"""
        fake_draw([make_question(f"Q-{i}") for i in range(3)])
        resp = client.post("/api/exams", json={"counts": {"单选": 10}},
                           headers=student_headers)
        assert resp.status_code == 201
        assert resp.json()["question_count"] == 3
        assert resp.json()["total_score"] == 3.0
