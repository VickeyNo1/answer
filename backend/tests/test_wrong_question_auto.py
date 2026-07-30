# -*- coding: utf-8 -*-
"""错题自动入本测试：交卷判卷后错题自动入本（设计 §5.2）

覆盖路径：
1. 有主观题 → grade_exam 完成后入本
2. 纯客观题 → submit_exam 即 graded 时入本
"""
import pytest

from app.database import get_db_ctx
from app.exam import judger
from tests.conftest import make_question


pytestmark = pytest.mark.usefixtures("clean_profile", "clean_exams")

JUDGE_OK = ('{"score_rate": 0.7, "reason": "部分正确"}', 120, 40)
JUDGE_FULL = ('{"score_rate": 1.0, "reason": "完全正确"}', 100, 20)


def _wrong_questions(user_id=2):
    """查询 wrong_questions 表"""
    with get_db_ctx() as db:
        cursor = db.execute(
            "SELECT question_id, wrong_count, mastered, my_answer, source_exam_id "
            "FROM wrong_questions WHERE user_id = %s ORDER BY question_id",
            (user_id,),
        )
        return list(cursor.fetchall())


def _submitted_exam(client, headers, fake_draw, questions, counts, answers):
    """造试卷 + 暂存 + 交卷，返回 exam_id"""
    fake_draw(questions)
    exam_id = client.post("/api/exams", json={"counts": counts},
                          headers=headers).json()["id"]
    client.put(f"/api/exams/{exam_id}/answers",
               json={"answers": answers}, headers=headers)
    client.post(f"/api/exams/{exam_id}/submit", headers=headers)
    return exam_id


class TestWrongQuestionAutoEntry:
    """判卷完成后错题自动入本（有主观题路径）"""

    def test_objective_wrong_enters(self, client, student_headers, fake_draw, fake_llm):
        """客观题答错 → 自动入本"""
        questions = [
            make_question("Q-1", answer="B"),
            make_question("J-1", question_type="计算", answer="参考答案"),
        ]
        answers = [
            {"seq": 1, "content": "C"},  # 错（答案是 B）
            {"seq": 2, "content": "完整作答"},
        ]
        fake_llm([JUDGE_FULL])  # 主观题满分
        exam_id = _submitted_exam(client, student_headers, fake_draw,
                                   questions, {"单选": 1, "计算": 1}, answers)
        judger.grade_exam(exam_id)

        wqs = _wrong_questions()
        assert len(wqs) == 1
        assert wqs[0]["question_id"] == "Q-1"
        assert int(wqs[0]["wrong_count"]) == 1
        assert int(wqs[0]["mastered"]) == 0
        assert wqs[0]["my_answer"] == "C"
        assert wqs[0]["source_exam_id"] == exam_id

    def test_subjective_low_score_enters(self, client, student_headers, fake_draw, fake_llm):
        """主观题低分（score < full_score）→ 自动入本"""
        questions = [
            make_question("Q-1", answer="B"),
            make_question("J-1", question_type="计算", answer="参考答案"),
        ]
        answers = [
            {"seq": 1, "content": "B"},  # 对
            {"seq": 2, "content": "部分作答"},
        ]
        fake_llm([JUDGE_OK])  # 0.7 → 7.0 < 10.0
        exam_id = _submitted_exam(client, student_headers, fake_draw,
                                   questions, {"单选": 1, "计算": 1}, answers)
        judger.grade_exam(exam_id)

        wqs = _wrong_questions()
        assert len(wqs) == 1
        assert wqs[0]["question_id"] == "J-1"

    def test_all_correct_no_entry(self, client, student_headers, fake_draw, fake_llm):
        """全对 → 不入本"""
        questions = [
            make_question("Q-1", answer="B"),
            make_question("J-1", question_type="计算", answer="参考答案"),
        ]
        answers = [
            {"seq": 1, "content": "B"},  # 对
            {"seq": 2, "content": "完整作答"},
        ]
        fake_llm([JUDGE_FULL])  # 主观题满分
        exam_id = _submitted_exam(client, student_headers, fake_draw,
                                   questions, {"单选": 1, "计算": 1}, answers)
        judger.grade_exam(exam_id)

        wqs = _wrong_questions()
        assert len(wqs) == 0

    def test_subjective_null_score_enters(self, client, student_headers, fake_draw, fake_llm):
        """主观题判卷失败 score=NULL → 自动入本"""
        questions = [
            make_question("Q-1", answer="B"),
            make_question("J-1", question_type="计算", answer="参考答案"),
        ]
        answers = [
            {"seq": 1, "content": "B"},  # 对
            {"seq": 2, "content": "作答"},
        ]
        fake_llm([RuntimeError("模型调用失败")])
        exam_id = _submitted_exam(client, student_headers, fake_draw,
                                   questions, {"单选": 1, "计算": 1}, answers)
        judger.grade_exam(exam_id)

        wqs = _wrong_questions()
        assert len(wqs) == 1
        assert wqs[0]["question_id"] == "J-1"

    def test_mixed_wrong_enters_both(self, client, student_headers, fake_draw, fake_llm):
        """客观题错 + 主观题低分 → 两题都入本"""
        questions = [
            make_question("Q-1", answer="B"),
            make_question("J-1", question_type="计算", answer="参考答案"),
        ]
        answers = [
            {"seq": 1, "content": "C"},  # 错
            {"seq": 2, "content": "部分作答"},
        ]
        fake_llm([JUDGE_OK])  # 0.7 → 7.0 < 10.0
        exam_id = _submitted_exam(client, student_headers, fake_draw,
                                   questions, {"单选": 1, "计算": 1}, answers)
        judger.grade_exam(exam_id)

        wqs = _wrong_questions()
        assert len(wqs) == 2
        qids = {w["question_id"] for w in wqs}
        assert qids == {"Q-1", "J-1"}


class TestPureObjectiveAutoEntry:
    """纯客观题交卷即 graded，错题自动入本（不走 grade_exam）"""

    def test_pure_objective_wrong_enters(self, client, student_headers, fake_draw):
        """纯客观题交卷 → 错题自动入本（submit_exam 路径）"""
        questions = [
            make_question("Q-1", answer="B"),
            make_question("Q-2", answer="A"),
        ]
        answers = [
            {"seq": 1, "content": "C"},  # 错
            {"seq": 2, "content": "A"},  # 对
        ]
        exam_id = _submitted_exam(client, student_headers, fake_draw,
                                   questions, {"单选": 2}, answers)
        # 纯客观题：submit 时即 graded，不调 grade_exam
        wqs = _wrong_questions()
        assert len(wqs) == 1
        assert wqs[0]["question_id"] == "Q-1"
        assert wqs[0]["my_answer"] == "C"
        assert wqs[0]["source_exam_id"] == exam_id

    def test_pure_objective_all_correct_no_entry(self, client, student_headers, fake_draw):
        """纯客观题全对 → 不入本"""
        questions = [
            make_question("Q-1", answer="B"),
            make_question("Q-2", answer="A"),
        ]
        answers = [
            {"seq": 1, "content": "B"},  # 对
            {"seq": 2, "content": "A"},  # 对
        ]
        _submitted_exam(client, student_headers, fake_draw,
                        questions, {"单选": 2}, answers)
        wqs = _wrong_questions()
        assert len(wqs) == 0
