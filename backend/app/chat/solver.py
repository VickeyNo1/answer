"""solve / practice 意图的确定性答题流水线（v4.1）

consult 意图仍走 qwen_service.stream_chat（模型自主决定要不要检索）；solve 与
practice 由本模块**确定性**执行检索——拍照上传的题目过去会被模型判成 textbook，
题库 collection 根本不会被查，于是「题库里有原题」和「题库里没有」在系统看来毫无区别。

solve 三档（**全部产出完整解答**，区别只在依据强度与末尾标注）：

- exact   题库命中原题（LLM 二次校验 same=true）→ 喂权威参考答案，跳过教材检索
- similar 题库只有相似题（校验 same=false 或校验失败）→ 喂相似题作范例 + 教材，严禁照搬
- none    题库无结果 → 教材定向检索（prefer="solve"），据准则独立推导

**不用 match_score 阈值判档**：doc/知识库对接文档.md §1.3 明确 score「仅用于排序，
不同请求间不可比」，任何固定阈值方案都建立在错误前提上。故以 LLM 二次校验为主判据。

检索资料注入 system prompt，不伪造 assistant tool_calls —— 本轮只做一次不带工具的
生成，用不上 tool 消息协议，少一层供应商兼容性风险。
"""
import json
import logging

from app import settings_store
from app.config import get_settings
from app.chat.intent import INTENT_PRACTICE, INTENT_SOLVE
from app.chat.qwen_service import (
    DEGRADED_SUFFIX,
    EMPTY_SUFFIX,
    SUGGESTIONS_INSTRUCTION,
    stream_answer,
)
from app.kb import client as kb_client
from app.kb.prompt import collect_kp_ids, format_results, sub_question_text
from app.llm import store as llm_store
from app.llm.client import create_client

logger = logging.getLogger(__name__)

# 检索 query 截断长度：综合题带资料能上千字，过长会稀释向量语义
QUERY_MAX_LEN = 1000

# ========== solve 意图 ==========

SOLVE_SYSTEM_PROMPT = """你是资深会计答疑老师。学生给你一道具体的题目，你必须给出完整解答。

解答要求：
1. 必须给出最终答案，包括解题思路、关键准则依据、计算步骤与结论
2. 不得以「请自行思考」「建议你试试」等方式搪塞，学生要的就是解答
3. 涉及金额的计算要列出算式与单位
4. 使用清晰的结构化格式（标题、列表、表格）
5. 若题目信息不足，明确指出缺什么，并在合理假设下仍然给出解答"""

EXACT_BLOCK = """

【本题命中情况】题库中已找到本题原题，下方给出的是权威参考答案与解析。
请据此把这道题讲透：解题思路、准则依据、易错点。
若你判断参考答案有误，明确指出并给出你的答案。"""

SIMILAR_BLOCK = """

【本题命中情况】题库中**未找到本题原题**。下方相似题**不是本题**，仅供解题思路参考——
**严禁照搬其数据、金额与答案**。请结合教材资料独立求解本题，给出完整步骤与最终答案。"""

NONE_BLOCK = """

【本题命中情况】题库与教材均未直接命中本题。
请依据企业会计准则独立求解，给出完整推理步骤与最终答案，并在关键假设处说明依据。"""

# 档位标注：附在答案末尾随正文落库，是本轮唯一的档位可见性手段（前端零改动）
EXACT_SUFFIX = "\n\n> ✅ 本题已在题库中找到原题，以上解答以题库参考答案为依据。"
SIMILAR_SUFFIX = (
    "\n\n> 📎 题库中未找到本题原题，以上解答参考相似题与教材资料独立推导，"
    "请留意与原题数据的差异。"
)
NONE_SUFFIX = (
    "\n\n> ⚠️ 知识库中未找到本题，以上解答由模型依据企业会计准则独立推导，"
    "建议与老师或教材核对。"
)

EXACT_HEADING = "以下是题库中命中的**本题原题**（含权威参考答案与解析）："
SIMILAR_HEADING = "以下是题库中与本题**相似但并非同一道**的题目（仅供思路参考，含其自身答案）："
NO_CONTEXT_TEXT = "知识库中未检索到与本题相关的资料。请依据企业会计准则独立解答本题。"
KB_DOWN_TEXT = "知识库检索服务当前不可用，未获取到任何资料。请依据企业会计准则独立解答本题。"

# ========== practice 意图 ==========

PRACTICE_SYSTEM_PROMPT = """你是会计练习出题老师。下方是从题库检索到的题目，请原样呈现给学生练习。

要求：
1. 逐题列出资料、题干、选项/要求，保持原文，不要改写数据
2. **绝对不要给出答案、解析或任何提示**，学生要先自己作答
3. 末尾写明「作答后把答案发给我，我来批改」
4. 不要自行编造题目，只呈现检索到的题"""

PRACTICE_REVEAL_BLOCK = """

【本次例外】学生要求直接看答案，请在每题后附题库的参考答案与解析。"""

PRACTICE_COMPOSE_BLOCK = """

【题库无现成练习题】请依据下方教材资料自行命题（须标注「改编题」），
仍**不得给出答案**，末尾写明「作答后把答案发给我，我来批改」。"""

PRACTICE_SUFFIX = "\n\n> 📝 以上为题库练习题，作答后发给我批改。"


def system_prompt_for(intent: str) -> str | None:
    """意图对应的 system prompt；consult 返回 None 表示沿用 qwen_service.SYSTEM_PROMPT"""
    if intent == INTENT_SOLVE:
        return SOLVE_SYSTEM_PROMPT
    if intent == INTENT_PRACTICE:
        return PRACTICE_SYSTEM_PROMPT
    return None


# ========== LLM 二次校验（题目同一性） ==========

VERIFY_SYSTEM_PROMPT = """你是题目比对助手。判断学生提问的题目与候选题库题目是否为**同一道题**。

判定标准：考查同一业务场景、同一数据、同一问法才算同一道题。
仅知识点相同、题型相同，但数据或问法不同的，不算同一道题。

只输出一个 JSON 对象，不要输出任何其他内容，格式：
{"same": true, "index": 1, "reason": "不超过40字的判定依据"}
same 为 false 时 index 输出 null。"""


def build_verify_prompt(question_text: str, candidates: list[dict]) -> str:
    """拼校验 prompt：学生提问 + 候选题（不含答案解析，校验用不上，省 token）"""
    parts = [f"【学生提问的题目】\n{question_text}"]
    items = []
    for i, r in enumerate(candidates, start=1):
        seg = [f"候选{i}（question_id={r.get('question_id') or '未知'}）"]
        if r.get("materials"):
            seg.append(f"资料：{r['materials']}")
        if r.get("stem"):
            seg.append(f"题干：{r['stem']}")
        options = r.get("options")
        if options:
            seg.append("选项：" + " ".join(f"{k}.{v}" for k, v in options.items()))
        for j, sub in enumerate(r.get("sub_questions") or [], start=1):
            text = sub_question_text(sub)
            if text:
                seg.append(f"子问{j}：{text}")
        items.append("\n".join(seg))
    parts.append("【候选题目】\n" + "\n\n".join(items))
    return "\n\n".join(parts)


def parse_verify_result(text: str) -> dict:
    """解析校验 JSON；任何解析失败一律返回 same=False

    代价不对称：误报 exact 会让学生拿着别人的答案去考试；漏报最多退到 similar 档，
    仍有相似题与教材可依。故一律取保守。
    """
    fallback = {"same": False, "index": None, "reason": ""}
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return fallback
    try:
        data = json.loads(text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return fallback
    if not isinstance(data, dict):
        return fallback
    reason = str(data.get("reason") or "").strip()
    if not data.get("same"):
        return {"same": False, "index": None, "reason": reason}
    try:
        index = int(data.get("index"))
    except (TypeError, ValueError):
        # 声称 same 却没给有效 index，无法定位到具体题目 → 保守降级
        return {"same": False, "index": None, "reason": reason}
    return {"same": True, "index": index, "reason": reason}


def _record_verify_usage(resp, model: str, user_id: int,
                         conversation_id: int | None) -> None:
    """校验调用单独记账（task_type='verify'）；失败不影响主链路"""
    try:
        usage = getattr(resp, "usage", None)
        llm_store.record_usage(
            model, user_id, conversation_id,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
            task_type="verify",
        )
    except Exception as e:
        logger.warning("verify 用量记账失败（不影响主链路）: %s", e)


def verify_same_question(question_text: str, candidates: list[dict],
                         user_id: int = 0, conversation_id: int | None = None,
                         model_name: str | None = None) -> dict:
    """LLM 二次校验：候选题里有没有学生问的那道题

    返回 {"same": bool, "index": int|None, "reason": str}。
    任何异常/解析失败一律 same=False（由调用方归入 similar 档）。
    """
    if not candidates:
        return {"same": False, "index": None, "reason": "无候选题"}
    try:
        model = model_name or llm_store.get_model_for("verify")
        client = create_client()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": VERIFY_SYSTEM_PROMPT},
                {"role": "user", "content": build_verify_prompt(question_text, candidates)},
            ],
            extra_body={"enable_thinking": False},
        )
        content = resp.choices[0].message.content or ""
        _record_verify_usage(resp, model, user_id, conversation_id)
        return parse_verify_result(content)
    except Exception as e:
        logger.warning("题目同一性校验失败，按相似题处理: %s", e)
        return {"same": False, "index": None, "reason": f"校验失败：{e}"}


# ========== 上下文拼装辅助 ==========

def _question_ref(r: dict) -> dict:
    """题库结果 → 引用卡片摘要（题库无 title/content，用 question_id 与题干顶替）"""
    return {
        "kp_id": (r.get("knowledge_point_ids") or [""])[0],
        "chapter": r.get("chapter") or "",
        "title": f"题库 {r.get('question_id') or ''}".strip(),
        "snippet": (r.get("stem") or r.get("materials") or "")[:100],
    }


def _textbook_refs(results: list[dict]) -> list[dict]:
    return [
        {
            "kp_id": (r.get("knowledge_point_ids") or [""])[0],
            "chapter": r.get("chapter", "") or "",
            "title": r.get("title", "") or "",
            "snippet": (r.get("content") or "")[:100],
        }
        for r in results
    ]


def _topic_query(results: list[dict], fallback: str) -> str:
    """similar 档的教材检索 query：用相似题自己的题干/资料（干净、同话题）

    题库结果只带 chapter/chapter_id/knowledge_point_ids，**没有 title**（见知识库
    对接文档 §1.4「其余字段同教材」）。学生提问常是 OCR 长文本，噪声大，
    拿相似题的规范题干去检索教材比拿原始提问更准；都没有时回落到原始提问。
    """
    for r in results[:3]:
        chapter = (r.get("chapter") or "").strip()
        body = (r.get("stem") or r.get("materials") or "").strip()
        if body:
            return f"{chapter} {body}".strip()[:QUERY_MAX_LEN]
    return fallback


def _build_answer_messages(messages: list[dict], block: str, context: str) -> list[dict]:
    """把档位说明与检索资料并入 system prompt，保留历史与当前提问

    messages[0] 已由 build_messages 组装为「意图 prompt + 记忆块」，此处只在其后追加。
    """
    head = dict(messages[0]) if messages else {"role": "system", "content": ""}
    head["content"] = (
        (head.get("content") or "") + block + "\n\n" + context + SUGGESTIONS_INSTRUCTION
    )
    return [head] + list(messages[1:])


# ========== solve 流水线 ==========

def run_solve(messages: list[dict], model_name: str | None, subject: str,
              user_id: int = 0, conversation_id: int | None = None,
              query_text: str = ""):
    """solve 意图的确定性检索阶梯 + 单次流式作答

    事件词汇与 qwen_service.stream_chat 完全一致，另加 {"match": {...}}
    （前端 lib/sse.ts 的 switch 无 default 分支，未知事件静默忽略，不会炸前端；
    下一轮批量答题工具直接消费该事件拿结构化档位）。
    """
    settings = get_settings()
    model = model_name or settings.CHAT_MODEL
    usage_acc = {"prompt_tokens": 0, "completion_tokens": 0}

    try:
        query = (query_text or (messages[-1].get("content", "") if messages else "")
                 ).strip()[:QUERY_MAX_LEN]

        yield {"kb_search": True}

        # ===== 第 1 步：题库检索（solve 必查 questions，不交给模型决定）=====
        q_data = kb_client.search(
            query=query, subject=subject, collection="questions", top_k=3,
            user_id=user_id, conversation_id=conversation_id,
        )
        q_results = (q_data or {}).get("results") or []

        # ===== 第 2 步：LLM 二次校验定档 =====
        tier, matched = "none", None
        verify = {"same": False, "index": None, "reason": ""}
        if q_results:
            verify = verify_same_question(query, q_results, user_id, conversation_id)
            idx = verify.get("index")
            # 校验失败或 index 越界一律 similar：绝不在无正向确认时宣称找到原题
            if verify.get("same") and isinstance(idx, int) and 1 <= idx <= len(q_results):
                tier, matched = "exact", q_results[idx - 1]
            else:
                tier = "similar"

        yield {"match": {
            "tier": tier,
            "question_id": (matched or {}).get("question_id"),
            "verify_reason": verify.get("reason") or "",
            "kb_scores": [r.get("score") for r in q_results],
        }}

        # ===== 第 3 步：按档组装上下文 =====
        parts: list[str] = []
        refs: list[dict] = []
        kp_ids = collect_kp_ids({"results": [matched]}) if matched else []
        t_data = None

        if tier == "exact":
            parts.append(format_results(
                {"collection": "questions", "results": [matched]},
                include_answer=True, heading=EXACT_HEADING,
            ))
            refs.append(_question_ref(matched))
        else:
            if tier == "similar":
                parts.append(format_results(
                    {"collection": "questions", "results": q_results},
                    include_answer=True, heading=SIMILAR_HEADING,
                ))
                refs.extend(_question_ref(r) for r in q_results)
                for kp in collect_kp_ids(q_data):
                    if kp not in kp_ids:
                        kp_ids.append(kp)
                text_query = _topic_query(q_results, query)
                top_k, prefer = 5, None
            else:
                text_query, top_k, prefer = query, 8, "solve"

            t_data = kb_client.search(
                query=text_query, subject=subject, collection="textbook", top_k=top_k,
                user_id=user_id, conversation_id=conversation_id,
            )
            t_results = (t_data or {}).get("results") or []
            if t_results:
                parts.append(format_results(t_data, prefer=prefer))
                refs.extend(_textbook_refs(t_results))
                for kp in collect_kp_ids(t_data):
                    if kp not in kp_ids:
                        kp_ids.append(kp)

        if kp_ids:
            yield {"kp_ids": kp_ids}
        if refs:
            yield {"kb_refs": refs}

        # 降级判定：exact 档本就不查教材，只看题库；其余档要两次检索都失败才算服务不可用
        degraded = False if tier == "exact" else (q_data is None and t_data is None)
        if degraded:
            suffix = DEGRADED_SUFFIX
        elif tier == "exact":
            suffix = EXACT_SUFFIX
        elif tier == "similar":
            suffix = SIMILAR_SUFFIX
        else:
            suffix = NONE_SUFFIX

        if parts:
            context = "\n\n".join(parts)
        else:
            context = KB_DOWN_TEXT if degraded else NO_CONTEXT_TEXT

        block = {"exact": EXACT_BLOCK, "similar": SIMILAR_BLOCK}.get(tier, NONE_BLOCK)

        # ===== 第 4 步：单次流式作答 =====
        client = create_client()
        answer_messages = _build_answer_messages(messages, block, context)
        for event in stream_answer(client, model, answer_messages, suffix):
            if "round_usage" in event:
                usage_acc["prompt_tokens"] += event["round_usage"]["in"]
                usage_acc["completion_tokens"] += event["round_usage"]["out"]
                continue
            yield event

        yield {"usage": usage_acc}

    except Exception as e:
        logger.exception("solve 流水线异常")
        yield {"error": f"AI 模型调用异常: {str(e)}"}


# ========== practice 流水线 ==========

def run_practice(messages: list[dict], model_name: str | None, subject: str,
                 user_id: int = 0, conversation_id: int | None = None):
    """practice 意图：只出题不给答案（受 practice_reveal_answer 开关控制）"""
    settings = get_settings()
    model = model_name or settings.CHAT_MODEL
    reveal = settings_store.get_bool("practice_reveal_answer")
    usage_acc = {"prompt_tokens": 0, "completion_tokens": 0}

    try:
        query = (messages[-1].get("content", "") if messages else "").strip()[:QUERY_MAX_LEN]

        yield {"kb_search": True}

        data = kb_client.search(
            query=query, subject=subject, collection="questions", top_k=5,
            user_id=user_id, conversation_id=conversation_id,
        )
        results = (data or {}).get("results") or []

        kp_ids = collect_kp_ids(data)
        refs: list[dict] = []
        t_results: list[dict] = []

        if results:
            refs = [_question_ref(r) for r in results]
            context = format_results(data, include_answer=reveal)
            block = PRACTICE_REVEAL_BLOCK if reveal else ""
            suffix = PRACTICE_SUFFIX
        else:
            # 题库没有现成练习题 → 退而据教材命题，避免学生只拿到一句「没有题」
            t_data = kb_client.search(
                query=query, subject=subject, collection="textbook", top_k=5,
                user_id=user_id, conversation_id=conversation_id,
            )
            t_results = (t_data or {}).get("results") or []
            for kp in collect_kp_ids(t_data):
                if kp not in kp_ids:
                    kp_ids.append(kp)
            if t_results:
                refs = _textbook_refs(t_results)
                context = format_results(t_data)
                block = PRACTICE_COMPOSE_BLOCK
                suffix = PRACTICE_SUFFIX
            else:
                kb_down = data is None and t_data is None
                context = KB_DOWN_TEXT if kb_down else NO_CONTEXT_TEXT
                block = NONE_BLOCK
                suffix = DEGRADED_SUFFIX if kb_down else EMPTY_SUFFIX

        if kp_ids:
            yield {"kp_ids": kp_ids}
        if refs:
            yield {"kb_refs": refs}

        client = create_client()
        answer_messages = _build_answer_messages(messages, block, context)
        for event in stream_answer(client, model, answer_messages, suffix):
            if "round_usage" in event:
                usage_acc["prompt_tokens"] += event["round_usage"]["in"]
                usage_acc["completion_tokens"] += event["round_usage"]["out"]
                continue
            yield event

        yield {"usage": usage_acc}

    except Exception as e:
        logger.exception("practice 流水线异常")
        yield {"error": f"AI 模型调用异常: {str(e)}"}
