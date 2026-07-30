"""考试数据访问（设计 §4.2/§4.5）：组卷、暂存、交卷判分、成绩单组装、掌握度归因

「每人仅 1 张 ongoing」用应用层校验 + 模块级锁防并发穿透（MySQL 无条件唯一约束）；
锁内只做「查 ongoing + 插占位试卷行」，抽题 HTTP 调用在锁外（避免全局串行）。
"""
import json
import logging
import threading

from app.exam import judger
from app.kb import client as kb_client

logger = logging.getLogger(__name__)

# 创卷临界区锁：保护「查 ongoing → 插占位行」，防并发穿透出两张 ongoing
_create_lock = threading.Lock()

WEAK_THRESHOLD = 0.6  # 薄弱知识点阈值（设计 §4.5）


class ExamOngoingExists(Exception):
    """已有未完成试卷（路由层转 409，返回该试卷 id）"""

    def __init__(self, exam_id: int):
        super().__init__(f"已有未完成的试卷（id={exam_id}）")
        self.exam_id = exam_id


class ExamNoQuestion(Exception):
    """所选范围内抽不到可用题目（路由层转 400）"""


class ExamSeqNotFound(Exception):
    """暂存的题号不属于本试卷（路由层转 400）"""

    def __init__(self, seqs: list[int]):
        super().__init__(f"题号不存在：{seqs}")
        self.seqs = seqs


# ========== 基础读取 ==========

def get_exam(db, exam_id: int) -> dict | None:
    cursor = db.execute(
        """SELECT id, user_id, subject, chapter_ids, status, question_count,
                  total_score, obtained_score, created_at, submitted_at
           FROM exams WHERE id = %s""",
        (exam_id,),
    )
    return cursor.fetchone()


def list_exams(db, user_id: int) -> list[dict]:
    """我的考试列表（倒序）"""
    cursor = db.execute(
        """SELECT id, subject, status, question_count, total_score,
                  obtained_score, created_at, submitted_at
           FROM exams WHERE user_id = %s
           ORDER BY id DESC""",
        (user_id,),
    )
    return list(cursor.fetchall())


def get_answers(db, exam_id: int) -> list[dict]:
    cursor = db.execute(
        """SELECT id, seq, question_id, question_type, question_snapshot,
                  full_score, student_answer, score, llm_reason, disputed
           FROM exam_answers WHERE exam_id = %s ORDER BY seq ASC""",
        (exam_id,),
    )
    return list(cursor.fetchall())


def load_snapshot(row: dict) -> dict:
    """解析题目快照；损坏时返回空 dict（不让单题脏数据打挂整卷）"""
    try:
        snap = json.loads(row["question_snapshot"])
        return snap if isinstance(snap, dict) else {}
    except (TypeError, ValueError):
        logger.warning("question_snapshot 解析失败 exam_answer_id=%s", row.get("id"))
        return {}


# ========== 创建试卷 ==========

def _reserve_exam(db, user_id: int, subject: str,
                  chapter_ids: list[str] | None) -> int:
    """锁内校验 ongoing 唯一并插入占位试卷行，返回 exam_id"""
    with _create_lock:
        cursor = db.execute(
            "SELECT id FROM exams WHERE user_id = %s AND status = 'ongoing' LIMIT 1",
            (user_id,),
        )
        row = cursor.fetchone()
        if row:
            raise ExamOngoingExists(row["id"])
        cursor = db.execute(
            """INSERT INTO exams (user_id, subject, chapter_ids, status,
                                  question_count, total_score)
               VALUES (%s, %s, %s, 'ongoing', 0, 0)""",
            (
                user_id, subject,
                json.dumps(chapter_ids, ensure_ascii=False) if chapter_ids else None,
            ),
        )
        db.commit()
        return cursor.lastrowid


def _drop_exam(db, exam_id: int) -> None:
    """抽题失败时清理占位行，避免学生被卡在 ongoing"""
    db.execute("DELETE FROM exams WHERE id = %s", (exam_id,))
    db.commit()


def create_exam(db, user_id: int, subject: str, chapter_ids: list[str] | None,
                counts: dict[str, int]) -> dict:
    """组卷：占位 → 抽题 → 逐题落 exam_answers（快照含答案解析）→ 回写题数与满分

    返回可直接喂 ExamCreateResponse 的 dict（questions 已剔除参考答案与解析）。
    抽题失败抛 KbDrawError（路由转 502），无可用题目抛 ExamNoQuestion（转 400）。
    """
    exam_id = _reserve_exam(db, user_id, subject, chapter_ids)
    try:
        questions = kb_client.draw_exam(subject, chapter_ids or None, counts)
    except Exception:
        _drop_exam(db, exam_id)
        raise

    seq = 0
    total_score = 0.0
    questions_out: list[dict] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        qtype = (q.get("question_type") or "").strip()
        qid = (q.get("question_id") or "").strip()
        if qtype not in judger.FULL_SCORES or not qid:
            logger.warning("跳过不合规题目 exam_id=%s question_id=%r type=%r",
                           exam_id, qid, qtype)
            continue
        seq += 1
        full = judger.FULL_SCORES[qtype]
        total_score += full
        db.execute(
            """INSERT INTO exam_answers
               (exam_id, seq, question_id, question_type, question_snapshot, full_score)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (exam_id, seq, qid[:32], qtype,
             json.dumps(q, ensure_ascii=False), full),
        )
        questions_out.append({
            "seq": seq,
            "question_type": qtype,
            "stem": q.get("stem"),
            "options": q.get("options"),
            "materials": q.get("materials"),
            "sub_questions": q.get("sub_questions"),
            "full_score": full,
        })

    if not questions_out:
        _drop_exam(db, exam_id)
        raise ExamNoQuestion("所选范围内没有可用题目，请调整章节或题量")

    db.execute(
        "UPDATE exams SET question_count = %s, total_score = %s WHERE id = %s",
        (seq, total_score, exam_id),
    )
    db.commit()
    logger.info("exam_created id=%s user_id=%s subject=%s questions=%d total=%.1f",
                exam_id, user_id, subject, seq, total_score)
    return {
        "id": exam_id,
        "status": "ongoing",
        "question_count": seq,
        "total_score": total_score,
        "questions": questions_out,
    }


# ========== 暂存作答 ==========

def save_answers(db, exam_id: int, items: list) -> None:
    """按 (exam_id, seq) 批量覆盖 student_answer；题号不属本卷抛 ExamSeqNotFound"""
    cursor = db.execute("SELECT seq FROM exam_answers WHERE exam_id = %s", (exam_id,))
    valid_seqs = {r["seq"] for r in cursor.fetchall()}
    unknown = [it.seq for it in items if it.seq not in valid_seqs]
    if unknown:
        raise ExamSeqNotFound(unknown)

    for it in items:
        db.execute(
            "UPDATE exam_answers SET student_answer = %s WHERE exam_id = %s AND seq = %s",
            (it.content, exam_id, it.seq),
        )
    db.commit()


# ========== 交卷 ==========

def submit_exam(db, exam_id: int) -> tuple[float, int]:
    """客观题即时判分并落库；有主观题置 grading，否则直接 graded 汇总总分

    返回 (objective_score, pending_subjective)。
    """
    rows = get_answers(db, exam_id)
    objective_score = 0.0
    pending = 0
    for row in rows:
        if judger.is_objective(row["question_type"]):
            score = judger.judge_objective(
                row["question_type"], load_snapshot(row), row["student_answer"]
            )
            db.execute("UPDATE exam_answers SET score = %s WHERE id = %s",
                       (score, row["id"]))
            objective_score += score
        else:
            pending += 1

    if pending:
        db.execute(
            "UPDATE exams SET status = 'grading', submitted_at = NOW() WHERE id = %s",
            (exam_id,),
        )
    else:
        db.execute(
            """UPDATE exams SET status = 'graded', submitted_at = NOW(),
                                obtained_score = %s WHERE id = %s""",
            (objective_score, exam_id),
        )
    db.commit()
    return round(objective_score, 1), pending


def mark_disputed(db, answer_id: int) -> None:
    db.execute("UPDATE exam_answers SET disputed = 1 WHERE id = %s", (answer_id,))
    db.commit()


# ========== 成绩单与掌握度 ==========

def chapter_of(kp_id: str) -> str:
    """章节 id 取知识点 id 前两段（ACC-03-02-01 → ACC-03）"""
    parts = kp_id.split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else kp_id


def compute_mastery(answers: list[dict]) -> dict:
    """掌握度归因（设计 §4.5）

    - 知识点掌握度 = Σ该知识点关联题得分 / Σ满分（一题多知识点不摊分）
    - 章节掌握度 = 章内各知识点掌握度按其关联题满分加权平均（等价于累计得分/累计满分）
    - 薄弱知识点 = 掌握度 < 0.6，按掌握度升序
    入参每项需含 knowledge_point_ids / score / full_score（score 为 None 按 0 计）。
    """
    kp_stat: dict[str, list[float]] = {}
    for a in answers:
        full = float(a.get("full_score") or 0)
        if full <= 0:
            continue
        got = float(a.get("score") or 0)
        for kp in a.get("knowledge_point_ids") or []:
            stat = kp_stat.setdefault(kp, [0.0, 0.0])
            stat[0] += got
            stat[1] += full

    by_kp = [
        {"kp_id": kp, "rate": round(got / full, 4)}
        for kp, (got, full) in sorted(kp_stat.items()) if full > 0
    ]

    chapter_stat: dict[str, list[float]] = {}
    for kp, (got, full) in kp_stat.items():
        if full <= 0:
            continue
        stat = chapter_stat.setdefault(chapter_of(kp), [0.0, 0.0])
        stat[0] += got
        stat[1] += full
    by_chapter = [
        {"chapter_id": cid, "rate": round(got / full, 4)}
        for cid, (got, full) in sorted(chapter_stat.items()) if full > 0
    ]

    weak_kps = sorted(
        [x for x in by_kp if x["rate"] < WEAK_THRESHOLD],
        key=lambda x: (x["rate"], x["kp_id"]),
    )
    return {"by_kp": by_kp, "by_chapter": by_chapter, "weak_kps": weak_kps}


def build_detail(db, exam: dict, reveal: bool | None = None) -> dict:
    """组装成绩单详情：graded 后才展示参考答案/解析/得分/掌握度

    reveal=None 时按 status=='graded' 判定；管理端传 reveal=True 强制展示
    （用于复核 grading 中的试卷，但 grading 时主观题 score 仍为 NULL）。
    """
    if reveal is None:
        reveal = exam["status"] == "graded"
    rows = get_answers(db, exam["id"])

    answers = []
    graded_items = []
    for row in rows:
        snap = load_snapshot(row)
        kp_ids = [str(k) for k in (snap.get("knowledge_point_ids") or [])]
        score = None if row["score"] is None else float(row["score"])
        full_score = float(row["full_score"])
        answers.append({
            "seq": row["seq"],
            "question_type": row["question_type"],
            "stem": snap.get("stem"),
            "options": snap.get("options"),
            "materials": snap.get("materials"),
            "sub_questions": snap.get("sub_questions"),
            "my_answer": row["student_answer"],
            "correct_answer": snap.get("answer") if reveal else None,
            "explanation": snap.get("explanation") if reveal else None,
            "score": score if reveal else None,
            "full_score": full_score,
            "llm_reason": row["llm_reason"] if reveal else None,
            "disputed": int(row["disputed"] or 0),
            "knowledge_point_ids": kp_ids,
        })
        graded_items.append({
            "knowledge_point_ids": kp_ids,
            "score": score,
            "full_score": full_score,
        })

    return {
        "id": exam["id"],
        "subject": exam["subject"],
        "status": exam["status"],
        "question_count": exam["question_count"],
        "total_score": float(exam["total_score"]),
        "obtained_score": (
            None if exam["obtained_score"] is None else float(exam["obtained_score"])
        ),
        "created_at": str(exam["created_at"]),
        "submitted_at": None if exam["submitted_at"] is None else str(exam["submitted_at"]),
        "answers": answers,
        # 掌握度仅在 graded 后展示：grading 中主观题 score=NULL 会严重低估
        "mastery": compute_mastery(graded_items) if exam["status"] == "graded" else None,
    }


# ========== 管理端 ==========

def list_admin_exams(db, student_id: str | None = None, subject: str | None = None,
                     date_from: str | None = None, date_to: str | None = None,
                     page: int = 1, page_size: int = 20) -> dict:
    """管理端考试列表（含学生信息，按 id 倒序分页）"""
    where = "WHERE 1=1"
    params: list = []
    if student_id:
        where += " AND u.student_id = %s"
        params.append(student_id)
    if subject:
        where += " AND e.subject = %s"
        params.append(subject)
    if date_from:
        where += " AND DATE(e.created_at) >= %s"
        params.append(date_from)
    if date_to:
        where += " AND DATE(e.created_at) <= %s"
        params.append(date_to)

    cursor = db.execute(
        f"SELECT COUNT(*) AS cnt FROM exams e JOIN users u ON e.user_id = u.id {where}",
        params,
    )
    total = int(cursor.fetchone()["cnt"])

    offset = (page - 1) * page_size
    cursor = db.execute(
        f"""SELECT e.id, u.student_id, u.name AS student_name, e.subject, e.status,
                   e.question_count, e.total_score, e.obtained_score,
                   e.created_at, e.submitted_at
            FROM exams e JOIN users u ON e.user_id = u.id
            {where}
            ORDER BY e.id DESC
            LIMIT %s OFFSET %s""",
        params + [page_size, offset],
    )
    items = [
        {
            "id": r["id"],
            "student_id": r["student_id"],
            "student_name": r["student_name"],
            "subject": r["subject"],
            "status": r["status"],
            "question_count": r["question_count"],
            "total_score": float(r["total_score"]),
            "obtained_score": (
                None if r["obtained_score"] is None else float(r["obtained_score"])
            ),
            "created_at": str(r["created_at"]),
            "submitted_at": (
                None if r["submitted_at"] is None else str(r["submitted_at"])
            ),
        }
        for r in cursor.fetchall()
    ]
    return {"total": total, "items": items}


def update_answer_score(db, exam_id: int, seq: int,
                        score: float, reason: str | None) -> dict:
    """管理员复核改分：更新单题 score/llm_reason 后重算 exams.obtained_score

    score 范围由路由层校验 [0, full_score]。返回更新后的 seq/score/reason/总分。
    题号不存在抛 ExamSeqNotFound。
    """
    row = next((r for r in get_answers(db, exam_id) if r["seq"] == seq), None)
    if row is None:
        raise ExamSeqNotFound([seq])
    db.execute(
        "UPDATE exam_answers SET score = %s, llm_reason = %s WHERE id = %s",
        (score, reason, row["id"]),
    )
    cursor = db.execute(
        "SELECT COALESCE(SUM(score), 0) AS total FROM exam_answers WHERE exam_id = %s",
        (exam_id,),
    )
    obtained = round(float(cursor.fetchone()["total"]), 1)
    db.execute(
        "UPDATE exams SET obtained_score = %s WHERE id = %s",
        (obtained, exam_id),
    )
    db.commit()
    return {"seq": seq, "score": score, "llm_reason": reason, "obtained_score": obtained}
