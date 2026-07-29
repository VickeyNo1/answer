# -*- coding: utf-8 -*-
"""测试答案反馈：POST /api/feedback + GET /api/admin/feedbacks

覆盖：
- 提交点赞/点踩（down 无理由 400）
- 三层归属校验（不存在 404 / 非本人 403 / 非 assistant 消息 400）
- 重复提交覆盖更新（UPSERT，单行）
- 管理员反馈明细：total/items、rating 筛选、分页、上一条学生提问关联
"""
import pytest

from app.database import get_db_ctx


@pytest.fixture(scope="module")
def feedback_data(client):
    """造数：学生（id=2）一段完整问答 + 管理员（id=1）自己的问答（用于 403 用例）"""
    with get_db_ctx() as db:
        # 学生会话：user 提问 → assistant 回答
        cursor = db.execute(
            "INSERT INTO conversations (user_id, title, subject) VALUES (%s, %s, %s)",
            (2, "反馈测试会话", "cpa_acc"),
        )
        student_conv = cursor.lastrowid
        cursor = db.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
            (student_conv, "user", "存货怎么计价？"),
        )
        student_question = cursor.lastrowid
        cursor = db.execute(
            "INSERT INTO messages (conversation_id, role, content, knowledge_point_ids) "
            "VALUES (%s, %s, %s, %s)",
            (student_conv, "assistant", "存货应按成本计量。", '["KP-001"]'),
        )
        student_answer = cursor.lastrowid

        # 管理员会话：assistant 消息（学生对其反馈应 403）
        cursor = db.execute(
            "INSERT INTO conversations (user_id, title) VALUES (%s, %s)",
            (1, "管理员会话"),
        )
        admin_conv = cursor.lastrowid
        cursor = db.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
            (admin_conv, "assistant", "管理员的 AI 回答"),
        )
        admin_answer = cursor.lastrowid
        db.commit()

    return {
        "student_question": student_question,
        "student_answer": student_answer,
        "admin_answer": admin_answer,
    }


class TestSubmitFeedback:
    """POST /api/feedback"""

    def test_without_token(self, client, feedback_data):
        resp = client.post("/api/feedback", json={
            "message_id": feedback_data["student_answer"], "rating": "up",
        })
        assert resp.status_code in (401, 403)

    def test_invalid_rating(self, client, student_headers, feedback_data):
        resp = client.post("/api/feedback", json={
            "message_id": feedback_data["student_answer"], "rating": "great",
        }, headers=student_headers)
        assert resp.status_code == 400

    def test_down_without_reason(self, client, student_headers, feedback_data):
        resp = client.post("/api/feedback", json={
            "message_id": feedback_data["student_answer"], "rating": "down",
        }, headers=student_headers)
        assert resp.status_code == 400
        assert "理由" in resp.json()["detail"]

    def test_message_not_found(self, client, student_headers):
        resp = client.post("/api/feedback", json={
            "message_id": 999999, "rating": "up",
        }, headers=student_headers)
        assert resp.status_code == 404

    def test_others_message_forbidden(self, client, student_headers, feedback_data):
        """学生评价管理员会话的消息 → 403"""
        resp = client.post("/api/feedback", json={
            "message_id": feedback_data["admin_answer"], "rating": "up",
        }, headers=student_headers)
        assert resp.status_code == 403

    def test_user_role_message_rejected(self, client, student_headers, feedback_data):
        """只能评价 assistant 消息，user 消息 → 400"""
        resp = client.post("/api/feedback", json={
            "message_id": feedback_data["student_question"], "rating": "up",
        }, headers=student_headers)
        assert resp.status_code == 400

    def test_submit_up_ok(self, client, student_headers, feedback_data):
        resp = client.post("/api/feedback", json={
            "message_id": feedback_data["student_answer"], "rating": "up",
        }, headers=student_headers)
        assert resp.status_code == 200
        assert resp.json() == {"message": "ok"}

    def test_upsert_overwrites(self, client, student_headers, feedback_data):
        """重复提交覆盖更新：up → down，单行且 rating 为最新值"""
        message_id = feedback_data["student_answer"]
        client.post("/api/feedback", json={
            "message_id": message_id, "rating": "up",
        }, headers=student_headers)
        resp = client.post("/api/feedback", json={
            "message_id": message_id, "rating": "down", "reason": "答案不完整",
        }, headers=student_headers)
        assert resp.status_code == 200

        with get_db_ctx() as db:
            rows = db.execute(
                "SELECT rating, reason FROM feedbacks WHERE message_id = %s",
                (message_id,),
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["rating"] == "down"
        assert rows[0]["reason"] == "答案不完整"


class TestAdminFeedbackList:
    """GET /api/admin/feedbacks"""

    def test_requires_admin(self, client, student_headers):
        resp = client.get("/api/admin/feedbacks", headers=student_headers)
        assert resp.status_code == 403

    def test_list_structure_and_question(self, client, admin_headers,
                                         student_headers, feedback_data):
        # 确保存在一条点踩反馈
        client.post("/api/feedback", json={
            "message_id": feedback_data["student_answer"],
            "rating": "down", "reason": "答案不完整",
        }, headers=student_headers)

        resp = client.get("/api/admin/feedbacks", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data and "items" in data
        assert data["total"] >= 1

        item = next(
            i for i in data["items"]
            if i["answer"] == "存货应按成本计量。"
        )
        assert item["rating"] == "down"
        assert item["reason"] == "答案不完整"
        assert item["student_id"] == "2024001"
        # 上一条学生提问：应用层关联同会话中该 assistant 消息之前最近的 user 消息
        assert item["question"] == "存货怎么计价？"
        assert item["knowledge_point_ids"] == ["KP-001"]

    def test_rating_filter(self, client, admin_headers, feedback_data):
        resp = client.get("/api/admin/feedbacks?rating=up", headers=admin_headers)
        assert resp.status_code == 200
        assert all(i["rating"] == "up" for i in resp.json()["items"])

    def test_pagination(self, client, admin_headers, feedback_data):
        resp = client.get(
            "/api/admin/feedbacks?page=1&page_size=1", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 1
        # 越界页返回空 items，total 不变
        resp2 = client.get(
            "/api/admin/feedbacks?page=999&page_size=20", headers=admin_headers
        )
        assert resp2.json()["items"] == []
        assert resp2.json()["total"] == data["total"]
