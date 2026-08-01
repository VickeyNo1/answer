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


def create_client() -> OpenAI:
    """创建百炼 OpenAI 兼容客户端（每次调用读取最新配置）"""
    return OpenAI(
        api_key=get_settings().DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL,
    )
