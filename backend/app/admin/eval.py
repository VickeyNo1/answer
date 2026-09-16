"""批量评测：单题作答端点（配套 backend/scripts/batch_eval.py）

用途是把基准题库（如 400 题）逐个喂给答题链路、导出 Excel 交专家线下评分。

**刻意不复用 POST /api/chat**，那条路对评测全是负担：

- 往 conversations/messages 落库 → 污染对话数据，还会推进学生画像的对话计数
- 扣每日配额 → 400 题跑不到头就被 429 挡住
- 走并发闸门 → 挤占真实学生的槽位
- SSE 只推正文增量 → 拿不到档位（match）与用量（usage）这两个结构化指标

本端点直接 drain 生成器、收齐事件后一次性返回 JSON，上面四样都不做；唯一的
持久化副作用是 usage_logs 记 task_type='eval' 的真实开销，且 **user_id 传 NULL**
（该列可空、无外键），既不把开销挂到任何学生头上，也便于事后按
`user_id IS NULL AND task_type='eval'` 一次查出全部评测行。

检索日志用 log_enabled=False 全程抑制：400 题 × 2 次检索 = 800 行，灌进去会把
给使用方看的检索质量报表彻底冲掉。

同步 def 路由：FastAPI 放线程池执行，drain 阻塞式生成器不会卡事件循环，脚本的
--concurrency 因此能真并发。
"""
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import require_admin
from app.chat import solver
from app.chat.intent import INTENT_PRACTICE, INTENT_SOLVE, classify_intent
from app.chat.qwen_service import build_messages, stream_chat
from app.kb.subjects import DEFAULT_SUBJECT, is_valid_subject
from app.llm import store as llm_store
from app.llm.client import completion_extra, create_client
from app.models import EvalAnswerOut, EvalAnswerRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/eval", tags=["批量评测"])

# solve = 强制走答题链路；auto = 按 classify_intent 分流（对照组）
EVAL_INTENTS = ("solve", "auto")

# 消融实验三组（2026-09-16，专家要求的对照设计）：
#   full        = C 组（模型+提示词+向量知识库，完整系统）
#   prompt_only = B 组（模型+提示词，检索桩空走 none 档 prompt）
#   bare        = A 组（裸模型直答）
EVAL_MODES = ("full", "prompt_only", "bare")


def _answer_bare(question: str, model: str, started: float) -> EvalAnswerOut:
    """A 组：裸模型直答——单条 user 消息，无 system prompt、无检索、无后处理"""
    prompt_tokens = 0
    completion_tokens = 0
    answer = ""
    error: str | None = None
    try:
        client = create_client(model)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": question}],
            extra_body=completion_extra(model),
        )
        answer = (resp.choices[0].message.content or "").strip()
        usage = getattr(resp, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    except Exception as e:
        logger.exception("eval bare 模式调用失败")
        error = f"AI 模型调用异常: {str(e)}"

    elapsed_ms = int((time.monotonic() - started) * 1000)
    if prompt_tokens or completion_tokens:
        try:
            llm_store.record_usage(
                model, None, None, prompt_tokens, completion_tokens,
                task_type="eval",
            )
        except Exception as e:
            logger.warning("eval 用量记账失败（不影响返回结果）: %s", e)

    return EvalAnswerOut(
        question=question,
        intent="bare",
        mode="bare",
        answer=answer,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        elapsed_ms=elapsed_ms,
        error=error,
    )


@router.post("/answer", response_model=EvalAnswerOut)
def answer_one(req: EvalAnswerRequest, admin: dict = Depends(require_admin)):
    """单题作答，返回结构化结果（档位 + 引用 + 用量），不落库对话、不扣配额、不占并发槽"""
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="question 不能为空"
        )
    if req.intent not in EVAL_INTENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"intent 只能是 {' 或 '.join(EVAL_INTENTS)}",
        )
    if req.mode not in EVAL_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"mode 只能是 {' / '.join(EVAL_MODES)}",
        )
    subject = req.subject if is_valid_subject(req.subject) else DEFAULT_SUBJECT

    # 显式指定模型时必须是 model_configs 里真实存在的模型名：
    # compute_cost 查不到模型时单价回退 0.0，整批评测的 cost 会恒记 0 且不报错
    pinned = (req.model_name or "").strip()
    if pinned and llm_store.get_model_by_name(pinned) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"模型 {pinned!r} 在 model_configs 中不存在，请先在管理后台补记录"
                   f"（否则本批评测费用将全部记 0）",
        )
    model_name = pinned or llm_store.get_model_for("eval")

    started = time.monotonic()
    if req.mode == "bare":
        return _answer_bare(question, model_name, started)

    # prompt_only（B 组）强制按 solve 处理：none 档 prompt 是为答题设计的，
    # consult 路径会让模型自主决定检索，与「无知识库」的实验定义冲突
    if req.mode == "prompt_only":
        intent = INTENT_SOLVE
    else:
        # auto 才过意图分类；solve 直接钉死，因为基准题面是书面陈述句，
        # 实测 400 题里 86.5% 会被判成 consult，而 consult 路径没有三档命中、
        # 不碰题库，评测不到答题能力（对照组的存在就是为了量化这个偏差）
        intent = classify_intent(question) if req.intent == "auto" else INTENT_SOLVE
    messages = build_messages(question, [], None, solver.system_prompt_for(intent))

    if intent == INTENT_PRACTICE:
        chunks = solver.run_practice(messages, model_name, subject, None, None,
                                     log_enabled=False)
    elif intent == INTENT_SOLVE:
        chunks = solver.run_solve(messages, model_name, subject, None, None,
                                  question, log_enabled=False,
                                  disable_kb=req.mode == "prompt_only",
                                  verify_model=pinned or None)
    else:
        chunks = stream_chat(messages, model_name, subject, None, None,
                             log_enabled=False)

    parts: list[str] = []
    tier: str | None = None
    question_id: str | None = None
    verify_reason = ""
    kp_ids: list[str] = []
    refs: list[dict] = []
    suggestions: list[str] = []
    prompt_tokens = 0
    completion_tokens = 0
    error: str | None = None

    for chunk in chunks:
        if "error" in chunk:
            error = chunk["error"]
            break
        if "match" in chunk:
            match = chunk["match"]
            tier = match.get("tier")
            question_id = match.get("question_id")
            verify_reason = match.get("verify_reason") or ""
        elif "kp_ids" in chunk:
            kp_ids = chunk["kp_ids"]
        elif "kb_refs" in chunk:
            refs = chunk["kb_refs"]
        elif "suggestions" in chunk:
            suggestions = chunk["suggestions"]
        elif "usage" in chunk:
            prompt_tokens = chunk["usage"].get("prompt_tokens", 0)
            completion_tokens = chunk["usage"].get("completion_tokens", 0)
        elif chunk.get("content"):
            parts.append(chunk["content"])

    elapsed_ms = int((time.monotonic() - started) * 1000)

    # 出错也要记账：token 已经真实消耗，静默丢掉会让评测成本对不上账
    if prompt_tokens or completion_tokens:
        try:
            llm_store.record_usage(
                model_name, None, None, prompt_tokens, completion_tokens,
                task_type="eval",
            )
        except Exception as e:
            logger.warning("eval 用量记账失败（不影响返回结果）: %s", e)

    return EvalAnswerOut(
        question=question,
        intent=intent,
        mode=req.mode,
        tier=tier,
        question_id=question_id,
        verify_reason=verify_reason,
        answer="".join(parts),
        kb_refs=refs,
        kp_ids=kp_ids,
        suggestions=suggestions,
        model=model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        elapsed_ms=elapsed_ms,
        error=error,
    )
