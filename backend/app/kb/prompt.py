"""知识库检索结果拼接（契约 §3）与 tool schema（契约 §2）"""

# 大模型 Function Calling 工具定义：模型只决定 query/collection/top_k，
# subject 由后端从会话上下文注入，不进 schema
SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_cpa_knowledge",
        "description": (
            "检索CPA会计知识库。当用户问题涉及会计准则、会计概念、账务处理、"
            "会计分录、例题讲解，或需要教材原文/练习题佐证时调用；"
            "用户想要练习题、真题时用 collection=questions；"
            "闲聊或与会计无关的问题不要调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用自然语言描述要查什么，尽量保留用户问题中的专业词",
                },
                "collection": {
                    "type": "string",
                    "enum": ["textbook", "questions"],
                    "description": "textbook=查教材讲解（默认）；questions=查练习题/真题",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回条数，默认5",
                },
            },
            "required": ["query"],
        },
    },
}

# 检索失败/空结果时喂给大模型的降级话术
FALLBACK_TEXT = "知识库未检索到相关资料，请基于你自身的会计专业知识回答，并说明本次回答未参考知识库资料。"


def _kp_label(kp_ids: list | None) -> str:
    """知识点标注：为空时标「未标注」"""
    if kp_ids:
        return "知识点 " + "、".join(kp_ids)
    return "知识点 未标注"


def format_results(data: dict | None) -> str:
    """将 /kb/search 响应拼接为回传给大模型的 tool 结果文本"""
    if data is None or not data.get("results"):
        return FALLBACK_TEXT

    collection = data.get("collection", "textbook")
    results = data["results"]
    if collection == "questions":
        return _format_questions(results)
    return _format_textbook(results)


def _format_textbook(results: list[dict]) -> str:
    lines = ["以下是从CPA会计知识库检索到的资料，请据此回答用户问题，并标注依据的知识点编号："]
    for i, r in enumerate(results, start=1):
        kp = _kp_label(r.get("knowledge_point_ids"))
        chapter = r.get("chapter", "")
        section = r.get("section", "")
        title = r.get("title", "")
        lines.append(f"\n【资料{i}｜{kp}｜{chapter} · {section}｜{title}】")
        lines.append(r.get("content", ""))
    return "\n".join(lines)


def _format_questions(results: list[dict]) -> str:
    lines = ["以下是从CPA题库检索到的题目："]
    for i, r in enumerate(results, start=1):
        kp = _kp_label(r.get("knowledge_point_ids"))
        qid = r.get("question_id", "")
        qtype = r.get("question_type", "")
        lines.append(f"\n【题目{i}｜{qid}｜{qtype}｜{kp}】")
        if r.get("materials"):
            lines.append(f"资料：{r['materials']}")
        if r.get("stem"):
            lines.append(f"题干：{r['stem']}")
        options = r.get("options")
        if options:
            opt_text = " ".join(f"{k}.{v}" for k, v in options.items())
            lines.append(f"选项：{opt_text}")
        if r.get("sub_questions"):
            for j, sub in enumerate(r["sub_questions"], start=1):
                lines.append(f"子问{j}：{sub}")
        if r.get("answer"):
            lines.append(f"答案：{r['answer']}")
        if r.get("explanation"):
            lines.append(f"解析：{r['explanation']}")
    return "\n".join(lines)


def collect_kp_ids(data: dict | None) -> list[str]:
    """汇总检索结果中的 knowledge_point_ids（去重、保序），用于落库"""
    if data is None:
        return []
    seen = []
    for r in data.get("results", []):
        for kp in r.get("knowledge_point_ids") or []:
            if kp not in seen:
                seen.append(kp)
    return seen
