# -*- coding: utf-8 -*-
"""交卷测试：POST /api/exams/{id}/submit（客观题即时判分）"""
import pytest

from app.database import get_db_ctx
from tests.conftest import make_question

pytestmark = pytest.mark.usefixtures("clean_exams")


def _create(client, headers, fake_draw, questions, counts):
    fake_draw(questions)
    resp = client.post("/api/exams", json={"counts": counts}, headers=headers)
    assert resp.status_code == 201
    return resp.json()["id"]


def _exam_row(exam_id):
    with get_db_ctx() as db:
        cursor = db.execute(
            "SELECT status, obtained_score, submitted_at FROM exams WHERE id = %s",
            (exam_id,),
        )
        return cursor.fetchone()


class TestExamSubmit:
    """交卷：客观题即时分、主观题挂起、重复交卷与归属校验"""

    def test_submit_objective_only_graded(self, client, student_headers, fake_draw):
        """纯客观题：交卷即 graded，总分=客观题得分"""
        questions = [make_question(f"Q-{i}", answer="B") for i in range(3)]
        exam_id = _create(client, student_headers, fake_draw, questions, {"单选": 3})
        client.put(
            f"/api/exams/{exam_id}/answers",
            json={"answers": [{"seq": 1, "content": "B"}, {"seq": 2, "content": "B"},
                              {"seq": 3, "content": "A"}]},
            headers=student_headers,
        )

        resp = client.post(f"/api/exams/{exam_id}/submit", headers=student_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"id": exam_id, "status": "graded",
                        "objective_score": 2.0, "pending_subjective": 0}

        row = _exam_row(exam_id)
        assert row["status"] == "graded"
        assert float(row["obtained_score"]) == 2.0
        assert row["submitted_at"] is not None

    def test_submit_multi_choice_partial_zero(self, client, student_headers, fake_draw):
        """多选半对不给分；选项顺序不同不影响判分"""
        questions = [make_question("M-1", question_type="多选", answer="ABD"),
                     make_question("M-2", question_type="多选", answer="AC")]
        exam_id = _create(client, student_headers, fake_draw, questions, {"多选": 2})
        client.put(
            f"/api/exams/{exam_id}/answers",
            json={"answers": [{"seq": 1, "content": "AB"}, {"seq": 2, "content": "CA"}]},
            headers=student_headers,
        )

        data = client.post(f"/api/exams/{exam_id}/submit", headers=student_headers).json()
        assert data["objective_score"] == 2.0  # 第 1 题半对 0 分，第 2 题乱序全对 2 分

    def test_submit_blank_answer_zero(self, client, student_headers, fake_draw):
        """未作答记 0 分"""
        exam_id = _create(client, student_headers, fake_draw,
                          [make_question("Q-1")], {"单选": 1})
        data = client.post(f"/api/exams/{exam_id}/submit", headers=student_headers).json()
        assert data["objective_score"] == 0.0
        assert data["status"] == "graded"

    def test_submit_with_subjective_grading(self, client, student_headers, fake_draw):
        """含主观题：置 grading，客观分即时返回，总分待判卷完成后汇总"""
        questions = [make_question("Q-1", answer="B"),
                     make_question("J-1", question_type="计算"),
                     make_question("Z-1", question_type="综合")]
        exam_id = _create(client, student_headers, fake_draw, questions,
                          {"单选": 1, "计算": 1, "综合": 1})
        client.put(f"/api/exams/{exam_id}/answers",
                   json={"answers": [{"seq": 1, "content": "B"},
                                     {"seq": 2, "content": "解题过程……"}]},
                   headers=student_headers)

        data = client.post(f"/api/exams/{exam_id}/submit", headers=student_headers).json()
        assert data["status"] == "grading"
        assert data["objective_score"] == 1.0
        assert data["pending_subjective"] == 2

        row = _exam_row(exam_id)
        assert row["status"] == "grading"
        assert row["obtained_score"] is None

    def test_submit_twice_409(self, client, student_headers, fake_draw):
        """重复交卷 → 409"""
        exam_id = _create(client, student_headers, fake_draw,
                          [make_question("Q-1")], {"单选": 1})
        assert client.post(f"/api/exams/{exam_id}/submit",
                           headers=student_headers).status_code == 200
        resp = client.post(f"/api/exams/{exam_id}/submit", headers=student_headers)
        assert resp.status_code == 409

    def test_submit_other_user_403(self, client, student_headers, admin_headers, fake_draw):
        """非本人试卷 → 403"""
        exam_id = _create(client, student_headers, fake_draw,
                          [make_question("Q-1")], {"单选": 1})
        resp = client.post(f"/api/exams/{exam_id}/submit", headers=admin_headers)
        assert resp.status_code == 403

    def test_submit_releases_ongoing_slot(self, client, student_headers, fake_draw):
        """交卷后可再创建新试卷（ongoing 名额释放）"""
        exam_id = _create(client, student_headers, fake_draw,
                          [make_question("Q-1")], {"单选": 1})
        client.post(f"/api/exams/{exam_id}/submit", headers=student_headers)

        fake_draw([make_question("Q-2")])
        resp = client.post("/api/exams", json={"counts": {"单选": 1}},
                           headers=student_headers)
        assert resp.status_code == 201
