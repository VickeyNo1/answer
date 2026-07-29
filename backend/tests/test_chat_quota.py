# -*- coding: utf-8 -*-
"""测试聊天配额与并发控制（v4.0 M1）

覆盖：
- 每日配额：生效上限（users 覆盖值 ?? 全局默认）用尽 → 429
- 单人串行：同一用户上一条回答未完成 → 429
- 并发闸门 + 有限等待队列（app/chat/concurrency 单元级）

使用独立账号，避免污染 student(2024001) 的当日提问计数。
"""
import bcrypt
import pytest

from app.database import get_db_ctx
from app.auth.jwt_handler import create_access_token
from app.chat import concurrency


class FakeResponse:
    """模拟 dashscope 流式响应块（防御用：配额/锁被拒时不应走到模型调用）"""

    def __init__(self, content="", finish_reason=None, usage=None):
        self.status_code = 200
        self.code = ""
        self.message = ""
        self.usage = usage
        self.output = {"choices": [{
            "message": {"content": content} if content else {},
            "finish_reason": finish_reason,
        }]}


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    def fake_call(*args, **kwargs):
        yield FakeResponse(content="好的。", finish_reason="stop",
                           usage={"input_tokens": 1, "output_tokens": 1})
    monkeypatch.setattr(
        "app.chat.qwen_service.Generation.call", staticmethod(fake_call)
    )


@pytest.fixture(scope="module")
def quota_user(client):
    """创建独立测试用户，返回 (user_id, headers)"""
    password_hash = bcrypt.hashpw(b"quota123456", bcrypt.gensalt()).decode("utf-8")
    with get_db_ctx() as db:
        cursor = db.execute(
            "INSERT INTO users (student_id, password_hash, name, role) "
            "VALUES (%s, %s, %s, 'student')",
            ("quota_test_user", password_hash, "配额测试"),
        )
        db.commit()
        user_id = cursor.lastrowid
    token = create_access_token(user_id=user_id, role="student")
    return user_id, {"Authorization": f"Bearer {token}"}


class TestDailyQuota:
    """每日提问配额 → 429"""

    def test_limit_zero_rejected(self, client, admin_headers, quota_user):
        user_id, headers = quota_user
        resp = client.put(
            f"/api/admin/students/{user_id}/entitlements",
            json={"daily_question_limit": 0}, headers=admin_headers,
        )
        assert resp.status_code == 200

        try:
            resp = client.post("/api/chat", json={
                "conversation_id": None, "message": "你好",
            }, headers=headers)
            assert resp.status_code == 429
            assert "今日提问次数已用完" in resp.json()["detail"]
        finally:
            # 恢复跟随全局默认
            client.put(
                f"/api/admin/students/{user_id}/entitlements",
                json={"daily_question_limit": None}, headers=admin_headers,
            )

    def test_limit_reached_by_usage(self, client, admin_headers, quota_user):
        """limit=1 且当日已有 1 条提问 → 429"""
        user_id, headers = quota_user
        with get_db_ctx() as db:
            cursor = db.execute(
                "INSERT INTO conversations (user_id, title) VALUES (%s, %s)",
                (user_id, "配额会话"),
            )
            conv_id = cursor.lastrowid
            db.execute(
                "INSERT INTO messages (conversation_id, role, content) "
                "VALUES (%s, 'user', %s)",
                (conv_id, "第一问"),
            )
            db.commit()

        client.put(
            f"/api/admin/students/{user_id}/entitlements",
            json={"daily_question_limit": 1}, headers=admin_headers,
        )
        try:
            resp = client.post("/api/chat", json={
                "conversation_id": conv_id, "message": "第二问",
            }, headers=headers)
            assert resp.status_code == 429
        finally:
            client.put(
                f"/api/admin/students/{user_id}/entitlements",
                json={"daily_question_limit": None}, headers=admin_headers,
            )


class TestUserSerial:
    """单人串行：上一条回答还在进行中 → 429"""

    def test_user_lock_held_rejected(self, client, quota_user):
        user_id, headers = quota_user
        assert concurrency.acquire_user_lock(user_id)
        try:
            resp = client.post("/api/chat", json={
                "conversation_id": None, "message": "并发提问",
            }, headers=headers)
            assert resp.status_code == 429
            assert "上一条回答还在进行中" in resp.json()["detail"]
        finally:
            concurrency.release_user_lock(user_id)


class TestConcurrencyGate:
    """并发闸门 + 有限等待队列（模块单元级）"""

    def test_queue_full_returns_none(self):
        concurrency.init(1)
        try:
            # 占满唯一执行位
            assert concurrency.try_enqueue(queue_size=1) == concurrency.IMMEDIATE
            # 进入等待队列（队位 1/1）
            ticket = concurrency.try_enqueue(queue_size=1)
            assert ticket is not None and ticket != concurrency.IMMEDIATE
            # 队列已满 → None（对应 429）
            assert concurrency.try_enqueue(queue_size=1) is None

            # 释放执行位后，排队者可获得执行权（wait_slot 正常结束）
            concurrency.release_slot()
            positions = list(concurrency.wait_slot(ticket))
            assert positions in ([], [1])  # 入队推一次队位；竞争成功则直接结束
            concurrency.release_slot()
        finally:
            # 恢复为测试会话的默认并发配置，避免影响其他用例
            from app import settings_store
            concurrency.init(settings_store.get_int("chat_concurrency"))

    def test_immediate_wait_slot_yields_nothing(self):
        assert list(concurrency.wait_slot(concurrency.IMMEDIATE)) == []
