"""分用途配模型测试（v4.1 B3，纯函数，不依赖数据库）

现状是对话/判卷/画像共用 `get_active_model()`，加上 v4.1 新增的 verify 与既有 OCR，
五个用途的敏感度与调用量完全不同，共用必然是错的。

约定：**环境变量为空串 = 跟随后台激活模型**，即不填就跟改造前一模一样。
"""
import pytest

from app.config import get_settings
from app.llm import store as llm_store


@pytest.fixture
def active(monkeypatch):
    """打桩后台激活模型，避开 get_active_model 的数据库查询"""
    monkeypatch.setattr(llm_store, "get_active_model", lambda: "active-model")


@pytest.fixture
def overrides(monkeypatch):
    """设置 JUDGE_MODEL / PROFILE_MODEL / VERIFY_MODEL 三个环境变量"""
    def _apply(**kwargs):
        for field, value in kwargs.items():
            monkeypatch.setattr(get_settings(), field, value)
    return _apply


class TestGetModelFor:

    @pytest.mark.parametrize("task_type", ["judge", "profile", "verify"])
    def test_empty_override_follows_active_model(self, active, overrides, task_type):
        """默认（空串）行为与改造前逐字一致：跟随后台激活模型"""
        overrides(JUDGE_MODEL="", PROFILE_MODEL="", VERIFY_MODEL="")
        assert llm_store.get_model_for(task_type) == "active-model"

    def test_judge_override(self, active, overrides):
        overrides(JUDGE_MODEL="qwen3.7-plus", PROFILE_MODEL="", VERIFY_MODEL="")
        assert llm_store.get_model_for("judge") == "qwen3.7-plus"

    def test_profile_override(self, active, overrides):
        overrides(JUDGE_MODEL="", PROFILE_MODEL="qwen3.7-flash", VERIFY_MODEL="")
        assert llm_store.get_model_for("profile") == "qwen3.7-flash"

    def test_verify_override(self, active, overrides):
        overrides(JUDGE_MODEL="", PROFILE_MODEL="", VERIFY_MODEL="cheap-flash")
        assert llm_store.get_model_for("verify") == "cheap-flash"

    def test_overrides_are_independent(self, active, overrides):
        overrides(JUDGE_MODEL="judge-m", PROFILE_MODEL="profile-m", VERIFY_MODEL="verify-m")
        assert llm_store.get_model_for("judge") == "judge-m"
        assert llm_store.get_model_for("profile") == "profile-m"
        assert llm_store.get_model_for("verify") == "verify-m"

    def test_whitespace_only_override_treated_as_empty(self, active, overrides):
        """.env 里误填空格不得变成一个名叫「 」的模型"""
        overrides(JUDGE_MODEL="   ", PROFILE_MODEL="", VERIFY_MODEL="")
        assert llm_store.get_model_for("judge") == "active-model"

    @pytest.mark.parametrize("task_type", ["chat", "ocr", "unknown", ""])
    def test_unmapped_task_type_follows_active_model(self, active, overrides, task_type):
        """chat 与 ocr 有意不做覆盖：对话模型由后台 active 控制，OCR 由 VISION_MODEL 控制"""
        overrides(JUDGE_MODEL="judge-m", PROFILE_MODEL="profile-m", VERIFY_MODEL="verify-m")
        assert llm_store.get_model_for(task_type) == "active-model"


class TestTaskModelFieldsDeclared:
    """config.Settings 必须真的声明这三个字段，否则 getattr 兜底会静默吞掉配置"""

    @pytest.mark.parametrize("field", ["JUDGE_MODEL", "PROFILE_MODEL", "VERIFY_MODEL"])
    def test_field_declared_as_str(self, field):
        settings = get_settings()
        assert hasattr(settings, field)
        assert isinstance(getattr(settings, field), str)
