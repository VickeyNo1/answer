# -*- coding: utf-8 -*-
"""测试 POST /api/admin/students/batch - Excel 批量导入"""
import io
import pytest
from openpyxl import Workbook
from app.database import get_db_ctx


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with get_db_ctx() as db:
        db.execute("DELETE FROM users WHERE student_id LIKE 'batch_test_%'")
        db.commit()


def _make_excel(rows: list[list]) -> io.BytesIO:
    """创建 Excel 文件"""
    wb = Workbook()
    ws = wb.active
    ws.append(["学号", "姓名", "密码"])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class TestAdminStudentBatch:

    def test_batch_success(self, client, admin_headers):
        """批量导入成功"""
        excel = _make_excel([
            ["batch_test_001", "学生A", "pass111"],
            ["batch_test_002", "学生B", "pass222"],
        ])
        resp = client.post(
            "/api/admin/students/batch",
            files={"file": ("students.xlsx", excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] == 2
        assert data["failed"] == 0

    def test_batch_with_errors(self, client, admin_headers):
        """部分失败的批量导入"""
        # 先创建一个学号
        client.post("/api/admin/students", json={
            "student_id": "batch_test_010",
            "name": "已有学生",
            "password": "pass",
        }, headers=admin_headers)

        excel = _make_excel([
            ["batch_test_011", "新学生", "pass"],
            ["batch_test_010", "重复学号", "pass"],  # 学号已存在
            ["", "空学号", "pass"],  # 学号为空
        ])
        resp = client.post(
            "/api/admin/students/batch",
            files={"file": ("students.xlsx", excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] == 1
        assert data["failed"] == 2
        assert len(data["errors"]) == 2
        # 错误包含行号和原因
        for err in data["errors"]:
            assert "row" in err
            assert "reason" in err

    def test_batch_empty_file(self, client, admin_headers):
        """空 Excel（只有表头）"""
        excel = _make_excel([])
        resp = client.post(
            "/api/admin/students/batch",
            files={"file": ("empty.xlsx", excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] == 0
        assert data["failed"] == 0

    def test_batch_invalid_format(self, client, admin_headers):
        """非 Excel 格式返回 400"""
        resp = client.post(
            "/api/admin/students/batch",
            files={"file": ("not_excel.txt", io.BytesIO(b"not excel"), "text/plain")},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "xlsx" in resp.json()["detail"].lower() or "格式" in resp.json()["detail"]

    def test_batch_without_token(self, client):
        """未认证返回 403"""
        excel = _make_excel([["x", "y", "z"]])
        resp = client.post(
            "/api/admin/students/batch",
            files={"file": ("students.xlsx", excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert resp.status_code in (401, 403)

    def test_batch_student_forbidden(self, client, student_headers):
        """学生无权批量导入返回 403"""
        excel = _make_excel([["x", "y", "z"]])
        resp = client.post(
            "/api/admin/students/batch",
            files={"file": ("students.xlsx", excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=student_headers,
        )
        assert resp.status_code == 403
