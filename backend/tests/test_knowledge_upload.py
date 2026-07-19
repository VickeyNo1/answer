# -*- coding: utf-8 -*-
"""测试 POST /api/knowledge/upload - 上传文档"""
import io
import pytest
from app.knowledge import chroma_service


@pytest.fixture(autouse=True)
def cleanup_doc():
    """每个测试后清理上传的文档"""
    yield
    try:
        chroma_service.delete_document("test_upload.txt")
        chroma_service.delete_document("test_upload.docx")
        chroma_service.delete_document("test_invalid.exe")
        chroma_service.delete_document("test_empty.txt")
    except Exception:
        pass


class TestKnowledgeUpload:

    def test_upload_txt_success(self, client, admin_headers):
        """上传 TXT 文件成功"""
        content = "借贷记账法是一种复式记账方法，以借和贷作为记账符号。" * 20
        resp = client.post(
            "/api/knowledge/upload",
            files={"file": ("test_upload.txt", io.BytesIO(content.encode("utf-8")), "text/plain")},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test_upload.txt"
        assert data["chunk_count"] > 0
        assert "created_at" in data

    def test_upload_without_token(self, client):
        """未认证返回 403"""
        content = "test content" * 50
        resp = client.post(
            "/api/knowledge/upload",
            files={"file": ("test.txt", io.BytesIO(content.encode()), "text/plain")},
        )
        assert resp.status_code in (401, 403)

    def test_upload_student_forbidden(self, client, student_headers):
        """学生无权上传返回 403"""
        content = "test content" * 50
        resp = client.post(
            "/api/knowledge/upload",
            files={"file": ("test_upload.txt", io.BytesIO(content.encode()), "text/plain")},
            headers=student_headers,
        )
        assert resp.status_code == 403

    def test_upload_invalid_format(self, client, admin_headers):
        """不支持的文件格式返回 400"""
        resp = client.post(
            "/api/knowledge/upload",
            files={"file": ("test_invalid.exe", io.BytesIO(b"\x00\x01\x02"), "application/octet-stream")},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "不支持" in resp.json()["detail"]

    def test_upload_duplicate(self, client, admin_headers):
        """重复上传返回 409"""
        content = "重复上传测试内容。" * 50
        # 第一次上传
        resp1 = client.post(
            "/api/knowledge/upload",
            files={"file": ("test_upload.txt", io.BytesIO(content.encode("utf-8")), "text/plain")},
            headers=admin_headers,
        )
        assert resp1.status_code == 201

        # 第二次上传同名文件
        resp2 = client.post(
            "/api/knowledge/upload",
            files={"file": ("test_upload.txt", io.BytesIO(content.encode("utf-8")), "text/plain")},
            headers=admin_headers,
        )
        assert resp2.status_code == 409
        assert "已存在" in resp2.json()["detail"]

    def test_upload_empty_file(self, client, admin_headers):
        """空内容文件返回 400"""
        resp = client.post(
            "/api/knowledge/upload",
            files={"file": ("test_empty.txt", io.BytesIO(b"   "), "text/plain")},
            headers=admin_headers,
        )
        assert resp.status_code == 400
