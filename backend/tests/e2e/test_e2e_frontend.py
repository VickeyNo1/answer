# -*- coding: utf-8 -*-
"""E2E: 前端页面编译验证 - 检查 Next.js 三个页面返回 200"""
import pytest
from tests.e2e.conftest import check_frontend_page


class TestE2EFrontend:

    def test_login_page(self, server_available):
        """登录页可访问"""
        code, length = check_frontend_page("/login")
        if code == 0:
            pytest.skip("\u524d\u7aef\u672a\u8fd0\u884c\u5728 localhost:3000")
        assert code == 200
        assert length > 1000

    def test_home_page(self, server_available):
        """对话主页可访问"""
        code, length = check_frontend_page("/")
        if code == 0:
            pytest.skip("\u524d\u7aef\u672a\u8fd0\u884c\u5728 localhost:3000")
        assert code == 200
        assert length > 1000

    def test_admin_page(self, server_available):
        """管理后台可访问"""
        code, length = check_frontend_page("/admin")
        if code == 0:
            pytest.skip("\u524d\u7aef\u672a\u8fd0\u884c\u5728 localhost:3000")
        assert code == 200
        assert length > 1000
