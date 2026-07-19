# -*- coding: utf-8 -*-
"""E2E: 科目 - GET /api/subjects, POST/PUT/DELETE /api/admin/subjects"""
import time
import pytest
from tests.e2e.conftest import api_request


class TestE2ESubjectList:

    def test_list_public_for_student(self, server_available, test_student):
        """学生可查看科目列表"""
        code, body = api_request("GET", "/api/subjects", token=test_student["token"])
        assert code == 200
        assert isinstance(body, list)

    def test_list_without_token(self, server_available):
        """无 Token 返回 401 或 403"""
        code, _ = api_request("GET", "/api/subjects")
        assert code in (401, 403)


class TestE2ESubjectCRUD:

    def test_create_update_delete(self, server_available, admin_token):
        """完整生命周期：创建 → 修改 → 删除"""
        name = f"e2e_subject_{int(time.time())}"

        code, created = api_request("POST", "/api/admin/subjects", token=admin_token, data={
            "name": name,
            "category": "professional",
            "description": "E2E测试科目",
            "sort_order": 99,
        })
        assert code == 201
        subject_id = created["id"]
        assert created["category"] == "professional"

        code, updated = api_request("PUT", f"/api/admin/subjects/{subject_id}",
                                    token=admin_token, data={"description": "已更新"})
        assert code == 200
        assert updated["description"] == "已更新"

        code, _ = api_request("DELETE", f"/api/admin/subjects/{subject_id}", token=admin_token)
        assert code == 200

    def test_create_invalid_category(self, server_available, admin_token):
        """非法 category 返回 400"""
        code, _ = api_request("POST", "/api/admin/subjects", token=admin_token, data={
            "name": f"e2e_bad_{int(time.time())}",
            "category": "invalid",
        })
        assert code == 400

    def test_create_student_forbidden(self, server_available, test_student):
        """学生无权新增科目"""
        code, _ = api_request("POST", "/api/admin/subjects", token=test_student["token"], data={
            "name": "e2e_forbidden_subject",
            "category": "general",
        })
        assert code == 403
