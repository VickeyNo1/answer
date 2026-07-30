# -*- coding: utf-8 -*-
"""记忆注入测试：build_messages 带/不带 memory_block + 开关关时不注入（设计 §5.3）"""
import pytest

from app.chat.qwen_service import build_messages, SYSTEM_PROMPT
from app.database import get_db_ctx
from app.profile import store as profile_store
from tests.conftest import make_wrong_question


pytestmark = pytest.mark.usefixtures("clean_profile", "clean_exams")


class TestBuildMessages:
    def test_without_memory_block(self):
        """无 memory_block 时 system prompt 不变"""
        messages = build_messages("什么是折旧？", [])
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == SYSTEM_PROMPT
        assert messages[-1] == {"role": "user", "content": "什么是折旧？"}

    def test_with_memory_block(self):
        """有 memory_block 时追加到 system prompt 末尾"""
        block = "【学生情况】\n薄弱知识点: ACC-01(掌握50%,错2题)"
        messages = build_messages("什么是折旧？", [], memory_block=block)
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == SYSTEM_PROMPT + "\n\n" + block
        assert messages[-1] == {"role": "user", "content": "什么是折旧？"}

    def test_with_none_memory_block(self):
        """memory_block=None 时与不带参数行为一致"""
        messages = build_messages("hi", [], memory_block=None)
        assert messages[0]["content"] == SYSTEM_PROMPT

    def test_with_empty_memory_block(self):
        """memory_block='' 时不追加（falsy 不追加）"""
        messages = build_messages("hi", [], memory_block="")
        assert messages[0]["content"] == SYSTEM_PROMPT

    def test_history_preserved_with_memory_block(self):
        """有 memory_block 时历史消息仍正常拼接"""
        history = [
            {"role": "user", "content": "什么是资产？"},
            {"role": "assistant", "content": "资产是企业拥有的经济资源。"},
        ]
        messages = build_messages("什么是折旧？", history, memory_block="记忆块")
        assert len(messages) == 4  # system + 2 history + user
        assert messages[0]["role"] == "system"
        assert "记忆块" in messages[0]["content"]
        assert messages[1] == {"role": "user", "content": "什么是资产？"}
        assert messages[2] == {"role": "assistant", "content": "资产是企业拥有的经济资源。"}
        assert messages[3] == {"role": "user", "content": "什么是折旧？"}


class TestBuildMemoryBlockSwitchOff:
    """开关关时 build_memory_block 返回 None（不注入）"""

    def test_switch_off_returns_none(self, monkeypatch):
        """记忆开关关闭时，即使有数据也不注入"""
        # 先造一些数据
        make_wrong_question(2, "Q-001")
        with get_db_ctx() as db:
            profile_store.upsert_profile(db, 2, "偏好分录示例讲解")

        # 关闭记忆开关
        monkeypatch.setattr(
            "app.profile.store.get_effective_memory_enabled",
            lambda user: False,
        )

        with get_db_ctx() as db:
            block = profile_store.build_memory_block(db, 2, {"id": 2, "role": "student"})
        assert block is None

    def test_switch_on_returns_block(self, monkeypatch):
        """记忆开关开启且有数据时正常注入"""
        # build_memory_block 读 profile/exam/weak_kps，不直接读 wrong_questions
        with get_db_ctx() as db:
            profile_store.upsert_profile(db, 2, "偏好分录示例讲解，概念辨析题易错。")
        monkeypatch.setattr(
            "app.profile.store.get_effective_memory_enabled",
            lambda user: True,
        )
        with get_db_ctx() as db:
            block = profile_store.build_memory_block(db, 2, {"id": 2, "role": "student"})
        assert block is not None
        assert "【学生情况】" in block
        assert "偏好分录示例讲解" in block
