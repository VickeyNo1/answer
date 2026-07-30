# -*- coding: utf-8 -*-
"""掌握度归因算式单元测试（设计 §4.5）"""
from app.exam.store import chapter_of, compute_mastery


def _answer(kp_ids, score, full_score):
    return {"knowledge_point_ids": kp_ids, "score": score, "full_score": full_score}


class TestChapterOf:
    def test_prefix_two_segments(self):
        assert chapter_of("ACC-03-02-01") == "ACC-03"

    def test_short_id_unchanged(self):
        assert chapter_of("ACC") == "ACC"
        assert chapter_of("ACC-03") == "ACC-03"


class TestComputeMastery:
    def test_multi_kp_not_split(self):
        """一题多知识点：该题得分/满分同时全额计入每个知识点（不摊分）"""
        result = compute_mastery([
            _answer(["ACC-01-01-01", "ACC-01-02-01"], 1.0, 1.0),
            _answer(["ACC-01-01-01"], 0.0, 2.0),
        ])
        assert result["by_kp"] == [
            {"kp_id": "ACC-01-01-01", "rate": round(1 / 3, 4)},  # 1/(1+2)
            {"kp_id": "ACC-01-02-01", "rate": 1.0},
        ]

    def test_chapter_weighted_by_full_score(self):
        """章节掌握度按关联题满分加权（不是知识点掌握度的算术平均）"""
        result = compute_mastery([
            _answer(["ACC-01-01-01", "ACC-01-02-01"], 1.0, 1.0),
            _answer(["ACC-01-01-01"], 0.0, 2.0),
            _answer(["ACC-03-01-01"], 5.0, 10.0),
        ])
        # ACC-01：得分 1+1=2，满分 3+1=4 → 0.5（算术平均会是 0.6667）
        assert result["by_chapter"] == [
            {"chapter_id": "ACC-01", "rate": 0.5},
            {"chapter_id": "ACC-03", "rate": 0.5},
        ]

    def test_weak_kps_sorted_asc(self):
        """薄弱知识点 = 掌握度 < 0.6，按掌握度升序"""
        result = compute_mastery([
            _answer(["KP-A"], 0.0, 1.0),    # 0.0
            _answer(["KP-B"], 5.0, 10.0),   # 0.5
            _answer(["KP-C"], 1.0, 1.0),    # 1.0
            _answer(["KP-D"], 6.0, 10.0),   # 0.6 → 不算薄弱（严格小于）
        ])
        assert result["weak_kps"] == [
            {"kp_id": "KP-A", "rate": 0.0},
            {"kp_id": "KP-B", "rate": 0.5},
        ]

    def test_null_score_counts_as_zero(self):
        """判卷失败（score=NULL）按 0 分计入"""
        result = compute_mastery([_answer(["KP-A"], None, 10.0)])
        assert result["by_kp"] == [{"kp_id": "KP-A", "rate": 0.0}]

    def test_no_kp_ids_ignored(self):
        """无知识点标注的题不进入归因"""
        result = compute_mastery([_answer([], 1.0, 1.0), _answer(["KP-A"], 1.0, 1.0)])
        assert result["by_kp"] == [{"kp_id": "KP-A", "rate": 1.0}]

    def test_empty_returns_empty(self):
        assert compute_mastery([]) == {"by_kp": [], "by_chapter": [], "weak_kps": []}
