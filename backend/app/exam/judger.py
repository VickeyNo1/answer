"""判卷引擎（设计 §4.3）：题型满分常量 + 客观题程序判分

主观题 LLM 异步判卷在 B3 批次实现（本文件内 grade_subjective_async）。
判分依据一律读 question_snapshot，不回查知识库（防改题错位）。
"""
import logging

logger = logging.getLogger(__name__)

# 题型满分（v4.0 固定值，设计 §4.2）
FULL_SCORES: dict[str, float] = {
    "单选": 1.0,
    "多选": 2.0,
    "计算": 10.0,
    "综合": 15.0,
}

OBJECTIVE_TYPES = ("单选", "多选")
SUBJECTIVE_TYPES = ("计算", "综合")


def is_objective(question_type: str) -> bool:
    return question_type in OBJECTIVE_TYPES


def judge_objective(question_type: str, snapshot: dict,
                    student_answer: str | None) -> float:
    """客观题即时判分：单选全等得满分；多选选项集合完全一致得满分，否则 0（不做半对给分）"""
    full = FULL_SCORES.get(question_type, 0.0)
    correct = (snapshot.get("answer") or "").strip().upper()
    mine = (student_answer or "").strip().upper()
    if not mine or not correct:
        return 0.0
    if question_type == "多选":
        return full if set(mine) == set(correct) else 0.0
    return full if mine == correct else 0.0
