# -*- coding: utf-8 -*-
"""E2E: 知识库模块 - POST /api/knowledge/upload, GET /api/knowledge/documents, DELETE /api/knowledge/documents/{name}"""
import urllib.parse
import pytest
from tests.e2e.conftest import api_request, make_multipart


DOC_NAME = "e2e_knowledge_test.txt"
DOC_CONTENT = (
    "\u501f\u8d37\u8bb0\u8d26\u6cd5\u662f\u4ee5\u201c\u501f\u201d\u548c\u201c\u8d37\u201d"
    "\u4e3a\u8bb0\u8d26\u7b26\u53f7\u7684\u4e00\u79cd\u590d\u5f0f\u8bb0\u8d26\u65b9\u6cd5\u3002\n"
    "\u8d44\u4ea7 = \u8d1f\u503a + \u6240\u6709\u8005\u6743\u76ca\n"
    "\u501f\u65b9\u8868\u793a\u8d44\u4ea7\u7684\u589e\u52a0\u6216\u8d1f\u503a\u7684\u51cf\u5c11\uff0c"
    "\u8d37\u65b9\u8868\u793a\u8d44\u4ea7\u7684\u51cf\u5c11\u6216\u8d1f\u503a\u7684\u589e\u52a0\u3002\n"
).encode("utf-8")


class TestE2EKnowledgeUpload:

    def test_upload_txt_success(self, server_available, admin_token):
        """上传 txt 文档成功"""
        boundary, body = make_multipart(DOC_NAME, DOC_CONTENT, "text/plain")
        code, resp = api_request(
            "POST", "/api/knowledge/upload", token=admin_token,
            raw_body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        assert code == 201
        assert resp["name"] == DOC_NAME
        assert resp["chunk_count"] > 0

    def test_upload_without_token(self, server_available):
        """无 Token 上传返回 401 或 403"""
        boundary, body = make_multipart("test.txt", b"hello", "text/plain")
        code, _ = api_request(
            "POST", "/api/knowledge/upload",
            raw_body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        assert code in (401, 403)

    def test_upload_student_forbidden(self, server_available, test_student):
        """学生上传返回 403"""
        boundary, body = make_multipart("test.txt", b"hello", "text/plain")
        code, _ = api_request(
            "POST", "/api/knowledge/upload", token=test_student["token"],
            raw_body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        assert code == 403

    def test_upload_duplicate(self, server_available, admin_token):
        """重复上传同名文档返回 409"""
        boundary, body = make_multipart(DOC_NAME, DOC_CONTENT, "text/plain")
        code, _ = api_request(
            "POST", "/api/knowledge/upload", token=admin_token,
            raw_body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        assert code == 409


class TestE2EKnowledgeList:

    def test_list_returns_array(self, server_available, admin_token):
        """文档列表返回数组"""
        code, body = api_request("GET", "/api/knowledge/documents", token=admin_token)
        assert code == 200
        assert isinstance(body, list)

    def test_list_contains_uploaded_doc(self, server_available, admin_token):
        """列表中包含已上传的文档"""
        code, body = api_request("GET", "/api/knowledge/documents", token=admin_token)
        assert code == 200
        names = [d["name"] for d in body]
        assert DOC_NAME in names

    def test_list_student_forbidden(self, server_available, test_student):
        """学生无法查看文档列表"""
        code, _ = api_request("GET", "/api/knowledge/documents", token=test_student["token"])
        assert code == 403

    def test_list_without_token(self, server_available):
        """无 Token 返回 401 或 403"""
        code, _ = api_request("GET", "/api/knowledge/documents")
        assert code in (401, 403)


class TestE2EKnowledgeDelete:

    def test_delete_success(self, server_available, admin_token):
        """删除文档成功"""
        encoded = urllib.parse.quote(DOC_NAME)
        code, body = api_request(
            "DELETE", f"/api/knowledge/documents/{encoded}", token=admin_token
        )
        assert code == 200

    def test_delete_not_found(self, server_available, admin_token):
        """删除不存在的文档返回 404"""
        encoded = urllib.parse.quote("nonexistent_doc.txt")
        code, _ = api_request(
            "DELETE", f"/api/knowledge/documents/{encoded}", token=admin_token
        )
        assert code == 404

    def test_delete_student_forbidden(self, server_available, test_student):
        """学生无法删除文档"""
        encoded = urllib.parse.quote(DOC_NAME)
        code, _ = api_request(
            "DELETE", f"/api/knowledge/documents/{encoded}",
            token=test_student["token"],
        )
        assert code == 403
