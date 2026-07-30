# -*- coding: utf-8 -*-
"""判分异议测试：POST /api/exams/{id}/answers/{seq}/dispute"""
import pytest

from app.database import get_db_ctx
from tests.conftest import make_question

pytestmark = pytest.mark.usefixtures("clean_exams")


def _graded_exam(client, headers, fake_draw):
    """造一张含主观题的已判卷试卷（B3 判卷引擎接入前直接置 graded）"""
    fake_draw([make_question("Q-1", answer="B"),
               make_question("J-1", question_type="计算")])
    exam_id = client.post("/api/exams", json={"counts": {"单选": 1, "计算": 1}},
                          headers=headers).json()["id"]
    client.put(f"/api/exams/{exam_id}/answers",
               json={"answers": [{"seq": 1, "content": "B"},
                                 {"seq": 2, "content": "解题过程……"}]},
               headers=headers)
    client.post(f"/api/exams/{exam_id}/submit", headers=headers)
    with get_db_ctx() as db:
        db.execute(
            "UPDATE exams SET status = 'graded', obtained_score = 6 WHERE id = %s",
            (exam_id,),
        )
        db.execute(
            "UPDATE exam_answers SET score = 5, llm_reason = '思路正确，结论有误' "
            "WHERE exam_id = %s AND seq = 2",
            (exam_id,),
        )
        db.commit()
    return exam_id


def _disputed(exam_id, seq):
    with get_db_ctx() as db:
        cursor = db.execute(
            "SELECT disputed FROM exam_answers WHERE exam_id = %s AND seq = %s",
            (exam_id, seq),
        )
        return int(cursor.fetchone()["disputed"])


class TestExamDispute:
    """异议：仅 graded 后的主观题可标记"""

    def test_dispute_subjective_ok(self, client, student_headers, fake_draw):
        exam_id = _graded_exam(client, student_headers, fake_draw)
        resp = client.post(f"/api/exams/{exam_id}/answers/2/dispute",
                           headers=student_headers)
        assert resp.status_code == 200
        assert resp.json() == {"message": "ok"}
        assert _disputed(exam_id, 2) == 1

        # 详情中回显异议标记
        data = client.get(f"/api/exams/{exam_id}", headers=student_headers).json()
        assert data["answers"][1]["disputed"] == 1
        assert data["answers"][1]["llm_reason"] == "思路正确，结论有误"

    def test_dispute_objective_400(self, client, student_headers, fake_draw):
        """客观题由程序判定，不支持异议"""
        exam_id = _graded_exam(client, student_headers, fake_draw)
        resp = client.post(f"/api/exams/{exam_id}/answers/1/dispute",
                           headers=student_headers)
        assert resp.status_code == 400
        assert _disputed(exam_id, 1) == 0

    def test_dispute_before_graded_409(self, client, student_headers, fake_draw):
        """未判卷完成不能提异议"""
        fake_draw([make_question("J-1", question_type="计算")])
        exam_id = client.post("/api/exams", json={"counts": {"计算": 1}},
                              headers=student_headers).json()["id"]
        resp = client.post(f"/api/exams/{exam_id}/answers/1/dispute",
                           headers=student_headers)
        assert resp.status_code == 409

    def test_dispute_seq_not_found_404(self, client, student_headers, fake_draw):
        exam_id = _graded_exam(client, student_headers, fake_draw)
        resp = client.post(f"/api/exams/{exam_id}/answers/99/dispute",
                           headers=student_headers)
        assert resp.status_code == 404

    def test_dispute_other_user_403(self, client, student_headers, admin_headers, fake_draw):
        exam_id = _graded_exam(client, student_headers, fake_draw)
        resp = client.post(f"/api/exams/{exam_id}/answers/2/dispute",
                           headers=admin_headers)
        assert resp.status_code == 403
