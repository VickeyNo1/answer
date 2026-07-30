# -*- coding: utf-8 -*-
"""暂存作答测试：PUT /api/exams/{id}/answers"""
import pytest

from tests.conftest import make_question

pytestmark = pytest.mark.usefixtures("clean_exams")


def _create_exam(client, headers, fake_draw, questions=None):
    """辅助：mock 抽题并创建一张试卷，返回试卷 id"""
    fake_draw(questions or [make_question("Q-1"), make_question("Q-2")])
    resp = client.post("/api/exams", json={"counts": {"单选": 2}}, headers=headers)
    assert resp.status_code == 201
    return resp.json()["id"]


class TestExamSaveAnswers:
    """暂存：可多次覆盖、题号校验、归属与状态校验"""

    def test_save_and_overwrite(self, client, student_headers, fake_draw):
        """多次暂存后以最后一次为准"""
        exam_id = _create_exam(client, student_headers, fake_draw)

        resp = client.put(
            f"/api/exams/{exam_id}/answers",
            json={"answers": [{"seq": 1, "content": "A"}, {"seq": 2, "content": "C"}]},
            headers=student_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == {"message": "ok"}

        resp = client.put(
            f"/api/exams/{exam_id}/answers",
            json={"answers": [{"seq": 1, "content": "B"}]},
            headers=student_headers,
        )
        assert resp.status_code == 200

        detail = client.get(f"/api/exams/{exam_id}", headers=student_headers).json()
        assert [a["my_answer"] for a in detail["answers"]] == ["B", "C"]

    def test_save_empty_list_ok(self, client, student_headers, fake_draw):
        """空作答列表直接返回 ok"""
        exam_id = _create_exam(client, student_headers, fake_draw)
        resp = client.put(f"/api/exams/{exam_id}/answers", json={"answers": []},
                          headers=student_headers)
        assert resp.status_code == 200

    def test_save_seq_out_of_range_400(self, client, student_headers, fake_draw):
        """题号不属于本试卷 → 400，且不影响已有作答"""
        exam_id = _create_exam(client, student_headers, fake_draw)
        client.put(f"/api/exams/{exam_id}/answers",
                   json={"answers": [{"seq": 1, "content": "A"}]},
                   headers=student_headers)

        resp = client.put(
            f"/api/exams/{exam_id}/answers",
            json={"answers": [{"seq": 1, "content": "D"}, {"seq": 99, "content": "D"}]},
            headers=student_headers,
        )
        assert resp.status_code == 400
        assert "99" in resp.json()["detail"]

        detail = client.get(f"/api/exams/{exam_id}", headers=student_headers).json()
        assert detail["answers"][0]["my_answer"] == "A"  # 整批不生效

    def test_save_other_user_403(self, client, student_headers, admin_headers, fake_draw):
        """非本人试卷 → 403"""
        exam_id = _create_exam(client, student_headers, fake_draw)
        resp = client.put(f"/api/exams/{exam_id}/answers",
                          json={"answers": [{"seq": 1, "content": "A"}]},
                          headers=admin_headers)
        assert resp.status_code == 403

    def test_save_exam_not_found_404(self, client, student_headers):
        """试卷不存在 → 404"""
        resp = client.put("/api/exams/999999/answers",
                          json={"answers": [{"seq": 1, "content": "A"}]},
                          headers=student_headers)
        assert resp.status_code == 404

    def test_save_after_submit_409(self, client, student_headers, fake_draw):
        """已交卷试卷不能再暂存 → 409"""
        exam_id = _create_exam(client, student_headers, fake_draw)
        assert client.post(f"/api/exams/{exam_id}/submit",
                           headers=student_headers).status_code == 200

        resp = client.put(f"/api/exams/{exam_id}/answers",
                          json={"answers": [{"seq": 1, "content": "A"}]},
                          headers=student_headers)
        assert resp.status_code == 409
