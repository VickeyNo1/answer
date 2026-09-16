"""solve / practice 意图的确定性答题流水线（v4.1）

consult 意图仍走 qwen_service.stream_chat（模型自主决定要不要检索）；solve 与
practice 由本模块**确定性**执行检索——拍照上传的题目过去会被模型判成 textbook，
题库 collection 根本不会被查，于是「题库里有原题」和「题库里没有」在系统看来毫无区别。

solve 三档（**全部产出完整解答**，区别只在依据强度与末尾标注）：

- exact   题库命中原题（LLM 二次校验 same=true）→ 喂权威参考答案，跳过教材检索
- similar 题库只有相似题（校验 same=false 但指认了相关候选）→ 只喂被指认的那几道作范例
          + 教材，严禁照搬
- none    题库无结果，**或候选经校验判定与本题无关** → 教材定向检索（prefer="solve"），
          据准则独立推导

**不用 match_score 阈值判档，也不用它做相关性下限**：doc/知识库对接文档.md §1.3 明确
score「仅用于排序，不同请求间不可比」，任何固定阈值方案都建立在错误前提上。而检索服务
本身**没有相关性下限**——乱码 query 也会返回满 top_k 条（实测 score 恒为 1.0/0.5/0.333
这类归一化排序分），所以「题库返回了结果」并不等于「题库里有相关的题」。两件事都只能
交给 LLM 二次校验：同一次调用既判同一性（定 exact），又指认哪几道值得作参考
（relevant_indexes），**零额外成本**。

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
from app.kb.prompt import (
    append_marker_notice,
    collect_kp_ids,
    format_results,
    sub_question_text,
)
from app.llm import store as llm_store
from app.llm.client import completion_extra, create_client

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
**严禁照搬其数据、金额与答案**。请结合教材资料与准则原文独立求解本题，给出完整步骤与最终答案。"""

NONE_BLOCK = """

【本题命中情况】题库中没有可用于参考本题的题目。
若下方附有教材或准则原文资料，请以其为依据（准则原文与你的既有记忆冲突时，以原文为准）；
否则依据企业会计准则独立求解。
两种情况都必须给出完整推理步骤与最终答案，并在关键假设处说明依据。"""

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

VERIFY_SYSTEM_PROMPT = """你是题目比对助手。对学生提问的题目与候选题库题目做两项判断：

一、**同一性**：候选里有没有和学生问的是**同一道题**。
判定标准：考查同一业务场景、同一数据、同一问法才算同一道题。
仅知识点相同、题型相同，但数据或问法不同的，不算同一道题。

二、**相关性**：候选里哪几道与本题**同一知识点或同一业务领域**，值得作为解题思路参考。
知识库检索没有相关性下限，无关候选也会被一并返回；把不同章节、不同业务的题目当范例
会污染作答。判定口径要宽松：同知识点但数据或问法不同的**应当列入**（这正是相似题的
价值所在），只有与本题明显不同章节、不同业务的才排除。都不相关时输出空数组。

只输出一个 JSON 对象，不要输出任何其他内容，格式：
{"same": true, "index": 1, "relevant_indexes": [1, 2], "reason": "不超过40字的判定依据"}
same 为 false 时 index 输出 null；没有相关候选时 relevant_indexes 输出 []。"""


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


def _parse_relevant_indexes(value) -> list[int] | None:
    """解析 relevant_indexes；缺失或不是数组一律 None（无信号），而非 []（明确无相关）

    越界裁剪交给调用方——本函数不知道候选有几条。
    """
    if not isinstance(value, (list, tuple)):
        return None
    out: list[int] = []
    for item in value:
        try:
            idx = int(item)
        except (TypeError, ValueError):
            continue
        if idx not in out:
            out.append(idx)
    return out


def parse_verify_result(text: str) -> dict:
    """解析校验 JSON；任何解析失败一律返回 same=False

    代价不对称：误报 exact 会让学生拿着别人的答案去考试；漏报最多退到 similar 档，
    仍有相似题与教材可依。故一律取保守。

    `relevant_indexes` 的 None 与 [] 是两种不同信号，别合并：None = 没拿到相关性判断
    （沿用旧的保守行为），[] = 模型明确说候选里没有一道与本题相关（触发相关性下限）。
    """
    fallback = {"same": False, "index": None, "relevant_indexes": None, "reason": ""}
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
    relevant = _parse_relevant_indexes(data.get("relevant_indexes"))
    if not data.get("same"):
        return {"same": False, "index": None, "relevant_indexes": relevant, "reason": reason}
    try:
        index = int(data.get("index"))
    except (TypeError, ValueError):
        # 声称 same 却没给有效 index，无法定位到具体题目 → 保守降级
        return {"same": False, "index": None, "relevant_indexes": relevant, "reason": reason}
    return {"same": True, "index": index, "relevant_indexes": relevant, "reason": reason}


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
    """LLM 二次校验：候选题里有没有学生问的那道题，以及哪几道值得作参考

    返回 {"same": bool, "index": int|None, "relevant_indexes": list[int]|None, "reason": str}。
    任何异常/解析失败一律 same=False（由调用方归入 similar 档）；此时 relevant_indexes
    为 **None**（没拿到相关性信号），刻意区别于 [] （模型明确判定都不相关）。
    """
    if not candidates:
        return {"same": False, "index": None, "relevant_indexes": [], "reason": "无候选题"}
    try:
        model = model_name or llm_store.get_model_for("verify")
        client = create_client(model)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": VERIFY_SYSTEM_PROMPT},
                {"role": "user", "content": build_verify_prompt(question_text, candidates)},
            ],
            extra_body=completion_extra(model),
        )
        content = resp.choices[0].message.content or ""
        _record_verify_usage(resp, model, user_id, conversation_id)
        result = parse_verify_result(content)
        indexes = result["relevant_indexes"]
        if indexes:
            # 全部越界 = 信号不可用（模型幻觉了序号），按「无信号」处理而非「明确无相关」，
            # 否则会白白丢掉可用的相似题参考
            result["relevant_indexes"] = [
                i for i in indexes if 1 <= i <= len(candidates)
            ] or None
        return result
    except Exception as e:
        logger.warning("题目同一性校验失败，按相似题处理: %s", e)
        return {"same": False, "index": None, "relevant_indexes": None,
                "reason": f"校验失败：{e}"}


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


def _standards_refs(results: list[dict]) -> list[dict]:
    """standards 结果的引用卡片：kp 恒空，用准则号/准则名定位"""
    return [
        {
            "kp_id": "",
            "chapter": str(r.get("standard_no") or ""),
            "title": str(r.get("standard_title") or ""),
            "snippet": str(r.get("content") or "")[:100],
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
              user_id: int | None = 0, conversation_id: int | None = None,
              query_text: str = "", log_enabled: bool = True,
              disable_kb: bool = False, verify_model: str | None = None):
    """solve 意图的确定性检索阶梯 + 单次流式作答

    事件词汇与 qwen_service.stream_chat 完全一致，另加 {"match": {...}}
    （前端 lib/sse.ts 的 switch 无 default 分支，未知事件静默忽略，不会炸前端；
    批量答题工具直接消费该事件拿结构化档位）。

    log_enabled=False 供批量评测使用：检索行为不变，但各次检索都不写
    kb_search_logs。user_id 可为 None（usage_logs 该列可空且无外键），
    评测用量因此不挂到任何真实学生头上。

    disable_kb=True 供消融实验的 B 组（模型+提示词，无知识库）：各次检索都
    跳过、不触发校验调用，自然落入 none 档路径——prompt 结构、档位说明块、
    末尾标注与真实 none 档完全相同，只是资料段为空。此时不算降级
    （DEGRADED_SUFFIX 是「检索服务挂了」，与消融组语义不符）。

    verify_model 非空时校验调用用它而非 get_model_for("verify")：消融实验
    的 C 组需要 verify 与作答同模型，才能把「换模型」作为唯一变量隔离。
    """
    settings = get_settings()
    model = model_name or settings.CHAT_MODEL
    usage_acc = {"prompt_tokens": 0, "completion_tokens": 0}

    try:
        query = (query_text or (messages[-1].get("content", "") if messages else "")
                 ).strip()[:QUERY_MAX_LEN]

        yield {"kb_search": True}

        # ===== 第 1 步：题库检索（solve 必查 questions，不交给模型决定）=====
        q_data = None if disable_kb else kb_client.search(
            query=query, subject=subject, collection="questions", top_k=3,
            user_id=user_id, conversation_id=conversation_id,
            log_enabled=log_enabled,
        )
        q_results = (q_data or {}).get("results") or []

        # ===== 第 2 步：LLM 二次校验定档 =====
        tier, matched, ref_questions = "none", None, []
        verify = {"same": False, "index": None, "reason": ""}
        if q_results:
            verify = verify_same_question(query, q_results, user_id, conversation_id,
                                          model_name=verify_model)
            idx = verify.get("index")
            # 校验失败或 index 越界一律 similar：绝不在无正向确认时宣称找到原题
            if verify.get("same") and isinstance(idx, int) and 1 <= idx <= len(q_results):
                tier, matched = "exact", q_results[idx - 1]
            else:
                # 相关性下限：检索服务没有下限（乱码 query 也返回 top_k），score 又只是
                # 重排后的排序分、跨请求不可比，故只能由校验模型指认哪几道真与本题同领域。
                indexes = verify.get("relevant_indexes")
                if indexes is None:
                    # 没拿到相关性信号（校验失败/字段缺失）→ 沿用旧的保守行为，全量注入
                    tier, ref_questions = "similar", q_results
                else:
                    picked = [q_results[i - 1] for i in indexes if 1 <= i <= len(q_results)]
                    if picked:
                        tier, ref_questions = "similar", picked
                    else:
                        # 明确判定候选与本题无关 → 不注入噪声，走 none 档独立推导
                        tier = "none"

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
        s_data = None

        if tier == "exact":
            parts.append(format_results(
                {"collection": "questions", "results": [matched]},
                include_answer=True, heading=EXACT_HEADING,
            ))
            refs.append(_question_ref(matched))
        else:
            if tier == "similar":
                parts.append(format_results(
                    {"collection": "questions", "results": ref_questions},
                    include_answer=True, heading=SIMILAR_HEADING,
                ))
                refs.extend(_question_ref(r) for r in ref_questions)
                for kp in collect_kp_ids({"results": ref_questions}):
                    if kp not in kp_ids:
                        kp_ids.append(kp)
                text_query = _topic_query(ref_questions, query)
                top_k, prefer = 5, None
            else:
                text_query, top_k, prefer = query, 8, "solve"

            t_data = None if disable_kb else kb_client.search(
                query=text_query, subject=subject, collection="textbook", top_k=top_k,
                user_id=user_id, conversation_id=conversation_id,
                log_enabled=log_enabled,
            )
            t_results = (t_data or {}).get("results") or []
            if t_results:
                parts.append(format_results(t_data, prefer=prefer))
                refs.extend(_textbook_refs(t_results))
                for kp in collect_kp_ids(t_data):
                    if kp not in kp_ids:
                        kp_ids.append(kp)

            # standards 库（准则/解释原文）2026-09 起可用：similar/none 两档都补查。
            # query 用原始提问——题面常直接点名新解释/新准则，教材定向 query 反而丢掉该信号；
            # 失败（None）静默跳过，不影响其余资料，也不单独算降级
            s_data = None if disable_kb else kb_client.search(
                query=query, subject=subject, collection="standards", top_k=3,
                user_id=user_id, conversation_id=conversation_id,
                log_enabled=log_enabled,
            )
            s_results = (s_data or {}).get("results") or []
            if s_results:
                parts.append(format_results(s_data))
                refs.extend(_standards_refs(s_results))

        if kp_ids:
            yield {"kp_ids": kp_ids}
        if refs:
            yield {"kb_refs": refs}

        # 降级判定：exact 档本就不查教材，只看题库；其余档要三次检索全部失败才算服务不可用
        # （standards 或教材任一拿到资料就不算降级）。disable_kb 是消融组（刻意不检索），
        # 不是检索服务故障，不算降级
        degraded = False if (tier == "exact" or disable_kb) else (
            q_data is None and t_data is None and s_data is None
        )
        if degraded:
            suffix = DEGRADED_SUFFIX
        elif tier == "exact":
            suffix = EXACT_SUFFIX
        elif tier == "similar":
            suffix = SIMILAR_SUFFIX
        else:
            suffix = NONE_SUFFIX

        if parts:
            context = append_marker_notice("\n\n".join(parts))
        else:
            context = KB_DOWN_TEXT if degraded else NO_CONTEXT_TEXT

        block = {"exact": EXACT_BLOCK, "similar": SIMILAR_BLOCK}.get(tier, NONE_BLOCK)

        # ===== 第 4 步：单次流式作答 =====
        client = create_client(model)
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
                 user_id: int | None = 0, conversation_id: int | None = None,
                 log_enabled: bool = True):
    """practice 意图：只出题不给答案（受 practice_reveal_answer 开关控制）

    log_enabled 与 run_solve 同名参数语义一致，供批量评测抑制 kb_search_logs。
    """
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
            log_enabled=log_enabled,
        )
        results = (data or {}).get("results") or []

        kp_ids = collect_kp_ids(data)
        refs: list[dict] = []
        t_results: list[dict] = []

        if results:
            refs = [_question_ref(r) for r in results]
            context = append_marker_notice(format_results(data, include_answer=reveal))
            block = PRACTICE_REVEAL_BLOCK if reveal else ""
            suffix = PRACTICE_SUFFIX
        else:
            # 题库没有现成练习题 → 退而据教材命题，避免学生只拿到一句「没有题」
            t_data = kb_client.search(
                query=query, subject=subject, collection="textbook", top_k=5,
                user_id=user_id, conversation_id=conversation_id,
                log_enabled=log_enabled,
            )
            t_results = (t_data or {}).get("results") or []
            for kp in collect_kp_ids(t_data):
                if kp not in kp_ids:
                    kp_ids.append(kp)
            if t_results:
                refs = _textbook_refs(t_results)
                context = append_marker_notice(format_results(t_data))
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

        client = create_client(model)
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
