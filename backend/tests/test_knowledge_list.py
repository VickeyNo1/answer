# -*- coding: utf-8 -*-
"""测试 GET /api/knowledge/documents - 获取文档列表"""
import io
import pytest
from app.knowledge import chroma_service


@pytest.fixture(autouse=True)
def cleanup_docs():
    """测试后清理"""
    yield
    for name in ["list_test_1.txt", "list_test_2.txt"]:
        try:
            chroma_service.delete_document(name)
        except Exception:
            pass


class TestKnowledgeList:

    def test_list_returns_array(self, client, admin_headers):
        """返回文档数组"""
        resp = client.get("/api/knowledge/documents", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_after_upload(self, client, admin_headers):
        """上传后出现在列表中"""
        content = "列表测试内容。" * 50
        client.post(
            "/api/knowledge/upload",
            files={"file": ("list_test_1.txt", io.BytesIO(content.encode("utf-8")), "text/plain")},
            headers=admin_headers,
        )

        resp = client.get("/api/knowledge/documents", headers=admin_headers)
        names = [d["name"] for d in resp.json()]
        assert "list_test_1.txt" in names

    def test_list_without_token(self, client):
        """未认证返回 403"""
        resp = client.get("/api/knowledge/documents")
        assert resp.status_code in (401, 403)

    def test_list_student_forbidden(self, client, student_headers):
        """学生无权访问返回 403"""
        resp = client.get("/api/knowledge/documents", headers=student_headers)
        assert resp.status_code == 403

    def test_list_response_fields(self, client, admin_headers):
        """每条文档包含 name 和 chunk_count"""
        content = "字段测试。" * 50
        client.post(
            "/api/knowledge/upload",
            files={"file": ("list_test_2.txt", io.BytesIO(content.encode("utf-8")), "text/plain")},
            headers=admin_headers,
        )

        resp = client.get("/api/knowledge/documents", headers=admin_headers)
        for doc in resp.json():
            assert "name" in doc
            assert "chunk_count" in doc
            assert isinstance(doc["chunk_count"], int)
