# -*- coding: utf-8 -*-
"""画像总结器测试：LLM mock 验证成功/失败/截断/记账（设计 §5.6）"""
import json
import pytest

from app.database import get_db_ctx
from app.profile import store as profile_store, summarizer
from tests.conftest import make_question

pytestmark = pytest.mark.usefixtures("clean_profile", "clean_exams")


def _create_dialog(user_id, n=5):
    """造 n 轮对话（user + assistant 各一条）"""
    with get_db_ctx() as db:
        cursor = db.execute(
            "INSERT INTO conversations (user_id, title, subject) VALUES (%s, 'test', 'cpa_acc')",
            (user_id,),
        )
        conv_id = cursor.lastrowid
        for i in range(n):
            db.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)",
                (conv_id, f"什么是第{i+1}章内容？"),
            )
            db.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'assistant', %s)",
                (conv_id, f"第{i+1}章讲解的是会计基础概念{i+1}。"),
            )
        db.commit()


class TestBuildSummaryPrompt:
    def test_assembles_history(self):
        history = [
            {"role": "user", "content": "什么是折旧？"},
            {"role": "assistant", "content": "折旧是固定资产在使用过程中的价值分摊。"},
        ]
        prompt = summarizer.build_summary_prompt(history)
        assert "学生: 什么是折旧？" in prompt
        assert "老师: 折旧是" in prompt

    def test_truncates_to_40(self):
        history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg{i}"} for i in range(50)]
        prompt = summarizer.build_summary_prompt(history)
        lines = prompt.strip().split("\n")
        assert len(lines) == 40  # 只保留最近 40 条
        assert "msg49" in lines[-1]  # 最后一条
        assert "msg10" in lines[0]   # 最近 40 条的第一条（索引 10）


class TestSummarizeProfile:
    def test_success(self, monkeypatch):
        """LLM 成功→画像写入 + 计数清零"""
        _create_dialog(2, 5)
        with get_db_ctx() as db:
            profile_store.increment_dialog_count(db, 2)
            profile_store.increment_dialog_count(db, 2)

        monkeypatch.setattr(
            "app.profile.summarizer._call_llm",
            lambda model, prompt: ("偏好分录示例讲解，概念辨析题易错。", 100, 50),
        )
        summarizer.summarize_profile(2)

        with get_db_ctx() as db:
            row = profile_store.get_profile(db, 2)
        assert row["style_profile"] == "偏好分录示例讲解，概念辨析题易错。"
        assert int(row["dialog_count_since_update"]) == 0

    def test_truncates_to_200_chars(self, monkeypatch):
        """画像文本截断到 200 字符"""
        _create_dialog(2, 1)
        long_text = "画像" * 200  # 400 字符
        monkeypatch.setattr(
            "app.profile.summarizer._call_llm",
            lambda model, prompt: (long_text, 100, 50),
        )
        summarizer.summarize_profile(2)

        with get_db_ctx() as db:
            row = profile_store.get_profile(db, 2)
        assert len(row["style_profile"]) == 200

    def test_llm_failure_silent(self, monkeypatch):
        """LLM 失败→静默放弃，不抛异常，计数仍清零"""
        _create_dialog(2, 1)
        with get_db_ctx() as db:
            profile_store.increment_dialog_count(db, 2)

        def _fail(model, prompt):
            raise RuntimeError("网络超时")

        monkeypatch.setattr("app.profile.summarizer._call_llm", _fail)
        summarizer.summarize_profile(2)  # 不抛异常

        with get_db_ctx() as db:
            row = profile_store.get_profile(db, 2)
        # 画像未写入（NULL），但计数已清零
        assert row["style_profile"] is None
        assert int(row["dialog_count_since_update"]) == 0

    def test_no_history_skips(self, monkeypatch):
        """无对话历史→跳过总结"""
        called = []
        monkeypatch.setattr(
            "app.profile.summarizer._call_llm",
            lambda model, prompt: called.append(prompt) or ("画像", 1, 1),
        )
        summarizer.summarize_profile(2)
        assert len(called) == 0  # LLM 未被调用

    def test_task_type_profile_billing(self, monkeypatch):
        """画像总结按 task_type='profile' 记账"""
        _create_dialog(2, 1)
        recorded = []
        monkeypatch.setattr(
            "app.profile.summarizer._call_llm",
            lambda model, prompt: ("画像文本", 100, 50),
        )
        monkeypatch.setattr(
            "app.llm.store.record_usage",
            lambda *a, **kw: recorded.append({"args": a, "kw": kw}),
        )
        summarizer.summarize_profile(2)
        assert len(recorded) == 1
        assert recorded[0]["kw"].get("task_type") == "profile"
