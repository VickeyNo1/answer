# -*- coding: utf-8 -*-
"""E2E 端到端测试包

与 tests/ 下的单元测试不同，这些测试需要后端服务器实际运行在 localhost:8000。
运行方式：
    uv run pytest tests/e2e/ -v -s

前置条件：
    1. 后端已启动: uv run uvicorn app.main:app --port 8000
    2. (可选) 前端已启动: cd frontend && npm run dev  (用于前端页面检查)
"""
