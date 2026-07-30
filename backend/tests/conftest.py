# -*- coding: utf-8 -*-
"""共享测试 fixtures

使用独立的 MySQL 测试库（MYSQL_DB=answer_test）。
MySQL 不可达时整体 skip，不影响本地无数据库环境。
在导入 app 之前设置测试环境变量。
"""
import os
import sys

# ---- 设置测试环境变量（必须在导入 app 之前）----
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(TEST_DIR)

# 使用独立测试库，避免污染开发库
os.environ["MYSQL_DB"] = "answer_test"
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")

# 将 backend 加入 sys.path
sys.path.insert(0, BACKEND_DIR)

import pytest
import bcrypt
import pymysql
from fastapi.testclient import TestClient

from app.config import get_settings

# ---- 清理缓存，确保测试环境变量生效 ----
get_settings.cache_clear()


def _mysql_available() -> bool:
    """探测 MySQL 是否可达（不带库名，避免库不存在导致误判）"""
    s = get_settings()
    try:
        conn = pymysql.connect(
            host=s.MYSQL_HOST, port=s.MYSQL_PORT,
            user=s.MYSQL_USER, password=s.MYSQL_PASSWORD,
            charset="utf8mb4", connect_timeout=5,
        )
        conn.close()
        return True
    except Exception:
        return False


# MySQL 是否可达（不可达时所有 DB 相关测试整体 skip）
MYSQL_OK = _mysql_available()


from app.database import init_db, get_db_ctx
from app.settings_store import SETTING_DEFAULTS
from app.auth.jwt_handler import create_access_token
from app.main import app


@pytest.fixture(scope="session")
def settings():
    """返回测试环境配置"""
    return get_settings()


def _drop_test_db():
    """删除测试库（teardown 清理）"""
    s = get_settings()
    conn = pymysql.connect(
        host=s.MYSQL_HOST, port=s.MYSQL_PORT,
        user=s.MYSQL_USER, password=s.MYSQL_PASSWORD,
        charset="utf8mb4", connect_timeout=5,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{s.MYSQL_DB}`")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """会话级：重建测试库 + 建表 + 创建 admin 和 student 账号

    MySQL 不可达时整体 skip。
    """
    if not MYSQL_OK:
        pytest.skip("MySQL 不可达，跳过需要数据库的测试")

    # 先清理旧测试库，确保 AUTO_INCREMENT 从 1 开始
    _drop_test_db()

    # 建库建表
    init_db()

    # 创建 admin(id=1) 和 student(id=2) 账号
    with get_db_ctx() as db:
        admin_hash = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode("utf-8")
        student_hash = bcrypt.hashpw(b"student123", bcrypt.gensalt()).decode("utf-8")

        db.execute(
            "INSERT INTO users (student_id, password_hash, name, role) VALUES (%s, %s, %s, 'admin')",
            ("admin", admin_hash, "管理员"),
        )
        db.execute(
            "INSERT INTO users (student_id, password_hash, name, role) VALUES (%s, %s, %s, 'student')",
            ("2024001", student_hash, "测试学生"),
        )

        # 幂等写入全局设置初始键值（与 seed.py 一致，供设置/配额相关测试使用）
        for key, value in SETTING_DEFAULTS.items():
            db.execute(
                "INSERT INTO app_settings (setting_key, setting_value) VALUES (%s, %s)",
                (key, str(value)),
            )
        db.commit()

    yield

    # 会话结束后清理测试库
    _drop_test_db()


@pytest.fixture(scope="session")
def client(setup_database):
    """FastAPI 测试客户端"""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token():
    """管理员 JWT Token"""
    return create_access_token(user_id=1, role="admin")


@pytest.fixture(scope="session")
def student_token():
    """学生 JWT Token"""
    return create_access_token(user_id=2, role="student")


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    """管理员请求头"""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def student_headers(student_token):
    """学生请求头"""
    return {"Authorization": f"Bearer {student_token}"}


# ========== 考试相关（v4.0 M2） ==========

def make_question(question_id: str, question_type: str = "单选",
                  answer: str | None = "B", kp_ids: list[str] | None = None,
                  **extra) -> dict:
    """构造知识库抽题返回的题目（结构见 doc/知识库对接文档.md §1.4）"""
    question = {
        "question_id": question_id,
        "question_type": question_type,
        "chapter_id": "ACC-01",
        "chapter": "第一章 总论",
        "knowledge_point_ids": ["ACC-01-03-01"] if kp_ids is None else kp_ids,
        "stem": f"题干 {question_id}",
        "options": {"A": "甲", "B": "乙", "C": "丙", "D": "丁"},
        "answer": answer,
        "explanation": f"解析 {question_id}",
        "materials": None,
        "sub_questions": None,
    }
    if question_type in ("计算", "综合"):
        question["stem"] = None
        question["options"] = None
        question["materials"] = f"资料 {question_id}"
        question["sub_questions"] = ["要求1", "要求2"]
    question.update(extra)
    return question


@pytest.fixture
def fake_draw(monkeypatch):
    """mock 知识库抽题：fake_draw(questions) 后创卷返回这些题，返回调用参数记录列表

    也可传异常实例/类，创卷时抛出（覆盖 KbDrawError 降级路径）。
    """
    def _apply(questions):
        calls: list[dict] = []

        def _draw(subject, chapter_ids, counts):
            calls.append({"subject": subject, "chapter_ids": chapter_ids, "counts": counts})
            if isinstance(questions, BaseException) or (
                isinstance(questions, type) and issubclass(questions, BaseException)
            ):
                raise questions
            return questions

        monkeypatch.setattr("app.kb.client.draw_exam", _draw)
        return calls

    return _apply


@pytest.fixture
def clean_exams():
    """考试测试隔离：用例前后清空考试数据（「每人仅 1 张 ongoing」会互相干扰）"""
    def _clear():
        with get_db_ctx() as db:
            db.execute("DELETE FROM exam_answers")
            db.execute("DELETE FROM exams")
            db.commit()

    _clear()
    yield
    _clear()


@pytest.fixture(autouse=True)
def bg_grading_calls(monkeypatch):
    """拦截交卷后的后台判卷任务，避免测试真调 dashscope

    返回被提交判卷的 exam_id 列表供断言；需要验证判卷流程的用例
    在 mock 掉 judger._call_llm 后同步调 judger.grade_exam(exam_id)。
    """
    calls: list[int] = []
    monkeypatch.setattr("app.exam.judger.submit_grading", calls.append)
    return calls


@pytest.fixture
def fake_llm(monkeypatch):
    """mock 判卷大模型：fake_llm([...]) 按顺序返回每次调用的结果

    每项可为 (文本, input_tokens, output_tokens) 或异常实例（抛出以覆盖重试路径）；
    用尽后循环使用最后一项。返回收到的 prompt 列表。
    """
    def _apply(script):
        prompts: list[str] = []

        def _call(model, prompt):
            prompts.append(prompt)
            item = script[min(len(prompts) - 1, len(script) - 1)]
            if isinstance(item, BaseException):
                raise item
            return item

        monkeypatch.setattr("app.exam.judger._call_llm", _call)
        return prompts

    return _apply
