"""百炼 OpenAI 兼容模式客户端工厂

qwen3.5+ 系列模型（含 qwen3.7-flash/plus/max）在 DashScope 原生 SDK 中
需使用 MultiModalConversation 接口；为统一调用方式、避免端点不匹配，
全项目改用 OpenAI 兼容端点（一个 base_url 通吃所有模型）。

文档：https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope
"""
from openai import OpenAI

from app.config import get_settings

# 百炼 OpenAI 兼容端点（华北2-北京，旧域名仍可正常使用）
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def create_client(model_name: str | None = None) -> OpenAI:
    """创建 OpenAI 兼容客户端，按模型名路由厂商（每次调用读取最新配置）

    - glm 开头的模型 → 智谱开放平台自有端点（用户自购资源包）
    - 其余 → 百炼 OpenAI 兼容端点
    model_name 为空时（历史调用方式）一律走百炼。
    """
    if model_name and model_name.lower().startswith("glm"):
        settings = get_settings()
        return OpenAI(
            api_key=settings.ZHIPU_API_KEY,
            base_url=settings.ZHIPU_BASE_URL,
        )
    return OpenAI(
        api_key=get_settings().DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL,
    )


def completion_extra(model_name: str | None) -> dict:
    """关闭思考模式的请求参数，按厂商分：

    - 百炼（通义/DeepSeek）：enable_thinking=False
    - 智谱 GLM（4.5+）：thinking.type=disabled；enable_thinking 是 DashScope
      私有参数，智谱端点不认。⚠️ GLM-5.3 强制思考、传 disabled 直接请求失败，
      智谱只能用 5.2 及以下（AGENTS.md §6）
    """
    if model_name and model_name.lower().startswith("glm"):
        return {"thinking": {"type": "disabled"}}
    return {"enable_thinking": False}
