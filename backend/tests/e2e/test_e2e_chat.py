# -*- coding: utf-8 -*-
"""E2E: 对话模块 - POST /api/chat (SSE), POST /api/conversations, GET /api/conversations, GET /api/conversations/{id}, DELETE /api/conversations/{id}"""
import pytest
from tests.e2e.conftest import api_request, api_sse


class TestE2EConversationCreate:

    def test_create_with_title(self, server_available, test_student):
        """新建带标题的对话"""
        code, body = api_request("POST", "/api/conversations", token=test_student["token"],
                                 data={"title": "E2E\u6d4b\u8bd5\u5bf9\u8bdd"})
        assert code == 201
        assert "id" in body
        assert body["title"] == "E2E\u6d4b\u8bd5\u5bf9\u8bdd"
        assert "created_at" in body

    def test_create_default_title(self, server_available, test_student):
        """不传标题使用默认值"""
        code, body = api_request("POST", "/api/conversations", token=test_student["token"],
                                 data={})
        assert code == 201
        assert body["title"] == "\u65b0\u5bf9\u8bdd"

    def test_create_without_token(self, server_available):
        """无 Token 创建对话返回 401 或 403"""
        code, _ = api_request("POST", "/api/conversations", data={"title": "test"})
        assert code in (401, 403)


class TestE2EConversationList:

    def test_list_returns_array(self, server_available, test_student):
        """对话列表返回数组"""
        code, body = api_request("GET", "/api/conversations", token=test_student["token"])
        assert code == 200
        assert isinstance(body, list)

    def test_list_after_create(self, server_available, test_student):
        """创建后列表中包含新对话"""
        # 创建对话
        code, created = api_request("POST", "/api/conversations", token=test_student["token"],
                                   data={"title": "ListTest"})
        assert code == 201
        # 获取列表
        code, body = api_request("GET", "/api/conversations", token=test_student["token"])
        assert code == 200
        ids = [c["id"] for c in body]
        assert created["id"] in ids

    def test_list_without_token(self, server_available):
        """无 Token 返回 401 或 403"""
        code, _ = api_request("GET", "/api/conversations")
        assert code in (401, 403)


class TestE2EChatSSE:

    def test_chat_auto_create_conversation(self, server_available, test_student):
        """SSE 对话: conversation_id=null 自动创建对话"""
        code, events = api_sse("/api/chat", test_student["token"], {
            "conversation_id": None,
            "message": "\u4ec0\u4e48\u662f\u501f\u8d37\u8bb0\u8d26\u6cd5\uff1f",
        })
        assert code == 200
        start_events = [e for e in events if e.get("type") == "start"]
        assert len(start_events) > 0
        assert "conversation_id" in start_events[0]

    def test_chat_returns_delta_and_done(self, server_available, test_student):
        """SSE 对话: 收到 delta 和 done 事件"""
        code, events = api_sse("/api/chat", test_student["token"], {
            "conversation_id": None,
            "message": "\u8d44\u4ea7=\u8d1f\u503a+\u6240\u6709\u8005\u6743\u76ca \u662f\u4ec0\u4e48\u610f\u601d\uff1f",
        })
        delta_events = [e for e in events if e.get("type") == "delta"]
        done_events = [e for e in events if e.get("type") == "done"]
        assert len(delta_events) > 0, "应该收到至少一个 delta 事件"
        assert len(done_events) > 0, "应该收到 done 事件"
        assert "message_id" in done_events[0]

    def test_chat_ai_content_not_empty(self, server_available, test_student):
        """SSE 对话: AI 回答非空"""
        code, events = api_sse("/api/chat", test_student["token"], {
            "conversation_id": None,
            "message": "\u4ec0\u4e48\u662f\u4f1a\u8ba1\uff1f",
        })
        delta_events = [e for e in events if e.get("type") == "delta"]
        content = "".join(e.get("content", "") for e in delta_events)
        assert len(content) > 10, f"AI 回答应该超过10个字符, 实际: {len(content)}"

    def test_chat_with_existing_conversation(self, server_available, test_student):
        """SSE 对话: 已有对话续聊"""
        # 第一次对话
        code, events = api_sse("/api/chat", test_student["token"], {
            "conversation_id": None,
            "message": "\u4ec0\u4e48\u662f\u501f\u8d37\u8bb0\u8d26\u6cd5\uff1f",
        })
        start_events = [e for e in events if e.get("type") == "start"]
        conv_id = start_events[0]["conversation_id"]

        # 续聊
        code2, events2 = api_sse("/api/chat", test_student["token"], {
            "conversation_id": conv_id,
            "message": "\u80fd\u4e3e\u4e2a\u4f8b\u5b50\u5417\uff1f",
        })
        delta_events = [e for e in events2 if e.get("type") == "delta"]
        assert len(delta_events) > 0

    def test_chat_with_subject_id(self, server_available, test_student, admin_token):
        """SSE 对话: 带 subject_id 发起对话，科目随对话持久化"""
        # 取一个已有科目（默认 seed 应存在）
        code, subjects = api_request("GET", "/api/subjects", token=test_student["token"])
        assert code == 200
        subject_id = subjects[0]["id"] if subjects else None

        code, events = api_sse("/api/chat", test_student["token"], {
            "conversation_id": None,
            "message": "\u4ec0\u4e48\u662f\u4f1a\u8ba1\u51ed\u8bc1\uff1f",
            "subject_id": subject_id,
        })
        assert code == 200
        start_events = [e for e in events if e.get("type") == "start"]
        assert len(start_events) > 0
        conv_id = start_events[0]["conversation_id"]

        # 对话列表回显 subject_id
        code, convs = api_request("GET", "/api/conversations", token=test_student["token"])
        assert code == 200
        conv = next((c for c in convs if c["id"] == conv_id), None)
        assert conv is not None
        if subject_id is not None:
            assert conv["subject_id"] == subject_id

    def test_chat_without_token(self, server_available):
        """无 Token 发送消息返回 401 或 403"""
        from tests.e2e.conftest import API_BASE
        import json
        import urllib.request
        import urllib.error

        url = f"{API_BASE}/api/chat"
        body = json.dumps({"conversation_id": None, "message": "test"}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
            assert False, "\u5e94\u8be5\u8fd4\u56de\u9519\u8bef"
        except urllib.error.HTTPError as e:
            assert e.code in (401, 403)


class TestE2EConversationMessages:

    def test_get_messages_with_data(self, server_available, test_student):
        """获取消息历史: 有数据"""
        # 先对话产生消息
        code, events = api_sse("/api/chat", test_student["token"], {
            "conversation_id": None,
            "message": "\u4ec0\u4e48\u662f\u4f1a\u8ba1\uff1f",
        })
        start_events = [e for e in events if e.get("type") == "start"]
        conv_id = start_events[0]["conversation_id"]

        # 获取消息
        code2, body = api_request("GET", f"/api/conversations/{conv_id}", token=test_student["token"])
        assert code2 == 200
        assert isinstance(body, list)
        assert len(body) >= 2  # user + assistant

    def test_get_messages_order_ascending(self, server_available, test_student):
        """消息按时间升序"""
        code, events = api_sse("/api/chat", test_student["token"], {
            "conversation_id": None,
            "message": "\u4ec0\u4e48\u662f\u8d44\u4ea7\uff1f",
        })
        conv_id = [e for e in events if e.get("type") == "start"][0]["conversation_id"]
        code2, body = api_request("GET", f"/api/conversations/{conv_id}", token=test_student["token"])
        if len(body) >= 2:
            assert body[0]["created_at"] <= body[-1]["created_at"]

    def test_get_messages_roles(self, server_available, test_student):
        """消息角色包含 user 和 assistant"""
        code, events = api_sse("/api/chat", test_student["token"], {
            "conversation_id": None,
            "message": "\u4ec0\u4e48\u662f\u8d1f\u503a\uff1f",
        })
        conv_id = [e for e in events if e.get("type") == "start"][0]["conversation_id"]
        code2, body = api_request("GET", f"/api/conversations/{conv_id}", token=test_student["token"])
        roles = [m["role"] for m in body]
        assert "user" in roles
        assert "assistant" in roles

    def test_get_messages_not_found(self, server_available, test_student):
        """不存在的对话返回 404"""
        code, _ = api_request("GET", "/api/conversations/99999", token=test_student["token"])
        assert code == 404

    def test_get_messages_other_user(self, server_available, test_student, admin_token):
        """获取其他用户的对话返回 404"""
        # 学生创建对话
        code, events = api_sse("/api/chat", test_student["token"], {
            "conversation_id": None,
            "message": "test",
        })
        conv_id = [e for e in events if e.get("type") == "start"][0]["conversation_id"]
        # 管理员尝试访问
        code2, _ = api_request("GET", f"/api/conversations/{conv_id}", token=admin_token)
        assert code2 == 404


class TestE2EConversationDelete:

    def test_delete_success(self, server_available, test_student):
        """删除对话成功"""
        # 创建对话
        code, body = api_request("POST", "/api/conversations", token=test_student["token"],
                                 data={"title": "ToDelete"})
        conv_id = body["id"]
        # 删除
        code2, body2 = api_request("DELETE", f"/api/conversations/{conv_id}", token=test_student["token"])
        assert code2 == 200

    def test_delete_not_found(self, server_available, test_student):
        """删除不存在的对话返回 404"""
        code, _ = api_request("DELETE", "/api/conversations/99999", token=test_student["token"])
        assert code == 404

    def test_delete_other_user(self, server_available, test_student, admin_token):
        """删除其他用户的对话返回 404"""
        code, body = api_request("POST", "/api/conversations", token=test_student["token"],
                                 data={"title": "OtherUserDelete"})
        conv_id = body["id"]
        code2, _ = api_request("DELETE", f"/api/conversations/{conv_id}", token=admin_token)
        assert code2 == 404

    def test_delete_cascades_messages(self, server_available, test_student):
        """删除对话后消息也被删除"""
        # 对话产生消息
        code, events = api_sse("/api/chat", test_student["token"], {
            "conversation_id": None,
            "message": "test cascade",
        })
        conv_id = [e for e in events if e.get("type") == "start"][0]["conversation_id"]
        # 删除对话
        api_request("DELETE", f"/api/conversations/{conv_id}", token=test_student["token"])
        # 获取消息应该 404
        code3, _ = api_request("GET", f"/api/conversations/{conv_id}", token=test_student["token"])
        assert code3 == 404
