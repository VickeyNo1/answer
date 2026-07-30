# -*- coding: utf-8 -*-
"""管理端考试接口测试：列表筛选分页 / 详情（grading 可见）/ 复核改分"""
import pytest

from app.database import get_db_ctx
from tests.conftest import make_question

pytestmark = pytest.mark.usefixtures("clean_exams")


def _graded_exam(client, headers, fake_draw):
    """造一张纯客观题已判卷试卷：2 单选 + 1 多选，全答对 → obtained=4"""
    fake_draw([
        make_question("Q-1", answer="B"),
        make_question("Q-2", answer="A"),
        make_question("Q-3", question_type="多选", answer="ABC"),
    ])
    exam_id = client.post("/api/exams", json={"counts": {"单选": 2, "多选": 1}},
                          headers=headers).json()["id"]
    client.put(f"/api/exams/{exam_id}/answers",
               json={"answers": [{"seq": 1, "content": "B"},
                                 {"seq": 2, "content": "A"},
                                 {"seq": 3, "content": "ABC"}]},
               headers=headers)
    client.post(f"/api/exams/{exam_id}/submit", headers=headers)
    return exam_id


def _grading_exam(client, headers, fake_draw):
    """造一张含主观题的 grading 试卷（交卷后停在 grading）"""
    fake_draw([make_question("Q-1", answer="B"),
               make_question("J-1", question_type="计算", answer="参考答案")])
    exam_id = client.post("/api/exams", json={"counts": {"单选": 1, "计算": 1}},
                          headers=headers).json()["id"]
    client.put(f"/api/exams/{exam_id}/answers",
               json={"answers": [{"seq": 1, "content": "B"},
                                 {"seq": 2, "content": "我的解答"}]},
               headers=headers)
    client.post(f"/api/exams/{exam_id}/submit", headers=headers)
    return exam_id


class TestAdminExamList:
    """GET /api/admin/exams：筛选 + 分页 + 权限"""

    def test_list_empty(self, client, admin_headers):
        resp = client.get("/api/admin/exams", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == {"total": 0, "items": []}

    def test_list_contains_student_info(self, client, admin_headers,
                                        student_headers, fake_draw):
        _graded_exam(client, student_headers, fake_draw)
        resp = client.get("/api/admin/exams", headers=admin_headers)
        data = resp.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["student_id"] == "2024001"
        assert item["student_name"] == "测试学生"
        assert item["status"] == "graded"
        assert float(item["obtained_score"]) == 4.0

    def test_list_filter_by_student_id(self, client, admin_headers,
                                       student_headers, fake_draw):
        _graded_exam(client, student_headers, fake_draw)
        resp = client.get("/api/admin/exams?student_id=2024001",
                          headers=admin_headers)
        assert resp.json()["total"] == 1
        resp = client.get("/api/admin/exams?student_id=9999",
                          headers=admin_headers)
        assert resp.json()["total"] == 0

    def test_list_pagination(self, client, admin_headers, student_headers, fake_draw):
        for i in range(3):
            _graded_exam(client, student_headers, fake_draw)
        resp = client.get("/api/admin/exams?page=1&page_size=2",
                          headers=admin_headers)
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 2
        # 倒序：最新的在前
        assert data["items"][0]["id"] > data["items"][1]["id"]

        resp = client.get("/api/admin/exams?page=2&page_size=2",
                          headers=admin_headers)
        assert len(resp.json()["items"]) == 1

    def test_list_not_admin_403(self, client, student_headers):
        resp = client.get("/api/admin/exams", headers=student_headers)
        assert resp.status_code == 403


class TestAdminExamDetail:
    """GET /api/admin/exams/{id}：grading 中也展示参考答案"""

    def test_detail_reveals_grading(self, client, admin_headers,
                                    student_headers, fake_draw):
        """管理端在 grading 中就能看参考答案（学生端看不到）"""
        exam_id = _grading_exam(client, student_headers, fake_draw)
        resp = client.get(f"/api/admin/exams/{exam_id}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "grading"
        # 参考答案可见（管理端 reveal=True）
        assert data["answers"][0]["correct_answer"] == "B"
        assert data["answers"][1]["correct_answer"] == "参考答案"
        # grading 中 mastery 为 None（判卷未完成）
        assert data["mastery"] is None

        # 对照：学生端 grading 时看不到参考答案
        student = client.get(f"/api/exams/{exam_id}",
                             headers=student_headers).json()
        assert student["answers"][0]["correct_answer"] is None

    def test_detail_not_found_404(self, client, admin_headers):
        resp = client.get("/api/admin/exams/9999", headers=admin_headers)
        assert resp.status_code == 404

    def test_detail_not_admin_403(self, client, student_headers, fake_draw):
        exam_id = _graded_exam(client, student_headers, fake_draw)
        resp = client.get(f"/api/admin/exams/{exam_id}", headers=student_headers)
        assert resp.status_code == 403


class TestAdminUpdateScore:
    """PUT /api/admin/exams/{id}/answers/{seq}/score：改分 + 重算总分"""

    def test_update_score_ok(self, client, admin_headers, student_headers, fake_draw):
        exam_id = _graded_exam(client, student_headers, fake_draw)
        # 改 seq=3（多选，满分 2，原得 2）为 1 分
        resp = client.put(f"/api/admin/exams/{exam_id}/answers/3/score",
                          json={"score": 1, "reason": "多选漏选一题"},
                          headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["seq"] == 3
        assert float(data["score"]) == 1.0
        assert data["llm_reason"] == "多选漏选一题"
        # 总分重算：1+1+1 = 3
        assert float(data["obtained_score"]) == 3.0

        # 详情中确认改分生效
        detail = client.get(f"/api/admin/exams/{exam_id}",
                            headers=admin_headers).json()
        assert float(detail["answers"][2]["score"]) == 1.0
        assert float(detail["obtained_score"]) == 3.0

    def test_update_score_to_zero(self, client, admin_headers,
                                  student_headers, fake_draw):
        exam_id = _graded_exam(client, student_headers, fake_draw)
        resp = client.put(f"/api/admin/exams/{exam_id}/answers/1/score",
                          json={"score": 0}, headers=admin_headers)
        assert resp.status_code == 200
        assert float(resp.json()["obtained_score"]) == 3.0  # 0+1+2

    def test_update_score_above_full_400(self, client, admin_headers,
                                         student_headers, fake_draw):
        exam_id = _graded_exam(client, student_headers, fake_draw)
        resp = client.put(f"/api/admin/exams/{exam_id}/answers/1/score",
                          json={"score": 2}, headers=admin_headers)
        assert resp.status_code == 400

    def test_update_score_negative_400(self, client, admin_headers,
                                       student_headers, fake_draw):
        exam_id = _graded_exam(client, student_headers, fake_draw)
        resp = client.put(f"/api/admin/exams/{exam_id}/answers/1/score",
                          json={"score": -0.5}, headers=admin_headers)
        assert resp.status_code == 400

    def test_update_score_seq_not_found_404(self, client, admin_headers,
                                            student_headers, fake_draw):
        exam_id = _graded_exam(client, student_headers, fake_draw)
        resp = client.put(f"/api/admin/exams/{exam_id}/answers/99/score",
                          json={"score": 1}, headers=admin_headers)
        assert resp.status_code == 404

    def test_update_score_exam_not_found_404(self, client, admin_headers):
        resp = client.put("/api/admin/exams/9999/answers/1/score",
                          json={"score": 1}, headers=admin_headers)
        assert resp.status_code == 404

    def test_update_score_not_admin_403(self, client, student_headers, fake_draw):
        exam_id = _graded_exam(client, student_headers, fake_draw)
        resp = client.put(f"/api/admin/exams/{exam_id}/answers/1/score",
                          json={"score": 1}, headers=student_headers)
        assert resp.status_code == 403
