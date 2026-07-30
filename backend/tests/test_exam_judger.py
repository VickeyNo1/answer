# -*- coding: utf-8 -*-
"""判卷引擎测试：客观题判分规则 + 主观题 LLM 判卷（mock 大模型）"""
import pytest

from app.database import get_db_ctx
from app.exam import judger
from tests.conftest import make_question


class TestFullScores:
    def test_full_scores_fixed(self):
        """题型满分为 v4.0 固定值（设计 §4.2）"""
        assert judger.FULL_SCORES == {"单选": 1.0, "多选": 2.0, "计算": 10.0, "综合": 15.0}
        assert judger.is_objective("单选") and judger.is_objective("多选")
        assert not judger.is_objective("计算") and not judger.is_objective("综合")


class TestJudgeSingleChoice:
    def test_correct_gets_full(self):
        assert judger.judge_objective("单选", {"answer": "B"}, "B") == 1.0

    def test_wrong_gets_zero(self):
        assert judger.judge_objective("单选", {"answer": "B"}, "C") == 0.0

    def test_blank_gets_zero(self):
        assert judger.judge_objective("单选", {"answer": "B"}, None) == 0.0
        assert judger.judge_objective("单选", {"answer": "B"}, "  ") == 0.0

    def test_case_and_space_tolerant(self):
        """大小写与首尾空格不影响判分"""
        assert judger.judge_objective("单选", {"answer": "B"}, " b ") == 1.0

    def test_missing_reference_answer_zero(self):
        """快照缺参考答案时记 0（不误判满分）"""
        assert judger.judge_objective("单选", {}, "B") == 0.0


class TestJudgeMultiChoice:
    def test_exact_match_gets_full(self):
        assert judger.judge_objective("多选", {"answer": "ABD"}, "ABD") == 2.0

    def test_order_insensitive(self):
        assert judger.judge_objective("多选", {"answer": "ABD"}, "DBA") == 2.0

    def test_partial_gets_zero(self):
        """半对不给分（不做半对给分，避免规则争议）"""
        assert judger.judge_objective("多选", {"answer": "ABD"}, "AB") == 0.0

    def test_superset_gets_zero(self):
        assert judger.judge_objective("多选", {"answer": "ABD"}, "ABCD") == 0.0

    def test_blank_gets_zero(self):
        assert judger.judge_objective("多选", {"answer": "ABD"}, "") == 0.0


class TestJudgeUnknownType:
    def test_unknown_type_zero(self):
        """未登记题型满分为 0，不产生分数"""
        assert judger.judge_objective("填空", {"answer": "现金"}, "现金") == 0.0


class TestParseJudgeResult:
    def test_parse_with_surrounding_text(self):
        """模型带寒暄前后缀不影响 JSON 提取"""
        rate, reason = judger.parse_judge_result(
            '好的，判分结果如下：{"score_rate": 0.7, "reason": "分录方向错"} 以上。'
        )
        assert rate == 0.7
        assert reason == "分录方向错"

    def test_rate_clamped(self):
        """score_rate 越界钳到 [0, 1]"""
        assert judger.parse_judge_result('{"score_rate": 1.8}')[0] == 1.0
        assert judger.parse_judge_result('{"score_rate": -0.5}')[0] == 0.0

    def test_no_json_raises(self):
        with pytest.raises(ValueError):
            judger.parse_judge_result("我无法判分")

    def test_missing_rate_raises(self):
        with pytest.raises((TypeError, ValueError)):
            judger.parse_judge_result('{"reason": "很好"}')


class TestRoundHalfStep:
    def test_round_to_half(self):
        """四舍五入到 0.5（非银行家舍入）"""
        assert judger.round_half_step(6.6) == 6.5
        assert judger.round_half_step(6.8) == 7.0
        assert judger.round_half_step(0.25) == 0.5
        assert judger.round_half_step(10.0) == 10.0


# ========== 主观题 LLM 判卷（需数据库） ==========

JUDGE_OK = ('{"score_rate": 0.7, "reason": "思路正确，分录遗漏一项"}', 120, 40)


def _exam_row(exam_id):
    with get_db_ctx() as db:
        cursor = db.execute(
            "SELECT status, obtained_score FROM exams WHERE id = %s", (exam_id,)
        )
        return cursor.fetchone()


def _answer_row(exam_id, seq):
    with get_db_ctx() as db:
        cursor = db.execute(
            "SELECT score, llm_reason FROM exam_answers WHERE exam_id = %s AND seq = %s",
            (exam_id, seq),
        )
        return cursor.fetchone()


def _exam_usage_rows():
    with get_db_ctx() as db:
        cursor = db.execute(
            """SELECT user_id, conversation_id, total_tokens FROM usage_logs
               WHERE task_type = 'exam' ORDER BY id ASC"""
        )
        return list(cursor.fetchall())


def _submitted_exam(client, headers, fake_draw, subjective_answer="借：固定资产 100"):
    """造一张 1 单选 + 1 计算的试卷并交卷（交卷后 status='grading'）"""
    fake_draw([make_question("Q-1", answer="B"),
               make_question("J-1", question_type="计算", answer="参考答案文本")])
    exam_id = client.post("/api/exams", json={"counts": {"单选": 1, "计算": 1}},
                          headers=headers).json()["id"]
    client.put(f"/api/exams/{exam_id}/answers",
               json={"answers": [{"seq": 1, "content": "B"},
                                 {"seq": 2, "content": subjective_answer}]},
               headers=headers)
    client.post(f"/api/exams/{exam_id}/submit", headers=headers)
    return exam_id


@pytest.mark.usefixtures("clean_exams")
class TestGradeExam:
    """后台判卷主流程（测试里同步调 grade_exam，不走线程池）"""

    def test_submit_schedules_bg_grading(self, client, student_headers, fake_draw,
                                        bg_grading_calls):
        """含主观题交卷后提交后台判卷任务"""
        exam_id = _submitted_exam(client, student_headers, fake_draw)
        assert bg_grading_calls == [exam_id]
        assert _exam_row(exam_id)["status"] == "grading"

    def test_grade_success(self, client, student_headers, fake_draw, fake_llm):
        prompts = fake_llm([JUDGE_OK])
        exam_id = _submitted_exam(client, student_headers, fake_draw)
        judger.grade_exam(exam_id)

        row = _answer_row(exam_id, 2)
        assert float(row["score"]) == 7.0            # 10 分 × 0.7
        assert row["llm_reason"] == "思路正确，分录遗漏一项"
        exam = _exam_row(exam_id)
        assert exam["status"] == "graded"
        assert float(exam["obtained_score"]) == 8.0  # 客观 1 + 主观 7

        # 判卷 prompt 包含参考答案/解析/资料/学生作答，且只判主观题（调 1 次）
        assert len(prompts) == 1
        for fragment in ("参考答案文本", "解析 J-1", "资料 J-1", "借：固定资产 100"):
            assert fragment in prompts[0]

    def test_score_rounded_to_half(self, client, student_headers, fake_draw, fake_llm):
        """得分四舍五入到 0.5（10 × 0.66 = 6.6 → 6.5）"""
        fake_llm([('{"score_rate": 0.66, "reason": "部分正确"}', 100, 20)])
        exam_id = _submitted_exam(client, student_headers, fake_draw)
        judger.grade_exam(exam_id)
        assert float(_answer_row(exam_id, 2)["score"]) == 6.5

    def test_retry_then_success(self, client, student_headers, fake_draw, fake_llm):
        """单题失败重试 1 次，第二次成功则正常计分"""
        prompts = fake_llm([RuntimeError("调用超时"),
                            ('{"score_rate": 1, "reason": "完全正确"}', 100, 20)])
        exam_id = _submitted_exam(client, student_headers, fake_draw)
        judger.grade_exam(exam_id)
        assert len(prompts) == 2
        assert float(_answer_row(exam_id, 2)["score"]) == 10.0
        assert _exam_row(exam_id)["status"] == "graded"

    def test_two_failures_records_null(self, client, student_headers, fake_draw, fake_llm):
        """两次都失败：score 记 NULL、理由标判卷失败，试卷仍置 graded 且该题按 0 分计"""
        prompts = fake_llm([RuntimeError("模型调用失败: 500 - boom")])
        exam_id = _submitted_exam(client, student_headers, fake_draw)
        judger.grade_exam(exam_id)

        assert len(prompts) == 2
        row = _answer_row(exam_id, 2)
        assert row["score"] is None
        assert row["llm_reason"].startswith(judger.JUDGE_FAIL_PREFIX)
        exam = _exam_row(exam_id)
        assert exam["status"] == "graded"
        assert float(exam["obtained_score"]) == 1.0  # 仅客观题得分

    def test_unparsable_reply_records_null(self, client, student_headers, fake_draw, fake_llm):
        """模型返回非 JSON 也走重试，仍失败则记 NULL"""
        fake_llm([("我无法对这道题打分", 80, 10)])
        exam_id = _submitted_exam(client, student_headers, fake_draw)
        judger.grade_exam(exam_id)
        assert _answer_row(exam_id, 2)["score"] is None

    def test_usage_recorded_as_exam(self, client, student_headers, fake_draw, fake_llm):
        """判卷 token 按 task_type='exam' 记账，conversation_id 为空"""
        before = len(_exam_usage_rows())
        fake_llm([JUDGE_OK])
        exam_id = _submitted_exam(client, student_headers, fake_draw)
        judger.grade_exam(exam_id)

        rows = _exam_usage_rows()
        assert len(rows) == before + 1
        latest = rows[-1]
        assert latest["user_id"] == 2
        assert latest["conversation_id"] is None
        assert latest["total_tokens"] == 160

    def test_skip_when_not_grading(self, client, student_headers, fake_draw, fake_llm):
        """未交卷（ongoing）的试卷不判卷"""
        prompts = fake_llm([JUDGE_OK])
        fake_draw([make_question("J-1", question_type="计算")])
        exam_id = client.post("/api/exams", json={"counts": {"计算": 1}},
                              headers=student_headers).json()["id"]
        judger.grade_exam(exam_id)
        assert prompts == []
        assert _exam_row(exam_id)["status"] == "ongoing"

    def test_detail_reveals_reason_and_mastery(self, client, student_headers,
                                               fake_draw, fake_llm):
        """判卷完成后详情才展示判分理由与掌握度"""
        fake_llm([JUDGE_OK])
        exam_id = _submitted_exam(client, student_headers, fake_draw)

        data = client.get(f"/api/exams/{exam_id}", headers=student_headers).json()
        assert data["status"] == "grading"
        assert data["mastery"] is None
        assert data["answers"][1]["llm_reason"] is None

        judger.grade_exam(exam_id)
        data = client.get(f"/api/exams/{exam_id}", headers=student_headers).json()
        assert data["status"] == "graded"
        assert data["answers"][1]["llm_reason"] == "思路正确，分录遗漏一项"
        # 两题同一知识点：(1 + 7) / (1 + 10) = 0.7273
        assert data["mastery"]["by_kp"] == [{"kp_id": "ACC-01-03-01", "rate": 0.7273}]

