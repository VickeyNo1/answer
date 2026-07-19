# -*- coding: utf-8 -*-
"""E2E 测试共享 fixtures 和工具函数"""
import json
import time
import io
import codecs
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

import pytest

API_BASE = "http://localhost:8000"
FRONTEND_BASE = "http://localhost:3000"


# ==================== HTTP 工具函数 ====================

def api_request(
    method: str,
    path: str,
    token: Optional[str] = None,
    data: Optional[dict] = None,
    raw_body: Optional[bytes] = None,
    content_type: str = "application/json",
    timeout: int = 30,
):
    """发送 HTTP 请求到后端，返回 (status_code, json_body)"""
    url = f"{API_BASE}{path}"
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = None
    if raw_body is not None:
        body = raw_body
    elif data is not None:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read().decode("utf-8")
        return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


def api_sse(path: str, token: str, data: dict, timeout: int = 120):
    """发送 SSE 请求，返回 (status_code, events_list)"""
    url = f"{API_BASE}{path}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    resp = urllib.request.urlopen(req, timeout=timeout)
    events = []
    buffer = ""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="ignore")
    while True:
        chunk = resp.read(4096)
        if not chunk:
            break
        buffer += decoder.decode(chunk)
        lines = buffer.split("\n")
        buffer = lines.pop() or ""
        for line in lines:
            line = line.strip()
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
    buffer += decoder.decode(b"", final=True)
    for line in buffer.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return resp.status, events


def make_multipart(filename: str, content: bytes, mime_type: str = "text/plain") -> tuple:
    """构造 multipart/form-data 请求体，返回 (boundary, body_bytes)"""
    boundary = f"----E2E{int(time.time() * 1000)}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return boundary, body


def make_excel_file(students: list) -> bytes:
    """创建 Excel 文件用于批量导入测试"""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["\u5b66\u53f7", "\u59d3\u540d", "\u5bc6\u7801"])
    for row in students:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def check_frontend_page(path: str, timeout: int = 30):
    """检查前端页面是否返回 200，返回 (status_code, content_length)"""
    url = f"{FRONTEND_BASE}{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, len(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, 0
    except urllib.error.URLError:
        return 0, 0


# ==================== pytest fixtures ====================

@pytest.fixture(scope="session")
def server_available():
    """检查后端服务器是否可用，不可用则跳过所有 E2E 测试"""
    try:
        code, _ = api_request("GET", "/api/health", timeout=5)
        if code != 200:
            pytest.skip("后端服务器未运行在 localhost:8000，跳过 E2E 测试")
    except Exception:
        pytest.skip("后端服务器未运行在 localhost:8000，跳过 E2E 测试")


@pytest.fixture(scope="session")
def admin_token(server_available):
    """管理员登录获取 Token"""
    code, body = api_request("POST", "/api/auth/login", data={
        "student_id": "admin",
        "password": "admin123",
    })
    assert code == 200, f"管理员登录失败: {code} {body}"
    assert body["role"] == "admin"
    return body["access_token"]


@pytest.fixture(scope="session")
def test_student(server_available, admin_token):
    """创建测试学生并登录，返回 (student_id, password, token, db_id)"""
    sid = f"e2e_{int(time.time())}"
    password = "test123"

    # 创建学生
    code, body = api_request("POST", "/api/admin/students", token=admin_token, data={
        "student_id": sid,
        "name": "E2E\u6d4b\u8bd5\u5b66\u751f",
        "password": password,
    })
    assert code == 201, f"创建测试学生失败: {code} {body}"

    # 登录
    code, body = api_request("POST", "/api/auth/login", data={
        "student_id": sid,
        "password": password,
    })
    assert code == 200, f"学生登录失败: {code} {body}"
    student_db_id = body.get("id") or body.get("access_token")  # fallback

    # 获取用户信息拿到 id
    code2, body2 = api_request("GET", "/api/auth/me", token=body["access_token"])
    student_db_id = body2.get("id")

    yield {
        "student_id": sid,
        "password": password,
        "token": body["access_token"],
        "db_id": student_db_id,
    }

    # 清理：删除测试学生
    if student_db_id:
        api_request("DELETE", f"/api/admin/students/{student_db_id}", token=admin_token)
