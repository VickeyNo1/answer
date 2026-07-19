# -*- coding: utf-8 -*-
"""E2E: 管理员模块 - POST/GET/PUT/DELETE /api/admin/students, POST /api/admin/students/batch, GET /api/admin/stats"""
import time
import urllib.parse
import pytest
from tests.e2e.conftest import api_request, make_multipart, make_excel_file


class TestE2EStudentCreate:

    def test_create_success(self, server_available, admin_token):
        """创建学生成功"""
        sid = f"e2e_create_{int(time.time())}"
        code, body = api_request("POST", "/api/admin/students", token=admin_token, data={
            "student_id": sid,
            "name": "E2E\u521b\u5efa\u5b66\u751f",
            "password": "pass123",
        })
        assert code == 201
        assert body["student_id"] == sid
        assert body["role"] == "student"
        # 清理
        api_request("DELETE", f"/api/admin/students/{body['id']}", token=admin_token)

    def test_create_duplicate(self, server_available, admin_token, test_student):
        """学号重复返回 400"""
        code, body = api_request("POST", "/api/admin/students", token=admin_token, data={
            "student_id": test_student["student_id"],
            "name": "\u91cd\u590d",
            "password": "pass",
        })
        assert code == 400

    def test_create_without_token(self, server_available):
        """无 Token 返回 401 或 403"""
        code, _ = api_request("POST", "/api/admin/students", data={
            "student_id": "x", "name": "x", "password": "x",
        })
        assert code in (401, 403)

    def test_create_student_forbidden(self, server_available, test_student):
        """学生创建返回 403"""
        code, _ = api_request("POST", "/api/admin/students", token=test_student["token"], data={
            "student_id": "x", "name": "x", "password": "x",
        })
        assert code == 403

    def test_create_can_login(self, server_available, admin_token):
        """创建的学生可以登录"""
        sid = f"e2e_login_{int(time.time())}"
        api_request("POST", "/api/admin/students", token=admin_token, data={
            "student_id": sid, "name": "LoginTest", "password": "pass123",
        })
        code, body = api_request("POST", "/api/auth/login", data={
            "student_id": sid, "password": "pass123",
        })
        assert code == 200
        assert body["role"] == "student"
        # 清理
        # 获取 ID
        code2, body2 = api_request("GET", f"/api/auth/me", token=body["access_token"])
        api_request("DELETE", f"/api/admin/students/{body2['id']}", token=admin_token)


class TestE2EStudentList:

    def test_list_returns_paginated(self, server_available, admin_token):
        """分页返回学生列表"""
        code, body = api_request("GET", "/api/admin/students?page=1&size=20", token=admin_token)
        assert code == 200
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "size" in body

    def test_list_pagination(self, server_available, admin_token):
        """分页参数生效"""
        code, body = api_request("GET", "/api/admin/students?page=1&size=2", token=admin_token)
        assert code == 200
        assert len(body["items"]) <= 2

    def test_list_keyword_search(self, server_available, admin_token, test_student):
        """关键字搜索"""
        keyword = urllib.parse.quote("E2E")
        code, body = api_request("GET", f"/api/admin/students?keyword={keyword}", token=admin_token)
        assert code == 200
        assert body["total"] >= 1

    def test_list_without_token(self, server_available):
        """无 Token 返回 401 或 403"""
        code, _ = api_request("GET", "/api/admin/students")
        assert code in (401, 403)

    def test_list_student_forbidden(self, server_available, test_student):
        """学生访问返回 403"""
        code, _ = api_request("GET", "/api/admin/students", token=test_student["token"])
        assert code == 403


class TestE2EStudentUpdate:

    def test_update_name(self, server_available, admin_token, test_student):
        """修改学生姓名"""
        code, body = api_request("PUT", f"/api/admin/students/{test_student['db_id']}",
                                 token=admin_token, data={"name": "E2E\u6539\u540d"})
        assert code == 200
        assert body["name"] == "E2E\u6539\u540d"

    def test_update_password(self, server_available, admin_token, test_student):
        """重置密码后可以用新密码登录"""
        api_request("PUT", f"/api/admin/students/{test_student['db_id']}",
                    token=admin_token, data={"password": "newpass999"})
        code, body = api_request("POST", "/api/auth/login", data={
            "student_id": test_student["student_id"],
            "password": "newpass999",
        })
        assert code == 200
        # 更新 fixture 中的密码
        test_student["password"] = "newpass999"

    def test_update_not_found(self, server_available, admin_token):
        """修改不存在的学生返回 404"""
        code, _ = api_request("PUT", "/api/admin/students/99999", token=admin_token,
                              data={"name": "x"})
        assert code == 404


class TestE2EStudentDelete:

    def test_delete_success(self, server_available, admin_token):
        """删除学生成功"""
        sid = f"e2e_del_{int(time.time())}"
        code, body = api_request("POST", "/api/admin/students", token=admin_token, data={
            "student_id": sid, "name": "DelTest", "password": "pass",
        })
        code2, body2 = api_request("DELETE", f"/api/admin/students/{body['id']}", token=admin_token)
        assert code2 == 200

    def test_delete_not_found(self, server_available, admin_token):
        """删除不存在的学生返回 404"""
        code, _ = api_request("DELETE", "/api/admin/students/99999", token=admin_token)
        assert code == 404

    def test_delete_student_forbidden(self, server_available, test_student):
        """学生删除返回 403"""
        code, _ = api_request("DELETE", "/api/admin/students/1", token=test_student["token"])
        assert code == 403


class TestE2EStudentBatch:

    def test_batch_success(self, server_available, admin_token):
        """批量导入成功"""
        sid1 = f"batch_{int(time.time())}"
        sid2 = f"batch_{int(time.time())+1}"
        excel_bytes = make_excel_file([
            [sid1, "\u6279\u91cf\u4e00", "pass1"],
            [sid2, "\u6279\u91cf\u4e8c", "pass2"],
        ])
        boundary, body = make_multipart("batch.xlsx", excel_bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        code, resp = api_request("POST", "/api/admin/students/batch", token=admin_token,
            raw_body=body, content_type=f"multipart/form-data; boundary={boundary}")
        assert code == 200
        assert resp["success"] == 2
        assert resp["failed"] == 0
        # 清理
        for s in [sid1, sid2]:
            code2, body2 = api_request("GET",
                f"/api/admin/students?keyword={urllib.parse.quote(s)}", token=admin_token)
            if body2.get("items"):
                api_request("DELETE", f"/api/admin/students/{body2['items'][0]['id']}", token=admin_token)

    def test_batch_without_token(self, server_available):
        """无 Token 返回 401 或 403"""
        boundary, body = make_multipart("batch.xlsx", b"fake", "application/octet-stream")
        code, _ = api_request("POST", "/api/admin/students/batch",
            raw_body=body, content_type=f"multipart/form-data; boundary={boundary}")
        assert code in (401, 403)


class TestE2EAdminStats:

    def test_stats_success(self, server_available, admin_token):
        """获取统计数据成功"""
        code, body = api_request("GET", "/api/admin/stats", token=admin_token)
        assert code == 200
        assert "total_students" in body
        assert "total_conversations" in body
        assert "today_active_users" in body

    def test_stats_types(self, server_available, admin_token):
        """统计数据类型正确"""
        code, body = api_request("GET", "/api/admin/stats", token=admin_token)
        assert isinstance(body["total_students"], int)
        assert isinstance(body["total_conversations"], int)
        assert isinstance(body["today_active_users"], int)

    def test_stats_student_forbidden(self, server_available, test_student):
        """学生访问统计返回 403"""
        code, _ = api_request("GET", "/api/admin/stats", token=test_student["token"])
        assert code == 403

    def test_stats_without_token(self, server_available):
        """无 Token 返回 401 或 403"""
        code, _ = api_request("GET", "/api/admin/stats")
        assert code in (401, 403)
