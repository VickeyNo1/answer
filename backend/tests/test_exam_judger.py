# -*- coding: utf-8 -*-
"""判卷引擎单元测试：客观题判分规则（主观题 LLM 判卷见 B3 批次）"""
from app.exam import judger


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
