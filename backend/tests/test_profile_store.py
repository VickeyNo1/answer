# -*- coding: utf-8 -*-
"""学生记忆 store 单测：错题本 UPSERT/重练/薄弱点聚合/记忆注入（设计 §5.1-5.4）"""
import json
import pytest

from app.database import get_db_ctx
from app.profile import store as profile_store
from tests.conftest import make_question, make_wrong_question

pytestmark = pytest.mark.usefixtures("clean_profile", "clean_exams")


def _insert_exam_with_answers(user_id, subject="cpa_acc", answers_data=None):
    """造一张 graded 试卷 + 答题数据（用于薄弱点聚合测试）"""
    with get_db_ctx() as db:
        cursor = db.execute(
            "INSERT INTO exams (user_id, subject, status, question_count, total_score, obtained_score, submitted_at) "
            "VALUES (%s, %s, 'graded', %s, %s, %s, NOW())",
            (user_id, subject, len(answers_data or []),
             sum(a["full"] for a in (answers_data or [])),
             sum(a.get("score", 0) or 0 for a in (answers_data or []))),
        )
        exam_id = cursor.lastrowid
        for i, a in enumerate(answers_data or [], 1):
            snap = json.dumps(a.get("snap", {}), ensure_ascii=False)
            db.execute(
                "INSERT INTO exam_answers (exam_id, seq, question_id, question_type, question_snapshot, full_score, score) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (exam_id, i, a.get("qid", f"Q-{i}"), a.get("qtype", "单选"),
                 snap, a["full"], a.get("score")),
            )
        db.commit()
        return exam_id


class TestUpsertWrongQuestion:
    def test_first_insert(self):
        """首次入本：wrong_count=1, mastered=0"""
        snap = json.dumps(make_question("Q-001", answer="B"), ensure_ascii=False)
        with get_db_ctx() as db:
            profile_store.upsert_wrong_question(db, 2, "cpa_acc", "Q-001", snap, "C", None)
            cursor = db.execute("SELECT wrong_count, mastered, my_answer FROM wrong_questions WHERE user_id=2")
            row = cursor.fetchone()
        assert int(row["wrong_count"]) == 1
        assert int(row["mastered"]) == 0
        assert row["my_answer"] == "C"

    def test_duplicate_increments(self):
        """重复错同题：wrong_count+1, mastered 重置 0, my_answer 刷新"""
        snap = json.dumps(make_question("Q-001", answer="B"), ensure_ascii=False)
        with get_db_ctx() as db:
            profile_store.upsert_wrong_question(db, 2, "cpa_acc", "Q-001", snap, "C", 1)
            profile_store.upsert_wrong_question(db, 2, "cpa_acc", "Q-001", snap, "D", 2)
            cursor = db.execute("SELECT wrong_count, mastered, my_answer, source_exam_id FROM wrong_questions WHERE user_id=2")
            row = cursor.fetchone()
        assert int(row["wrong_count"]) == 2
        assert int(row["mastered"]) == 0
        assert row["my_answer"] == "D"
        assert int(row["source_exam_id"]) == 2

    def test_different_questions_separate(self):
        """不同题目各自独立"""
        snap1 = json.dumps(make_question("Q-001"), ensure_ascii=False)
        snap2 = json.dumps(make_question("Q-002"), ensure_ascii=False)
        with get_db_ctx() as db:
            profile_store.upsert_wrong_question(db, 2, "cpa_acc", "Q-001", snap1, "C", None)
            profile_store.upsert_wrong_question(db, 2, "cpa_acc", "Q-002", snap2, "A", None)
            cursor = db.execute("SELECT COUNT(*) AS cnt FROM wrong_questions WHERE user_id=2")
            assert int(cursor.fetchone()["cnt"]) == 2


class TestRetryObjective:
    def test_correct_sets_mastered(self):
        """客观题答对→mastered=1"""
        wq_id = make_wrong_question(2, "Q-001", question_type="单选", answer="B", my_answer="C")
        with get_db_ctx() as db:
            result = profile_store.retry_wrong_question(db, wq_id, 2, "B")
        assert result["correct"] is True
        assert result["correct_answer"] == "B"
        assert result["mastered"] == 1

    def test_wrong_increments(self):
        """客观题答错→wrong_count+1"""
        wq_id = make_wrong_question(2, "Q-001", question_type="单选", answer="B",
                                    my_answer="C", wrong_count=1)
        with get_db_ctx() as db:
            result = profile_store.retry_wrong_question(db, wq_id, 2, "D")
            assert result["correct"] is False
            assert result["mastered"] == 0
            cursor = db.execute("SELECT wrong_count FROM wrong_questions WHERE id=%s", (wq_id,))
            assert int(cursor.fetchone()["wrong_count"]) == 2

    def test_multi_choice_correct(self):
        """多选全对→mastered=1"""
        wq_id = make_wrong_question(2, "Q-001", question_type="多选", answer="ABD", my_answer="AB")
        with get_db_ctx() as db:
            result = profile_store.retry_wrong_question(db, wq_id, 2, "DBA")
        assert result["correct"] is True
        assert result["mastered"] == 1

    def test_not_found(self):
        with get_db_ctx() as db:
            result = profile_store.retry_wrong_question(db, 99999, 2, "B")
        assert result is None


class TestRetrySubjective:
    def test_correct_above_threshold(self, fake_llm):
        """主观题 score_rate>=0.6→答对"""
        wq_id = make_wrong_question(2, "J-001", question_type="计算", answer="参考答案", my_answer="错误答案")
        fake_llm([('{"score_rate": 0.8, "reason": "思路正确"}', 100, 50)])
        with get_db_ctx() as db:
            result = profile_store.retry_wrong_question(db, wq_id, 2, "较好的答案")
        assert result["correct"] is True
        assert result["mastered"] == 1

    def test_wrong_below_threshold(self, fake_llm):
        """主观题 score_rate<0.6→答错"""
        wq_id = make_wrong_question(2, "J-001", question_type="计算", answer="参考答案", my_answer="错误答案")
        fake_llm([('{"score_rate": 0.3, "reason": "方向错误"}', 100, 50)])
        with get_db_ctx() as db:
            result = profile_store.retry_wrong_question(db, wq_id, 2, "不太对的答案")
        assert result["correct"] is False
        assert result["mastered"] == 0


class TestComputeWeakKps:
    def test_exam_only(self):
        """仅考试来源的薄弱知识点"""
        snap1 = make_question("Q-1", kp_ids=["ACC-01-01-01"])
        snap2 = make_question("Q-2", kp_ids=["ACC-01-02-01"])
        _insert_exam_with_answers(2, answers_data=[
            {"qid": "Q-1", "qtype": "单选", "snap": snap1, "full": 1.0, "score": 0.0},
            {"qid": "Q-2", "qtype": "单选", "snap": snap2, "full": 1.0, "score": 1.0},
        ])
        with get_db_ctx() as db:
            result = profile_store.compute_weak_kps(db, 2)
        # ACC-01-01-01: rate=0.0 (错), ACC-01-02-01: rate=1.0 (对，不进薄弱)
        assert len(result) == 1
        assert result[0]["kp_id"] == "ACC-01-01-01"
        assert result[0]["rate"] == 0.0
        assert result[0]["wrong_count"] == 1

    def test_merge_feedback_down(self):
        """点踩消息的 kp_ids 补充进薄弱"""
        snap = make_question("Q-1", kp_ids=["ACC-01-01-01"])
        _insert_exam_with_answers(2, answers_data=[
            {"qid": "Q-1", "qtype": "单选", "snap": snap, "full": 1.0, "score": 0.0},
        ])
        # 造一条点踩消息带 kp_ids
        with get_db_ctx() as db:
            cursor = db.execute(
                "INSERT INTO conversations (user_id, title, subject) VALUES (2, 'test', 'cpa_acc')"
            )
            conv_id = cursor.lastrowid
            msg_cursor = db.execute(
                "INSERT INTO messages (conversation_id, role, content, knowledge_point_ids) "
                "VALUES (%s, 'assistant', 'AI回答', %s)",
                (conv_id, json.dumps(["ACC-03-01-01"], ensure_ascii=False)),
            )
            msg_id = msg_cursor.lastrowid
            db.execute(
                "INSERT INTO feedbacks (message_id, user_id, rating, reason) VALUES (%s, 2, 'down', '不对')",
                (msg_id,),
            )
            db.commit()
        with get_db_ctx() as db:
            result = profile_store.compute_weak_kps(db, 2)
        kp_ids = [r["kp_id"] for r in result]
        assert "ACC-01-01-01" in kp_ids  # 考试来源
        assert "ACC-03-01-01" in kp_ids  # 点踩来源

    def test_top5_limit(self):
        """最多返回 5 条"""
        snaps = [make_question(f"Q-{i}", kp_ids=[f"KP-{i:02d}"]) for i in range(7)]
        _insert_exam_with_answers(2, answers_data=[
            {"qid": f"Q-{i}", "snap": snaps[i], "full": 1.0, "score": 0.0} for i in range(7)
        ])
        with get_db_ctx() as db:
            result = profile_store.compute_weak_kps(db, 2)
        assert len(result) <= 5


class TestBuildMemoryBlock:
    def test_all_empty_returns_none(self):
        """三项全空→None"""
        with get_db_ctx() as db:
            result = profile_store.build_memory_block(db, 2, {"id": 2, "memory_enabled": None})
        assert result is None

    def test_switch_off_returns_none(self):
        """记忆开关关→None（即使有数据）"""
        snap = make_question("Q-1", kp_ids=["ACC-01-01-01"])
        _insert_exam_with_answers(2, answers_data=[
            {"qid": "Q-1", "snap": snap, "full": 1.0, "score": 0.0},
        ])
        with get_db_ctx() as db:
            result = profile_store.build_memory_block(db, 2, {"id": 2, "memory_enabled": 0})
        assert result is None

    def test_normal_assembly(self):
        """正常拼接记忆块"""
        snap = make_question("Q-1", kp_ids=["ACC-01-01-01"])
        _insert_exam_with_answers(2, answers_data=[
            {"qid": "Q-1", "snap": snap, "full": 1.0, "score": 0.0},
        ])
        with get_db_ctx() as db:
            profile_store.upsert_profile(db, 2, "偏好分录示例讲解，概念辨析题易错。")
            result = profile_store.build_memory_block(db, 2, {"id": 2, "memory_enabled": None})
        assert result is not None
        assert "【学生情况】" in result
        assert "薄弱知识点" in result
        assert "学习风格" in result
        assert "最近考试" in result


class TestIncrementDialogCount:
    def test_creates_row_if_missing(self):
        """无行时自动创建并计数 1"""
        with get_db_ctx() as db:
            count = profile_store.increment_dialog_count(db, 2)
        assert count == 1

    def test_increments_existing(self):
        """已有行时 +1"""
        with get_db_ctx() as db:
            profile_store.increment_dialog_count(db, 2)
            profile_store.increment_dialog_count(db, 2)
            count = profile_store.increment_dialog_count(db, 2)
        assert count == 3


class TestUpsertProfile:
    def test_truncates_to_200_chars(self):
        """画像文本截断到 200 字符"""
        long_text = "画像" * 200  # 400 字符
        with get_db_ctx() as db:
            profile_store.upsert_profile(db, 2, long_text)
            row = profile_store.get_profile(db, 2)
        assert len(row["style_profile"]) == 200

    def test_overwrite_and_reset_count(self):
        """覆盖式更新 + 计数清零"""
        with get_db_ctx() as db:
            profile_store.increment_dialog_count(db, 2)
            profile_store.increment_dialog_count(db, 2)
            profile_store.upsert_profile(db, 2, "新画像")
            row = profile_store.get_profile(db, 2)
        assert row["style_profile"] == "新画像"
        assert int(row["dialog_count_since_update"]) == 0


class TestGetRecentExam:
    def test_returns_latest_graded(self):
        _insert_exam_with_answers(2, answers_data=[
            {"qid": "Q-1", "full": 1.0, "score": 0.0},
        ])
        with get_db_ctx() as db:
            result = profile_store.get_recent_exam(db, 2)
        assert result is not None
        assert result["subject"] == "cpa_acc"
        assert result["total"] == 1

    def test_no_graded_returns_none(self):
        with get_db_ctx() as db:
            result = profile_store.get_recent_exam(db, 2)
        assert result is None


class TestAdminWrongStats:
    def test_list_admin_wrong_stats(self):
        """全校错题 Top 知识点统计"""
        make_wrong_question(2, "Q-001", kp_ids=["ACC-01-01-01"])
        make_wrong_question(2, "Q-002", kp_ids=["ACC-01-01-01"])
        make_wrong_question(2, "Q-003", kp_ids=["ACC-03-02-01"])
        with get_db_ctx() as db:
            result = profile_store.list_admin_wrong_stats(db, days=30, top=10)
        # ACC-01-01-01: 2 次, ACC-03-02-01: 1 次
        assert result[0]["kp_id"] == "ACC-01-01-01"
        assert result[0]["wrong_count"] == 2
        assert result[0]["student_count"] == 1
