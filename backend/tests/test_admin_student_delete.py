# -*- coding: utf-8 -*-
"""测试 DELETE /api/admin/students/{id} - 删除学生"""
import pytest
from app.database import get_db_ctx


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with get_db_ctx() as db:
        # 成功路径下 usage_logs.user_id 已被置 NULL，只能靠 model_name 找回
        db.execute("DELETE FROM usage_logs WHERE model_name = 'del_test_model'")

        # 用例中途失败时学生还在，按 id 清掉其余各表
        ids = [r["id"] for r in db.execute(
            "SELECT id FROM users WHERE student_id LIKE 'del_test_%'"
        ).fetchall()]
        if ids:
            ph = ",".join(["%s"] * len(ids))
            for table in ("feedbacks", "kb_search_logs", "wrong_questions",
                          "student_profiles", "usage_logs"):
                db.execute(f"DELETE FROM {table} WHERE user_id IN ({ph})", ids)
            db.execute(
                f"DELETE FROM exam_answers WHERE exam_id IN "
                f"(SELECT id FROM exams WHERE user_id IN ({ph}))", ids)
            db.execute(f"DELETE FROM exams WHERE user_id IN ({ph})", ids)
            db.execute(
                f"DELETE FROM messages WHERE conversation_id IN "
                f"(SELECT id FROM conversations WHERE user_id IN ({ph}))", ids)
            db.execute(f"DELETE FROM conversations WHERE user_id IN ({ph})", ids)
        db.execute("DELETE FROM users WHERE student_id LIKE 'del_test_%'")
        db.commit()


class TestAdminStudentDelete:

    def test_delete_success(self, client, admin_headers):
        """删除学生成功"""
        create_resp = client.post("/api/admin/students", json={
            "student_id": "del_test_001",
            "name": "待删除",
            "password": "pass123",
        }, headers=admin_headers)
        student_id = create_resp.json()["id"]

        resp = client.delete(f"/api/admin/students/{student_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["message"] == "ok"

    def test_delete_not_found(self, client, admin_headers):
        """删除不存在的学生返回 404"""
        resp = client.delete("/api/admin/students/99999", headers=admin_headers)
        assert resp.status_code == 404

    def test_delete_admin_forbidden(self, client, admin_headers):
        """不能删除管理员账号"""
        # admin 的 id 是 1
        resp = client.delete("/api/admin/students/1", headers=admin_headers)
        assert resp.status_code == 403
        assert "管理员" in resp.json()["detail"]

    def test_delete_without_token(self, client):
        """未认证返回 403"""
        resp = client.delete("/api/admin/students/2")
        assert resp.status_code in (401, 403)

    def test_delete_student_forbidden(self, client, student_headers):
        """学生无权删除返回 403"""
        resp = client.delete("/api/admin/students/2", headers=student_headers)
        assert resp.status_code == 403

    def test_delete_cascades_conversations(self, client, admin_headers):
        """删除学生时级联删除对话和消息"""
        # 创建学生
        create_resp = client.post("/api/admin/students", json={
            "student_id": "del_test_002",
            "name": "级联删除测试",
            "password": "pass123",
        }, headers=admin_headers)
        student_id = create_resp.json()["id"]

        # 创建对话和消息
        with get_db_ctx() as db:
            cursor = db.execute(
                "INSERT INTO conversations (user_id, title) VALUES (%s, %s)",
                (student_id, "测试对话"),
            )
            conv_id = cursor.lastrowid
            db.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conv_id, "user", "测试消息"),
            )
            db.commit()

        # 删除学生
        resp = client.delete(f"/api/admin/students/{student_id}", headers=admin_headers)
        assert resp.status_code == 200

        # 确认对话和消息也被删除
        with get_db_ctx() as db:
            conv_count = db.execute(
                "SELECT COUNT(*) as cnt FROM conversations WHERE user_id = %s",
                (student_id,),
            ).fetchone()["cnt"]
            msg_count = db.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = %s",
                (conv_id,),
            ).fetchone()["cnt"]
            assert conv_count == 0
            assert msg_count == 0

    def test_delete_cascades_all_student_data(self, client, admin_headers):
        """删除学生清空其全部学习数据；用量日志保留行但解除归属

        usage_logs 只有 tokens/费用/模型名，删掉会让「累计费用」少报已真实发生的开销，
        故只置空 user_id/conversation_id（两列可空），行本身留下。
        """
        student_id = client.post("/api/admin/students", json={
            "student_id": "del_test_003",
            "name": "全量级联",
            "password": "pass123",
        }, headers=admin_headers).json()["id"]

        with get_db_ctx() as db:
            conv_id = db.execute(
                "INSERT INTO conversations (user_id, title) VALUES (%s, %s)",
                (student_id, "会话"),
            ).lastrowid
            msg_id = db.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conv_id, "assistant", "回答"),
            ).lastrowid
            db.execute(
                "INSERT INTO feedbacks (message_id, user_id, rating) VALUES (%s, %s, 'up')",
                (msg_id, student_id),
            )
            db.execute(
                """INSERT INTO kb_search_logs
                   (user_id, conversation_id, subject, collection, query, result_count, status)
                   VALUES (%s, %s, 'cpa_acc', 'questions', '学生提问原文', 1, 'ok')""",
                (student_id, conv_id),
            )
            db.execute(
                """INSERT INTO usage_logs
                   (model_name, user_id, conversation_id,
                    prompt_tokens, completion_tokens, total_tokens, cost)
                   VALUES ('del_test_model', %s, %s, 10, 5, 15, 0.5)""",
                (student_id, conv_id),
            )
            exam_id = db.execute(
                """INSERT INTO exams (user_id, subject, status, question_count, total_score)
                   VALUES (%s, 'cpa_acc', 'graded', 1, 10)""",
                (student_id,),
            ).lastrowid
            db.execute(
                """INSERT INTO exam_answers
                   (exam_id, seq, question_id, question_type, question_snapshot, full_score)
                   VALUES (%s, 1, 'DEL_TEST_Q', '单选', '{}', 10)""",
                (exam_id,),
            )
            db.execute(
                """INSERT INTO wrong_questions (user_id, subject, question_id, question_snapshot)
                   VALUES (%s, 'cpa_acc', 'DEL_TEST_Q', '{}')""",
                (student_id,),
            )
            db.execute(
                "INSERT INTO student_profiles (user_id, style_profile) VALUES (%s, '画像')",
                (student_id,),
            )
            db.commit()

        resp = client.delete(f"/api/admin/students/{student_id}", headers=admin_headers)
        assert resp.status_code == 200

        with get_db_ctx() as db:
            def cnt(sql, params):
                return db.execute(sql, params).fetchone()["cnt"]

            assert cnt("SELECT COUNT(*) AS cnt FROM conversations WHERE id = %s", (conv_id,)) == 0
            assert cnt("SELECT COUNT(*) AS cnt FROM messages WHERE id = %s", (msg_id,)) == 0
            assert cnt("SELECT COUNT(*) AS cnt FROM feedbacks WHERE message_id = %s", (msg_id,)) == 0
            assert cnt("SELECT COUNT(*) AS cnt FROM kb_search_logs WHERE conversation_id = %s", (conv_id,)) == 0
            assert cnt("SELECT COUNT(*) AS cnt FROM exams WHERE id = %s", (exam_id,)) == 0
            assert cnt("SELECT COUNT(*) AS cnt FROM exam_answers WHERE exam_id = %s", (exam_id,)) == 0
            assert cnt("SELECT COUNT(*) AS cnt FROM wrong_questions WHERE user_id = %s", (student_id,)) == 0
            assert cnt("SELECT COUNT(*) AS cnt FROM student_profiles WHERE user_id = %s", (student_id,)) == 0

            row = db.execute(
                """SELECT user_id, conversation_id, cost FROM usage_logs
                   WHERE model_name = 'del_test_model'"""
            ).fetchone()
            assert row is not None
            assert row["user_id"] is None
            assert row["conversation_id"] is None
            assert float(row["cost"]) == pytest.approx(0.5)
