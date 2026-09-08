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

# 知识库 content_type 枚举（契约见 doc/知识库对接文档.md §content_type）
CONTENT_TYPE_LABELS: dict[str, str] = {
    "theory": "理论",
    "example": "例题",
    "entry": "分录",
    "table": "表格",
    "formula": "公式",
    "tip": "提示",
    "faq": "问答",
    "principle": "原则",
}

# 解题场景（prefer="solve"）优先前置的资料类型：分录题检索回一堆纯理论是没用的
SOLVE_PREFERRED_TYPES = ("example", "entry", "formula", "table")

# 剪裁答案时的占位提示：让模型知道答案存在但拿不到，从而引导学生先自行作答
ANSWER_OMITTED_HINT = "（参考答案与解析已省略，请先自行作答）"

# 标头行防泄漏：线上实测模型把「【题目2｜ACC-2025-Q-5.10｜multiple_choice｜知识点 …】」
# 原样抄进了给学生的答案里。标头是给模型定位资料用的内部索引，学生看到只会一头雾水。
# 必须**紧跟在资料之后**追加（两条作答路径的资料位置不同：solve/practice 在 system
# prompt 中段，consult 在独立的 tool 消息里），用「上方」指代才都成立。
MARKER_NOTICE = """

【内部标头不外泄】上方资料里形如「【题目1｜ACC-2025-Q-5.10｜multiple_choice｜知识点 ACC-05-02-01】」
「【资料2｜例题｜知识点 ACC-21-01-01｜第21章 租赁 · 第1节｜融资租赁的判断】」的标头行，
只是给你定位资料用的内部索引，不是学生要看的正文。回答中**不要复制这些标头行**，
也不要沿用它的竖线分隔格式；需要说明依据时用自然语言写章节与知识点编号，
例如「依据第21章 租赁（知识点 ACC-21-01-01）」。"""


def append_marker_notice(context: str) -> str:
    """在拼好的检索资料末尾追加 MARKER_NOTICE

    刻意不放进 format_results：solve 的 similar/none 档会把题库与教材两段资料拼在一起，
    放进去等于同一份 prompt 里说两遍；且 format_results 空结果时返回 FALLBACK_TEXT，
    那时根本没有标头行可交代。
    """
    return context + MARKER_NOTICE


def _kp_label(kp_ids: list | None) -> str:
    """知识点标注：为空时标「未标注」"""
    if kp_ids:
        return "知识点 " + "、".join(kp_ids)
    return "知识点 未标注"


def sub_question_text(sub, include_answer: bool = False) -> str:
    """子问渲染：知识库既返回纯字符串也返回对象（含 question/answer/explanation）

    对象形态直接 f-string 会把 Python dict repr 喂给大模型，计算/综合题（正是拍照
    提问最常见的题型）的子问因此变得难以理解。此处统一取文本。

    include_answer 默认 False —— 子问对象自带 answer/explanation，不剪裁就会从
    后门泄漏答案，与 format_results 的默认剪裁约定保持一致。
    """
    if isinstance(sub, dict):
        text = (sub.get("question") or sub.get("stem") or "").strip()
        if include_answer:
            answer = (sub.get("answer") or "").strip()
            if answer:
                text = f"{text}（该子问参考答案：{answer}）" if text else f"参考答案：{answer}"
        return text
    return str(sub or "").strip()


def format_results(data: dict | None, prefer: str | None = None,
                   include_answer: bool = False,
                   heading: str | None = None) -> str:
    """将 /kb/search 响应拼接为回传给大模型的 tool 结果文本

    prefer="solve" 时把例题/分录/公式/表格类资料稳定排序到理论类之前。
    include_answer 默认 False —— 题库答案与解析**默认剪裁**，需要答案的调用点
    必须显式传 True（契约见 doc/知识库对接文档.md「先答题后判卷场景务必剪裁」）。
    heading 用于覆盖题库结果的默认标题行（相似题场景需明确告知模型「这些不是本题」）。
    """
    if data is None or not data.get("results"):
        return FALLBACK_TEXT

    collection = data.get("collection", "textbook")
    results = data["results"]
    if collection == "questions":
        return _format_questions(results, include_answer=include_answer, heading=heading)
    return _format_textbook(results, prefer=prefer)


def _content_type_rank(r: dict) -> int:
    """解题场景的分组序：例题/分录/公式/表格 → 0，其余已知类型 → 1，缺失或未知 → 2"""
    ctype = r.get("content_type")
    if ctype in SOLVE_PREFERRED_TYPES:
        return 0
    if ctype in CONTENT_TYPE_LABELS:
        return 1
    return 2


def _format_textbook(results: list[dict], prefer: str | None = None) -> str:
    if prefer == "solve":
        # 稳定排序：同组内保持知识库返回的原 score 顺序；缺 content_type 的条目排最后但不丢弃
        results = sorted(results, key=_content_type_rank)

    lines = ["以下是从CPA会计知识库检索到的资料，请据此回答用户问题，并标注依据的知识点编号："]
    for i, r in enumerate(results, start=1):
        kp = _kp_label(r.get("knowledge_point_ids"))
        ctype = CONTENT_TYPE_LABELS.get(r.get("content_type") or "", "未分类")
        chapter = r.get("chapter", "")
        section = r.get("section", "")
        title = r.get("title", "")
        lines.append(f"\n【资料{i}｜{ctype}｜{kp}｜{chapter} · {section}｜{title}】")
        lines.append(r.get("content", ""))
    return "\n".join(lines)


QUESTIONS_HEADING = "以下是从CPA题库检索到的题目："


def _format_questions(results: list[dict], include_answer: bool = False,
                      heading: str | None = None) -> str:
    lines = [heading or QUESTIONS_HEADING]
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
            subs = [t for t in (sub_question_text(s, include_answer=include_answer)
                                for s in r["sub_questions"]) if t]
            for j, text in enumerate(subs, start=1):
                lines.append(f"子问{j}：{text}")
        if include_answer:
            if r.get("answer"):
                lines.append(f"答案：{r['answer']}")
            if r.get("explanation"):
                lines.append(f"解析：{r['explanation']}")
        elif _has_hidden_answer(r):
            lines.append(ANSWER_OMITTED_HINT)
    return "\n".join(lines)


def _has_hidden_answer(r: dict) -> bool:
    """本题是否存在被剪裁掉的答案

    综合题的参考答案常分散在 sub_questions 对象里而顶层 answer 为 null，只判顶层
    字段会漏掉提示，模型便以为题库没有答案而自行编造。
    """
    if r.get("answer") or r.get("explanation"):
        return True
    for sub in r.get("sub_questions") or []:
        if isinstance(sub, dict) and (sub.get("answer") or sub.get("explanation")):
            return True
    return False


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
