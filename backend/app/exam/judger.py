"""判卷引擎（设计 §4.3/§4.4）：题型满分常量 + 客观题程序判分 + 主观题 LLM 异步判卷

判分依据一律读 question_snapshot，不回查知识库（防改题错位）。
主观题在交卷后由模块级线程池后台判卷（M3 画像总结复用同一个池），
单题失败重试 1 次仍败记 score=NULL，整卷仍会置 graded（管理员可复核改分）。
"""
import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor

from app.llm.client import create_client
from app.database import get_db_ctx
from app.llm import store as llm_store

logger = logging.getLogger(__name__)

# 后台任务线程池（模块级单例，M3 画像总结复用；命名保持中性）
_bg_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bg")

# 题型满分（v4.0 固定值，设计 §4.2）
FULL_SCORES: dict[str, float] = {
    "单选": 1.0,
    "多选": 2.0,
    "计算": 10.0,
    "综合": 15.0,
}

OBJECTIVE_TYPES = ("单选", "多选")
SUBJECTIVE_TYPES = ("计算", "综合")


def is_objective(question_type: str) -> bool:
    return question_type in OBJECTIVE_TYPES


def judge_objective(question_type: str, snapshot: dict,
                    student_answer: str | None) -> float:
    """客观题即时判分：单选全等得满分；多选选项集合完全一致得满分，否则 0（不做半对给分）"""
    full = FULL_SCORES.get(question_type, 0.0)
    correct = (snapshot.get("answer") or "").strip().upper()
    mine = (student_answer or "").strip().upper()
    if not mine or not correct:
        return 0.0
    if question_type == "多选":
        return full if set(mine) == set(correct) else 0.0
    return full if mine == correct else 0.0


# ========== 主观题 LLM 判卷 ==========

JUDGE_SYSTEM_PROMPT = """你是资深会计阅卷老师，按参考答案与解析给学生作答打分。

评分要求：
1. 只看会计要点是否正确、完整，不因表述方式、错别字扣分
2. 得分率 score_rate 取 0 到 1 之间的小数（完全正确 1，完全错误或空白 0）
3. reason 用不超过 80 字说明扣分点或亮点
4. 只输出一个 JSON 对象，不要输出任何其他内容，格式：{"score_rate": 0.7, "reason": "…"}"""

JUDGE_FAIL_PREFIX = "[判卷失败]"


def build_judge_prompt(snapshot: dict, student_answer: str | None,
                       full_score: float) -> str:
    """拼判卷 prompt：题干 + materials + 参考答案 + 解析 + 学生作答"""
    parts = [f"【题型】{snapshot.get('question_type') or ''}（满分 {full_score} 分）"]
    if snapshot.get("materials"):
        parts.append(f"【资料】\n{snapshot['materials']}")
    if snapshot.get("stem"):
        parts.append(f"【题干】\n{snapshot['stem']}")
    subs = snapshot.get("sub_questions") or []
    if subs:
        items = "\n".join(f"{i}. {s}" for i, s in enumerate(subs, 1))
        parts.append(f"【要求】\n{items}")
    parts.append(f"【参考答案】\n{snapshot.get('answer') or '（无）'}")
    if snapshot.get("explanation"):
        parts.append(f"【解析】\n{snapshot['explanation']}")
    parts.append(f"【学生作答】\n{(student_answer or '').strip() or '（未作答）'}")
    return "\n\n".join(parts)


def _call_llm(model: str, prompt: str) -> tuple[str, int, int]:
    """同步调用大模型判卷，返回 (文本, input_tokens, output_tokens)；失败抛异常"""
    client = create_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        extra_body={"enable_thinking": False},
    )
    content = response.choices[0].message.content or ""
    usage = response.usage
    return content, (usage.prompt_tokens if usage else 0), (usage.completion_tokens if usage else 0)


def parse_judge_result(text: str) -> tuple[float, str]:
    """解析判卷 JSON，返回 (score_rate 钳到 [0,1], reason)；无法解析抛 ValueError"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("模型未返回 JSON")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("模型返回的 JSON 不是对象")
    rate = float(data.get("score_rate"))
    rate = min(1.0, max(0.0, rate))
    return rate, str(data.get("reason") or "").strip()


def round_half_step(value: float) -> float:
    """四舍五入到 0.5（不用内置 round，避免银行家舍入把 0.25 抹成 0）"""
    return math.floor(value * 2 + 0.5) / 2


def judge_subjective(model: str, row: dict, snapshot: dict,
                     user_id: int | None) -> tuple[float | None, str]:
    """单题主观判卷（失败重试 1 次）：返回 (score, llm_reason)

    两次都失败时返回 (None, '[判卷失败] …')，由调用方落库、试卷仍置 graded。
    每次成功的模型调用都按 task_type='exam' 记账。
    """
    full_score = float(row["full_score"])
    prompt = build_judge_prompt(dict(snapshot, question_type=row["question_type"]),
                               row.get("student_answer"), full_score)
    last_error = ""
    for attempt in (1, 2):
        try:
            text, tokens_in, tokens_out = _call_llm(model, prompt)
            if tokens_in or tokens_out:
                llm_store.record_usage(model, user_id, None, tokens_in, tokens_out,
                                       task_type="exam")
            rate, reason = parse_judge_result(text)
            return round_half_step(full_score * rate), reason
        except Exception as e:  # 网络异常 / 非 200 / JSON 解析失败统一重试
            last_error = str(e)
            logger.warning("主观题判卷失败（第 %d 次）exam_answer_id=%s: %s",
                           attempt, row.get("id"), last_error)
    return None, f"{JUDGE_FAIL_PREFIX} {last_error}"[:500]


def grade_exam(exam_id: int) -> None:
    """判卷主流程（同步，供后台线程与测试调用）：逐题判主观题 → 汇总总分置 graded

    后台线程无请求上下文，统一用 get_db_ctx()。仅处理 status='grading' 的试卷。
    """
    from app.exam import store  # 函数内导入：store 已导入本模块，避免循环依赖

    model = llm_store.get_active_model()
    with get_db_ctx() as db:
        exam = store.get_exam(db, exam_id)
        if exam is None or exam["status"] != "grading":
            logger.warning("跳过判卷 exam_id=%s status=%s", exam_id,
                           exam["status"] if exam else "not_found")
            return

        rows = [r for r in store.get_answers(db, exam_id)
                if not is_objective(r["question_type"])]
        for row in rows:
            score, reason = judge_subjective(model, row, store.load_snapshot(row),
                                             exam["user_id"])
            db.execute(
                "UPDATE exam_answers SET score = %s, llm_reason = %s WHERE id = %s",
                (score, reason, row["id"]),
            )
            db.commit()

        # SUM 自动忽略 NULL，等价于判卷失败题按 0 分计入总分
        cursor = db.execute(
            "SELECT COALESCE(SUM(score), 0) AS total FROM exam_answers WHERE exam_id = %s",
            (exam_id,),
        )
        obtained = round(float(cursor.fetchone()["total"]), 1)
        db.execute(
            "UPDATE exams SET status = 'graded', obtained_score = %s WHERE id = %s",
            (obtained, exam_id),
        )
        db.commit()

        # M3：错题自动入本（仅 score < full_score 或 score=NULL 的题）
        from app.profile.store import upsert_wrong_question
        all_rows = store.get_answers(db, exam_id)
        for row in all_rows:
            full = float(row["full_score"])
            score = row["score"]
            if score is None or float(score) < full:
                upsert_wrong_question(
                    db, exam["user_id"], exam["subject"],
                    row["question_id"], row["question_snapshot"],
                    row.get("student_answer"), exam_id,
                )
    logger.info("exam_graded id=%s 主观题=%d 总分=%.1f", exam_id, len(rows), obtained)


def submit_grading(exam_id: int) -> None:
    """把判卷任务丢进后台线程池，交卷接口立即返回（异常只记日志不外抛）"""
    _bg_executor.submit(_grade_exam_guarded, exam_id)


def _grade_exam_guarded(exam_id: int) -> None:
    try:
        grade_exam(exam_id)
    except Exception:
        logger.exception("判卷任务异常 exam_id=%s（试卷停留 grading，可由管理员复核）",
                         exam_id)
