# -*- coding: utf-8 -*-
"""成绩单详情与列表测试：GET /api/exams、GET /api/exams/{id}"""
import pytest

from tests.conftest import make_question

pytestmark = pytest.mark.usefixtures("clean_exams")


def _create(client, headers, fake_draw, questions, counts):
    fake_draw(questions)
    resp = client.post("/api/exams", json={"counts": counts}, headers=headers)
    assert resp.status_code == 201
    return resp.json()["id"]


class TestExamDetail:
    """详情：graded 前后字段可见性、掌握度、归属校验"""

    def test_detail_hides_answer_before_graded(self, client, student_headers, fake_draw):
        """ongoing 期间只回作答进度，不露参考答案/解析/得分/掌握度"""
        exam_id = _create(client, student_headers, fake_draw,
                          [make_question("Q-1", answer="B")], {"单选": 1})
        client.put(f"/api/exams/{exam_id}/answers",
                   json={"answers": [{"seq": 1, "content": "A"}]},
                   headers=student_headers)

        data = client.get(f"/api/exams/{exam_id}", headers=student_headers).json()
        assert data["status"] == "ongoing"
        assert data["mastery"] is None
        assert data["obtained_score"] is None
        answer = data["answers"][0]
        assert answer["my_answer"] == "A"
        assert answer["stem"] == "题干 Q-1"
        assert answer["correct_answer"] is None
        assert answer["explanation"] is None
        assert answer["score"] is None
        assert answer["full_score"] == 1.0

    def test_detail_after_graded_reveals(self, client, student_headers, fake_draw):
        """graded 后展示参考答案/解析/得分/知识点与掌握度"""
        questions = [make_question("Q-1", answer="B", kp_ids=["ACC-01-01-01"]),
                     make_question("Q-2", answer="C", kp_ids=["ACC-03-02-01"])]
        exam_id = _create(client, student_headers, fake_draw, questions, {"单选": 2})
        client.put(f"/api/exams/{exam_id}/answers",
                   json={"answers": [{"seq": 1, "content": "B"}, {"seq": 2, "content": "A"}]},
                   headers=student_headers)
        client.post(f"/api/exams/{exam_id}/submit", headers=student_headers)

        data = client.get(f"/api/exams/{exam_id}", headers=student_headers).json()
        assert data["status"] == "graded"
        assert data["total_score"] == 2.0
        assert data["obtained_score"] == 1.0
        assert data["submitted_at"] is not None

        first, second = data["answers"]
        assert first["correct_answer"] == "B"
        assert first["explanation"] == "解析 Q-1"
        assert first["score"] == 1.0
        assert first["knowledge_point_ids"] == ["ACC-01-01-01"]
        assert second["score"] == 0.0

        mastery = data["mastery"]
        assert mastery["by_kp"] == [{"kp_id": "ACC-01-01-01", "rate": 1.0},
                                    {"kp_id": "ACC-03-02-01", "rate": 0.0}]
        assert mastery["by_chapter"] == [{"chapter_id": "ACC-01", "rate": 1.0},
                                         {"chapter_id": "ACC-03", "rate": 0.0}]
        assert mastery["weak_kps"] == [{"kp_id": "ACC-03-02-01", "rate": 0.0}]

    def test_detail_subjective_fields(self, client, student_headers, fake_draw):
        """主观题详情带 materials/sub_questions，stem 为 null"""
        exam_id = _create(client, student_headers, fake_draw,
                          [make_question("J-1", question_type="计算")], {"计算": 1})
        data = client.get(f"/api/exams/{exam_id}", headers=student_headers).json()
        answer = data["answers"][0]
        assert answer["question_type"] == "计算"
        assert answer["stem"] is None
        assert answer["materials"] == "资料 J-1"
        assert answer["sub_questions"] == ["要求1", "要求2"]
        assert answer["full_score"] == 10.0

    def test_detail_other_user_403(self, client, student_headers, admin_headers, fake_draw):
        exam_id = _create(client, student_headers, fake_draw,
                          [make_question("Q-1")], {"单选": 1})
        assert client.get(f"/api/exams/{exam_id}",
                          headers=admin_headers).status_code == 403

    def test_detail_not_found_404(self, client, student_headers):
        assert client.get("/api/exams/999999",
                          headers=student_headers).status_code == 404


class TestExamList:
    """列表：倒序、只看自己的试卷"""

    def test_list_desc_order(self, client, student_headers, fake_draw):
        first = _create(client, student_headers, fake_draw,
                        [make_question("Q-1")], {"单选": 1})
        client.post(f"/api/exams/{first}/submit", headers=student_headers)
        second = _create(client, student_headers, fake_draw,
                         [make_question("Q-2"), make_question("Q-3")], {"单选": 2})

        items = client.get("/api/exams", headers=student_headers).json()
        assert [i["id"] for i in items] == [second, first]
        assert items[0]["status"] == "ongoing"
        assert items[0]["question_count"] == 2
        assert items[0]["obtained_score"] is None
        assert items[1]["status"] == "graded"
        assert items[1]["obtained_score"] == 0.0

    def test_list_isolated_by_user(self, client, student_headers, admin_headers, fake_draw):
        """只返回自己的试卷"""
        _create(client, student_headers, fake_draw, [make_question("Q-1")], {"单选": 1})
        assert client.get("/api/exams", headers=admin_headers).json() == []
