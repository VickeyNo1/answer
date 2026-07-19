"""通义千问流式调用封装：通过 dashscope SDK 实现 SSE 流式输出"""
import json
import dashscope
from dashscope import Generation
from app.config import get_settings


SYSTEM_PROMPT = """你是一个专业的会计答疑助手，面向会计专业学生提供准确、详细的会计知识解答。

回答要求：
1. 使用清晰的结构化格式（标题、列表、代码块等）
2. 回答要准确，引用相关会计准则和法规
3. 如果提供了参考资料，请基于参考资料回答
4. 如果不确定或资料不足，请诚实说明
5. 适当举例帮助理解"""


def build_messages(
    user_message: str,
    history: list[dict],
    context: list[str] | None = None,
) -> list[dict]:
    """构建发送给大模型的 messages 列表"""
    messages = []

    # 系统提示词
    system_content = SYSTEM_PROMPT
    if context:
        refs = "\n\n".join([f"【参考{i+1}】{c}" for i, c in enumerate(context)])
        system_content += f"\n\n以下是从知识库中检索到的参考资料，请优先基于这些资料回答：\n{refs}"

    messages.append({"role": "system", "content": system_content})

    # 历史消息
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # 当前用户消息
    messages.append({"role": "user", "content": user_message})

    return messages


def stream_chat(messages: list[dict], model_name: str | None = None):
    """
    流式调用大模型，逐块 yield 文本内容。
    - 正常内容: yield {"content": "..."}
    - 结束时用量: yield {"usage": {"prompt_tokens": int, "completion_tokens": int}}
    - 出错: yield {"error": "错误信息"}
    model_name 为空时回退到配置中的 CHAT_MODEL。
    """
    settings = get_settings()
    dashscope.api_key = settings.DASHSCOPE_API_KEY
    model = model_name or settings.CHAT_MODEL

    try:
        responses = Generation.call(
            model=model,
            messages=messages,
            result_format="message",
            stream=True,
            incremental_output=True,
        )

        prompt_tokens = 0
        completion_tokens = 0

        for response in responses:
            if response.status_code != 200:
                yield {"error": f"AI 模型调用失败: {response.code} - {response.message}"}
                return

            # 捕获用量（最后一个块携带累计 usage）
            usage = getattr(response, "usage", None)
            if usage:
                prompt_tokens = usage.get("input_tokens", prompt_tokens) or prompt_tokens
                completion_tokens = usage.get("output_tokens", completion_tokens) or completion_tokens

            choices = response.output.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("message", {}).get("content", "")
            if delta:
                yield {"content": delta}

        yield {"usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}}

    except Exception as e:
        yield {"error": f"AI 模型调用异常: {str(e)}"}
