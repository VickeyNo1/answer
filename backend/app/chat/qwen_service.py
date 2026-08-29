"""通义千问流式调用封装：Function Calling 两轮流程 + SSE 流式输出

使用百炼 OpenAI 兼容端点（app/llm/client.py），统一支持所有模型。

第 1 轮带 search_cpa_knowledge 工具调用大模型：
- 模型直答 → 内容增量直接透传
- 模型决定检索（finish_reason=tool_calls）→ 调知识库 → 组装 tool 结果
  → 第 2 轮流式生成最终答案（最多一轮工具调用）
subject 由后端从会话上下文注入，模型只决定 query/collection/top_k。
"""
import json

from app.config import get_settings
from app.llm.client import create_client
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

# 追问建议指令（仅追加到二轮回答的 system prompt 末尾，见设计文档 §3.3）
SUGGESTIONS_DELIMITER = "===SUGGESTIONS==="
SUGGESTIONS_INSTRUCTION = (
    "\n\n回答完成后，另起一行输出固定分隔行 " + SUGGESTIONS_DELIMITER
    + " ，然后在下一行输出一个 JSON 数组，包含 3 条学生可能想继续追问的问题"
    "（每条不超过 20 字），分隔行之后除 JSON 数组外不要输出任何内容。"
)

# 降级话术分档（附在答案尾部，随正文落库）
DEGRADED_SUFFIX = "\n\n> ⚠️ 知识库暂时不可用，本回答未经教材核对。"
EMPTY_SUFFIX = "\n\n> 知识库中未检索到直接相关内容。"

# 图片题目识别（方案 B）：仅转录，不解答；模型由 VISION_MODEL 配置
OCR_USER_PROMPT = (
    "请完整、准确地识别并转录图片中的会计题目文字，包括题干、选项、材料、要求等，"
    "保持原有结构与格式，只输出转录文本，不要解答、不要额外解释。"
)


def extract_question_text(image_base64: str, model_name: str | None = None) -> str:
    """单次非流式视觉调用，识别图片中的题目文字（方案 B OCR 步骤）"""
    settings = get_settings()
    model = model_name or settings.VISION_MODEL
    client = create_client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": [
                {"type": "text", "text": OCR_USER_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
            ]},
        ],
        extra_body={"enable_thinking": False},
    )
    return (resp.choices[0].message.content or "").strip()


def build_messages(user_message: str, history: list[dict],
                   memory_block: str | None = None) -> list[dict]:
    """构建发送给大模型的 messages 列表

    memory_block 非空时追加到 system prompt 末尾（M3 学生记忆注入）。
    """
    system_content = SYSTEM_PROMPT
    if memory_block:
        system_content = system_content + "\n\n" + memory_block
    messages = [{"role": "system", "content": system_content}]

    # 历史消息
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # 当前用户消息
    messages.append({"role": "user", "content": user_message})

    return messages


def stream_chat(
    messages: list[dict],
    model_name: str | None,
    subject: str,
    user_id: int = 0,
    conversation_id: int | None = None,
):
    """
    Function Calling 两轮流式调用，逐块 yield 事件：
    - 正常内容: {"content": "..."}
    - 开始检索知识库: {"kb_search": True}
    - 检索命中引用摘要: {"kb_refs": [...]}
    - 检索结果知识点编号: {"kp_ids": [...]}
    - 追问建议: {"suggestions": [...]}（解析失败静默不发）
    - 结束时用量（两轮累加）: {"usage": {"prompt_tokens": int, "completion_tokens": int}}
    - 出错: {"error": "错误信息"}
    model_name 为空时回退到配置中的 CHAT_MODEL。
    user_id/conversation_id 仅用于 kb_search_logs 落库。
    """
    settings = get_settings()
    model = model_name or settings.CHAT_MODEL
    usage_acc = {"prompt_tokens": 0, "completion_tokens": 0}

    try:
        client = create_client()

        # ===== 第 1 轮：带工具流式调用 =====
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=[SEARCH_TOOL],
            stream=True,
            extra_body={"enable_thinking": False},
        )

        tool_calls: dict[int, dict] = {}  # index -> {id, name, arguments}
        finish_reason = None
        round_usage = {"in": 0, "out": 0}

        for chunk in stream:
            if not chunk.choices:
                _track_usage(chunk, round_usage)
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            # 内容增量直接透传
            if delta and delta.content:
                yield {"content": delta.content}

            # 累积 tool_calls 分片（arguments 按 index 拼接）
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    slot = tool_calls.setdefault(
                        idx, {"id": "", "name": "", "arguments": ""}
                    )
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] = tc.function.name
                        if tc.function.arguments:
                            slot["arguments"] += tc.function.arguments

            if choice.finish_reason:
                finish_reason = choice.finish_reason
            _track_usage(chunk, round_usage)

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
            user_id=user_id,
            conversation_id=conversation_id,
        )
        tool_result = format_results(kb_data)
        kp_ids = collect_kp_ids(kb_data)
        if kp_ids:
            yield {"kp_ids": kp_ids}

        # 检索命中 → 下发引用卡片摘要（snippet 为 content 前 100 字符）
        results = (kb_data or {}).get("results") or []
        if results:
            yield {"kb_refs": [
                {
                    "kp_id": (r.get("knowledge_point_ids") or [""])[0],
                    "chapter": r.get("chapter", ""),
                    "title": r.get("title", ""),
                    "snippet": (r.get("content") or "")[:100],
                }
                for r in results
            ]}

        # 降级话术分档：检索服务不可用 / 检索成功但空结果
        if kb_data is None:
            kb_suffix = DEGRADED_SUFFIX
        elif not results:
            kb_suffix = EMPTY_SUFFIX
        else:
            kb_suffix = ""

        # ===== 第 2 轮：带工具结果流式生成最终答案（不再提供工具） =====
        # 二轮 system prompt 末尾追加追问建议指令（不改动原 messages）
        second_messages = [dict(messages[0])] + messages[1:] if messages else []
        if second_messages and second_messages[0].get("role") == "system":
            second_messages[0]["content"] = (
                second_messages[0]["content"] + SUGGESTIONS_INSTRUCTION
            )
        second_messages = second_messages + [
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
                "tool_call_id": call["id"] or "call_0",
                "content": tool_result,
            },
        ]

        stream = client.chat.completions.create(
            model=model,
            messages=second_messages,
            stream=True,
            extra_body={"enable_thinking": False},
        )

        round_usage = {"in": 0, "out": 0}
        # 追问建议解析：缓冲尾部内容，检测分隔行后从正文剔除建议段
        holdback = ""
        collecting_suggestions = False
        suggestions_text = ""
        # 分隔行可能跨块到达，保留足够尾部再下发
        keep_len = len(SUGGESTIONS_DELIMITER) + 2

        for chunk in stream:
            if not chunk.choices:
                _track_usage(chunk, round_usage)
                continue
            delta = chunk.choices[0].delta
            content = delta.content if delta else None
            if not content:
                _track_usage(chunk, round_usage)
                continue
            if collecting_suggestions:
                suggestions_text += content
                continue
            holdback += content
            if SUGGESTIONS_DELIMITER in holdback:
                before, after = holdback.split(SUGGESTIONS_DELIMITER, 1)
                before = before.rstrip()
                if before:
                    yield {"content": before}
                collecting_suggestions = True
                suggestions_text = after
                holdback = ""
            elif len(holdback) > keep_len:
                yield {"content": holdback[:-keep_len]}
                holdback = holdback[-keep_len:]
            _track_usage(chunk, round_usage)

        # 刷库存尾部正文 + 附降级话术
        if not collecting_suggestions and holdback:
            yield {"content": holdback}
        if kb_suffix:
            yield {"content": kb_suffix}

        # 解析追问建议（失败静默降级，不影响正文）
        if collecting_suggestions:
            items = _parse_suggestions(suggestions_text)
            if items:
                yield {"suggestions": items}

        # 第 2 轮用量计入总量
        usage_acc["prompt_tokens"] += round_usage["in"]
        usage_acc["completion_tokens"] += round_usage["out"]
        yield {"usage": usage_acc}

    except Exception as e:
        yield {"error": f"AI 模型调用异常: {str(e)}"}


def _parse_suggestions(text: str) -> list[str]:
    """从分隔行后的文本中解析 JSON 数组（解析失败返回空列表）"""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        items = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    return [str(item) for item in items if str(item).strip()][:3]


def _track_usage(chunk, round_usage: dict) -> None:
    """记录流式 chunk 的 usage（OpenAI 兼容模式最后一块携带累计值）"""
    usage = getattr(chunk, "usage", None)
    if not usage:
        return
    if getattr(usage, "prompt_tokens", None) is not None:
        round_usage["in"] = usage.prompt_tokens
    if getattr(usage, "completion_tokens", None) is not None:
        round_usage["out"] = usage.completion_tokens
