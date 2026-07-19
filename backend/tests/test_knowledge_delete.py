# -*- coding: utf-8 -*-
"""测试 DELETE /api/knowledge/documents/{name} - 删除文档"""
import io
import pytest
from app.knowledge import chroma_service


@pytest.fixture(autouse=True)
def cleanup():
    yield
    try:
        chroma_service.delete_document("delete_test.txt")
    except Exception:
        pass


class TestKnowledgeDelete:

    def test_delete_success(self, client, admin_headers):
        """删除已存在的文档"""
        # 先上传
        content = "删除测试内容。" * 50
        client.post(
            "/api/knowledge/upload",
            files={"file": ("delete_test.txt", io.BytesIO(content.encode("utf-8")), "text/plain")},
            headers=admin_headers,
        )

        # 删除
        resp = client.delete("/api/knowledge/documents/delete_test.txt", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["message"] == "ok"

        # 确认已删除
        docs = client.get("/api/knowledge/documents", headers=admin_headers).json()
        names = [d["name"] for d in docs]
        assert "delete_test.txt" not in names

    def test_delete_not_found(self, client, admin_headers):
        """删除不存在的文档返回 404"""
        resp = client.delete("/api/knowledge/documents/nonexistent.txt", headers=admin_headers)
        assert resp.status_code == 404

    def test_delete_without_token(self, client):
        """未认证返回 403"""
        resp = client.delete("/api/knowledge/documents/some.txt")
        assert resp.status_code in (401, 403)

    def test_delete_student_forbidden(self, client, student_headers):
        """学生无权删除返回 403"""
        resp = client.delete("/api/knowledge/documents/some.txt", headers=student_headers)
        assert resp.status_code == 403
