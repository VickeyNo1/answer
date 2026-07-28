"""通义千问流式调用封装：Function Calling 两轮流程 + SSE 流式输出

第 1 轮带 search_cpa_knowledge 工具调用大模型：
- 模型直答 → 内容增量直接透传
- 模型决定检索（finish_reason=tool_calls）→ 调知识库 → 组装 tool 结果
  → 第 2 轮流式生成最终答案（最多一轮工具调用）
subject 由后端从会话上下文注入，模型只决定 query/collection/top_k。
"""
import json
import dashscope
from dashscope import Generation
from app.config import get_settings
from app.kb import client as kb_client
from app.kb.prompt import SEARCH_TOOL, format_results, collect_kp_ids


SYSTEM_PROMPT = """你是一个专业的会计答疑助手，面向会计专业学生提供准确、详细的会计知识解答。

回答要求：
1. 使用清晰的结构化格式（标题、列表、代码块等）
2. 回答要准确，引用相关会计准则和法规
3. 涉及会计准则、概念、账务处理、例题时，优先调用知识库检索工具获取资料后再回答
4. 如果检索到了知识库资料，请基于资料回答，并在回答末尾列出所依据的知识点编号
5. 如果不确定或资料不足，请诚实说明
6. 适当举例帮助理解"""


def build_messages(user_message: str, history: list[dict]) -> list[dict]:
    """构建发送给大模型的 messages 列表"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # 历史消息
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # 当前用户消息
    messages.append({"role": "user", "content": user_message})

    return messages


def stream_chat(messages: list[dict], model_name: str | None, subject: str):
    """
    Function Calling 两轮流式调用，逐块 yield 事件：
    - 正常内容: {"content": "..."}
    - 开始检索知识库: {"kb_search": True}
    - 检索结果知识点编号: {"kp_ids": [...]}
    - 结束时用量（两轮累加）: {"usage": {"prompt_tokens": int, "completion_tokens": int}}
    - 出错: {"error": "错误信息"}
    model_name 为空时回退到配置中的 CHAT_MODEL。
    """
    settings = get_settings()
    dashscope.api_key = settings.DASHSCOPE_API_KEY
    model = model_name or settings.CHAT_MODEL
    usage_acc = {"prompt_tokens": 0, "completion_tokens": 0}

    try:
        # ===== 第 1 轮：带工具流式调用 =====
        responses = Generation.call(
            model=model,
            messages=messages,
            tools=[SEARCH_TOOL],
            result_format="message",
            stream=True,
            incremental_output=True,
        )

        tool_calls: dict[int, dict] = {}  # index -> {id, name, arguments}
        finish_reason = None
        round_usage = {"in": 0, "out": 0}

        for response in responses:
            if response.status_code != 200:
                yield {"error": f"AI 模型调用失败: {response.code} - {response.message}"}
                return

            _track_usage(response, round_usage)

            choices = response.output.get("choices", [])
            if not choices:
                continue
            choice = choices[0]
            message = choice.get("message", {})

            # 内容增量直接透传
            delta = message.get("content", "")
            if delta:
                yield {"content": delta}

            # 累积 tool_calls 分片（arguments 按 index 拼接）
            for tc in message.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = tool_calls.setdefault(
                    idx, {"id": "", "name": "", "arguments": ""}
                )
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function", {})
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["arguments"] += fn["arguments"]

            if choice.get("finish_reason") and choice["finish_reason"] != "null":
                finish_reason = choice["finish_reason"]

        # 第 1 轮用量计入总量
        usage_acc["prompt_tokens"] += round_usage["in"]
        usage_acc["completion_tokens"] += round_usage["out"]

        # 模型直答，无需检索
        if finish_reason != "tool_calls" or not tool_calls:
            yield {"usage": usage_acc}
            return

        # ===== 调用知识库检索 =====
        yield {"kb_search": True}

        call = tool_calls[min(tool_calls.keys())]
        try:
            args = json.loads(call["arguments"]) if call["arguments"] else {}
        except json.JSONDecodeError:
            args = {}

        kb_data = kb_client.search(
            query=args.get("query") or (messages[-1].get("content", "") if messages else ""),
            subject=subject,  # 后端注入，不由模型决定
            collection=args.get("collection") or "textbook",
            top_k=int(args.get("top_k") or 5),
        )
        tool_result = format_results(kb_data)
        kp_ids = collect_kp_ids(kb_data)
        if kp_ids:
            yield {"kp_ids": kp_ids}

        # ===== 第 2 轮：带工具结果流式生成最终答案（不再提供工具） =====
        second_messages = messages + [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call["id"] or "call_0",
                        "type": "function",
                        "function": {
                            "name": call["name"] or "search_cpa_knowledge",
                            "arguments": call["arguments"] or "{}",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "name": call["name"] or "search_cpa_knowledge",
                "tool_call_id": call["id"] or "call_0",
                "content": tool_result,
            },
        ]

        responses = Generation.call(
            model=model,
            messages=second_messages,
            result_format="message",
            stream=True,
            incremental_output=True,
        )

        round_usage = {"in": 0, "out": 0}
        for response in responses:
            if response.status_code != 200:
                yield {"error": f"AI 模型调用失败: {response.code} - {response.message}"}
                return

            _track_usage(response, round_usage)

            choices = response.output.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("message", {}).get("content", "")
            if delta:
                yield {"content": delta}

        # 第 2 轮用量计入总量
        usage_acc["prompt_tokens"] += round_usage["in"]
        usage_acc["completion_tokens"] += round_usage["out"]
        yield {"usage": usage_acc}

    except Exception as e:
        yield {"error": f"AI 模型调用异常: {str(e)}"}


def _track_usage(response, round_usage: dict) -> None:
    """记录单轮最新的累计 usage（流式每块携带本轮累计值，取最新即本轮总量）"""
    usage = getattr(response, "usage", None)
    if not usage:
        return
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if input_tokens is not None:
        round_usage["in"] = input_tokens
    if output_tokens is not None:
        round_usage["out"] = output_tokens
