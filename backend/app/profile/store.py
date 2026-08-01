"""学生记忆数据访问（设计 §5.1-5.4）：错题本 CRUD + 画像 + 薄弱点实时聚合 + 记忆注入

薄弱点不落快照表，注入前实时 SQL 聚合（考试归因 ∪ 点踩 kp）。
错题入本用 INSERT ... ON DUPLICATE KEY UPDATE 保证原子性。
"""
import json
import logging

from app.exam import judger
from app.exam.store import load_snapshot, chapter_of
from app.admin.entitlements import get_effective_memory_enabled

logger = logging.getLogger(__name__)

WEAK_THRESHOLD = 0.6
MAX_PROFILE_CHARS = 200
# 记忆注入 token 硬预算 ≤300，按中文 1 字 ≈ 0.5 token 估算 → 600 字符
MEMORY_CHAR_BUDGET = 600


# ========== 错题本 ==========

def list_wrong_questions(db, user_id: int, subject: str | None = None,
                         chapter_id: str | None = None, mastered: int | None = None,
                         page: int = 1, page_size: int = 20) -> dict:
    """错题本列表（分页 + 筛选），按 last_wrong_at 倒序"""
    where = "WHERE user_id = %s"
    params: list = [user_id]
    if subject:
        where += " AND subject = %s"
        params.append(subject)
    if mastered is not None:
        where += " AND mastered = %s"
        params.append(int(mastered))

    cursor = db.execute(
        f"SELECT COUNT(*) AS cnt FROM wrong_questions {where}", params,
    )
    total = int(cursor.fetchone()["cnt"])

    offset = (page - 1) * page_size
    cursor = db.execute(
        f"""SELECT id, subject, question_id, question_snapshot, my_answer,
                   wrong_count, mastered, last_wrong_at, source_exam_id, last_mastered_at
            FROM wrong_questions {where}
            ORDER BY last_wrong_at DESC
            LIMIT %s OFFSET %s""",
        params + [page_size, offset],
    )
    items = []
    for r in cursor.fetchall():
        snap = _safe_json(r["question_snapshot"])
        # 章节筛选（快照内 chapter_id）
        if chapter_id:
            q_chapter = snap.get("chapter_id", "")
            if q_chapter != chapter_id:
                continue
        items.append({
            "id": r["id"],
            "question_type": snap.get("question_type"),
            "stem": snap.get("stem"),
            "options": snap.get("options"),
            "materials": snap.get("materials"),
            "sub_questions": snap.get("sub_questions"),
            "wrong_count": int(r["wrong_count"]),
            "mastered": int(r["mastered"]),
            "last_wrong_at": str(r["last_wrong_at"]),
            "knowledge_point_ids": snap.get("knowledge_point_ids") or [],
            "subject": r["subject"],
        })
    # 章节筛选在应用层做（快照内字段），需重算 total
    if chapter_id:
        total = len(items)
    return {"total": total, "items": items}


def get_wrong_question(db, wq_id: int, user_id: int) -> dict | None:
    """取单条错题（含完整快照，用于重练）"""
    cursor = db.execute(
        """SELECT id, user_id, subject, question_id, question_snapshot, my_answer,
                  wrong_count, mastered, last_wrong_at,
                  source_exam_id, last_mastered_at
           FROM wrong_questions WHERE id = %s AND user_id = %s""",
        (wq_id, user_id),
    )
    return cursor.fetchone()


def upsert_wrong_question(db, user_id: int, subject: str, question_id: str,
                          snapshot_json: str, my_answer: str | None,
                          source_exam_id: int | None) -> None:
    """错题入本（UPSERT）：命中 UNIQUE(user_id, question_id) 时累加错次、重置掌握"""
    db.execute(
        """INSERT INTO wrong_questions
           (user_id, subject, question_id, question_snapshot, my_answer, wrong_count,
            mastered, last_wrong_at, source_exam_id)
           VALUES (%s, %s, %s, %s, %s, 1, 0, NOW(), %s)
           ON DUPLICATE KEY UPDATE
             wrong_count = wrong_count + 1,
             mastered = 0,
             last_wrong_at = NOW(),
             my_answer = VALUES(my_answer),
             source_exam_id = VALUES(source_exam_id),
             question_snapshot = VALUES(question_snapshot)""",
        (user_id, subject, question_id[:32], snapshot_json, my_answer, source_exam_id),
    )
    db.commit()


def retry_wrong_question(db, wq_id: int, user_id: int,
                         answer: str) -> dict | None:
    """重练判分：客观题程序判、主观题 LLM 判（score_rate≥0.6 视为答对）

    返回 {correct, correct_answer, explanation, mastered} 或 None（题不存在）。
    """
    row = get_wrong_question(db, wq_id, user_id)
    if row is None:
        return None
    snap = _safe_json(row["question_snapshot"])
    qtype = snap.get("question_type", "")

    full = judger.FULL_SCORES.get(qtype, 0.0)
    if judger.is_objective(qtype):
        score = judger.judge_objective(qtype, snap, answer)
        correct = score >= full if full > 0 else False
    else:
        # 构造 judger.judge_subjective 所需的 row（含 question_type/full_score/student_answer/id）
        judge_row = {
            "id": row["id"],
            "question_type": qtype,
            "full_score": full,
            "student_answer": answer,
        }
        score, reason = judger.judge_subjective(
            llm_store_get_model(), judge_row, snap, user_id,
        )
        rate = (score / full) if full > 0 and score is not None else 0.0
        correct = rate >= 0.6

    if correct:
        db.execute(
            "UPDATE wrong_questions SET mastered = 1, last_mastered_at = NOW() WHERE id = %s",
            (wq_id,),
        )
    else:
        db.execute(
            """UPDATE wrong_questions SET wrong_count = wrong_count + 1,
                  mastered = 0, my_answer = %s, last_wrong_at = NOW() WHERE id = %s""",
            (answer, wq_id),
        )
    db.commit()

    return {
        "correct": correct,
        "correct_answer": snap.get("answer"),
        "explanation": snap.get("explanation"),
        "mastered": 1 if correct else 0,
    }


# ========== 画像 ==========

def get_profile(db, user_id: int) -> dict | None:
    cursor = db.execute(
        "SELECT user_id, style_profile, dialog_count_since_update, updated_at "
        "FROM student_profiles WHERE user_id = %s",
        (user_id,),
    )
    return cursor.fetchone()


def upsert_profile(db, user_id: int, style_profile: str) -> None:
    """写入画像文本（覆盖式），截断到 200 字符"""
    profile = style_profile[:MAX_PROFILE_CHARS]
    db.execute(
        """INSERT INTO student_profiles (user_id, style_profile, dialog_count_since_update)
           VALUES (%s, %s, 0)
           ON DUPLICATE KEY UPDATE style_profile = %s, dialog_count_since_update = 0""",
        (user_id, profile, profile),
    )
    db.commit()


def increment_dialog_count(db, user_id: int) -> int:
    """对话计数 +1，返回新计数值（无行时自动创建）"""
    db.execute(
        "INSERT IGNORE INTO student_profiles (user_id) VALUES (%s)",
        (user_id,),
    )
    db.execute(
        "UPDATE student_profiles SET dialog_count_since_update = dialog_count_since_update + 1 "
        "WHERE user_id = %s",
        (user_id,),
    )
    db.commit()
    cursor = db.execute(
        "SELECT dialog_count_since_update FROM student_profiles WHERE user_id = %s",
        (user_id,),
    )
    row = cursor.fetchone()
    return int(row["dialog_count_since_update"]) if row else 0


def reset_dialog_count(db, user_id: int) -> None:
    db.execute(
        "UPDATE student_profiles SET dialog_count_since_update = 0 WHERE user_id = %s",
        (user_id,),
    )
    db.commit()


# ========== 薄弱点实时聚合 ==========

def compute_weak_kps(db, user_id: int) -> list[dict]:
    """薄弱知识点（设计 §5.1）：考试归因（rate<0.6）∪ 点踩 kp_ids（辅）

    来源1: exam_answers JOIN exams WHERE graded，按 kp 聚合得分率<0.6
    来源2: feedbacks.rating='down' JOIN messages 取 knowledge_point_ids
    合并后按 rate 升序取 Top5。
    """
    # 来源1：考试归因
    cursor = db.execute(
        """SELECT ea.question_snapshot, ea.score, ea.full_score
           FROM exam_answers ea
           JOIN exams e ON ea.exam_id = e.id
           WHERE e.user_id = %s AND e.status = 'graded'""",
        (user_id,),
    )
    kp_stat: dict[str, dict] = {}  # kp_id -> {got, full, wrong}
    for r in cursor.fetchall():
        snap = _safe_json(r["question_snapshot"])
        full = float(r["full_score"] or 0)
        got = float(r["score"] or 0) if r["score"] is not None else 0.0
        for kp in snap.get("knowledge_point_ids") or []:
            stat = kp_stat.setdefault(kp, {"got": 0.0, "full": 0.0, "wrong": 0})
            stat["got"] += got
            stat["full"] += full
            if got < full:
                stat["wrong"] += 1

    # 来源2：点踩消息的 kp_ids
    cursor = db.execute(
        """SELECT m.knowledge_point_ids
           FROM feedbacks f
           JOIN messages m ON f.message_id = m.id
           JOIN conversations c ON m.conversation_id = c.id
           WHERE c.user_id = %s AND f.rating = 'down'""",
        (user_id,),
    )
    feedback_kps: dict[str, int] = {}
    for r in cursor.fetchall():
        raw = r["knowledge_point_ids"]
        if not raw:
            continue
        try:
            kp_list = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(kp_list, list):
            for kp in kp_list:
                feedback_kps[kp] = feedback_kps.get(kp, 0) + 1

    # 合并：考试归因为主，点踩 kp 补充（不在考试中的按 rate=0.3 计）
    result: dict[str, dict] = {}
    for kp, stat in kp_stat.items():
        if stat["full"] > 0:
            rate = round(stat["got"] / stat["full"], 4)
            if rate < WEAK_THRESHOLD:
                result[kp] = {"kp_id": kp, "rate": rate, "wrong_count": stat["wrong"]}

    for kp, cnt in feedback_kps.items():
        if kp not in result:
            result[kp] = {"kp_id": kp, "rate": 0.3, "wrong_count": cnt}
        else:
            result[kp]["wrong_count"] += cnt

    weak = sorted(result.values(), key=lambda x: (x["rate"], x["kp_id"]))[:5]
    return weak


def get_recent_exam(db, user_id: int) -> dict | None:
    """最近一张已判卷试卷摘要"""
    cursor = db.execute(
        """SELECT id, subject, total_score, obtained_score, submitted_at
           FROM exams WHERE user_id = %s AND status = 'graded'
           ORDER BY submitted_at DESC LIMIT 1""",
        (user_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "subject": row["subject"],
        "score": int(row["obtained_score"]) if row["obtained_score"] is not None else 0,
        "total": int(float(row["total_score"])),
        "date": str(row["submitted_at"])[:10] if row["submitted_at"] else None,
    }


# ========== 记忆注入块 ==========

def build_memory_block(db, user_id: int, user: dict) -> str | None:
    """组装记忆注入块（设计 §5.3：≤300 token）

    构成与裁剪顺序：薄弱点（永远保留）> 学习风格（超预算第2砍）> 最近考试（第1砍）
    三项全空或记忆开关关闭时返回 None（整块不注入）。
    """
    if not get_effective_memory_enabled(user):
        return None

    weak_kps = compute_weak_kps(db, user_id)
    profile_row = get_profile(db, user_id)
    style_profile = (profile_row or {}).get("style_profile") if profile_row else None
    recent_exam = get_recent_exam(db, user_id)

    if not weak_kps and not style_profile and not recent_exam:
        return None

    parts: list[str] = []

    # 薄弱知识点（永远保留）
    if weak_kps:
        kp_strs = [
            f"{kp['kp_id']}(掌握{int(kp['rate'] * 100)}%,错{kp['wrong_count']}题)"
            for kp in weak_kps
        ]
        parts.append(f"薄弱知识点: {'; '.join(kp_strs)}")

    # 学习风格（超预算第2砍）
    if style_profile:
        parts.append(f"学习风格: {style_profile}")

    # 最近考试（超预算第1砍）
    if recent_exam:
        parts.append(
            f"最近考试: {recent_exam['date']} {recent_exam['subject']} "
            f"{recent_exam['score']}/{recent_exam['total']}分。"
        )

    block = "【学生情况】\n" + "\n".join(parts)

    # 超预算裁剪：先砍最近考试，再砍学习风格
    if len(block) > MEMORY_CHAR_BUDGET and recent_exam:
        parts = [p for p in parts if not p.startswith("最近考试")]
        block = "【学生情况】\n" + "\n".join(parts) if parts else ""
    if len(block) > MEMORY_CHAR_BUDGET and style_profile:
        parts = [p for p in parts if not p.startswith("学习风格")]
        block = "【学生情况】\n" + "\n".join(parts) if parts else ""

    return block if block else None


# ========== 管理端 ==========

def get_admin_student_profile(db, user_id: int) -> dict:
    """管理端查看指定学生画像：style_profile + weak_kps + 错题统计"""
    profile_row = get_profile(db, user_id)
    style_profile = (profile_row or {}).get("style_profile") if profile_row else None

    weak_kps = compute_weak_kps(db, user_id)
    recent_exam = get_recent_exam(db, user_id)

    # 错题统计
    cursor = db.execute(
        "SELECT COUNT(*) AS total, SUM(mastered = 0) AS unmastered FROM wrong_questions WHERE user_id = %s",
        (user_id,),
    )
    stat = cursor.fetchone()
    total_wrong = int(stat["total"] or 0) if stat else 0
    unmastered = int(stat["unmastered"] or 0) if stat else 0

    # 高频错题知识点 Top3
    cursor = db.execute(
        """SELECT question_snapshot FROM wrong_questions
           WHERE user_id = %s AND mastered = 0""",
        (user_id,),
    )
    kp_wrong: dict[str, int] = {}
    for r in cursor.fetchall():
        snap = _safe_json(r["question_snapshot"])
        for kp in snap.get("knowledge_point_ids") or []:
            kp_wrong[kp] = kp_wrong.get(kp, 0) + 1
    hot_wrong = sorted(kp_wrong.items(), key=lambda x: -x[1])[:3]
    hot_wrong_kps = [{"kp_id": kp, "wrong_count": cnt} for kp, cnt in hot_wrong]

    return {
        "style_profile": style_profile,
        "weak_kps": weak_kps,
        "recent_exam": recent_exam,
        "wrong_stats": {
            "total": total_wrong,
            "unmastered": unmastered,
            "hot_wrong_kps": hot_wrong_kps,
        },
    }


def list_admin_wrong_stats(db, days: int = 30, top: int = 10) -> list[dict]:
    """全校错题 Top 知识点统计（按 last_wrong_at 近 days 天）"""
    cursor = db.execute(
        """SELECT question_snapshot, user_id FROM wrong_questions
           WHERE last_wrong_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)""",
        (days,),
    )
    kp_stat: dict[str, set] = {}
    for r in cursor.fetchall():
        snap = _safe_json(r["question_snapshot"])
        for kp in snap.get("knowledge_point_ids") or []:
            if kp not in kp_stat:
                kp_stat[kp] = {"wrong_count": 0, "students": set()}
            kp_stat[kp]["wrong_count"] += 1
            kp_stat[kp]["students"].add(r["user_id"])

    result = [
        {"kp_id": kp, "wrong_count": v["wrong_count"], "student_count": len(v["students"])}
        for kp, v in kp_stat.items()
    ]
    result.sort(key=lambda x: -x["wrong_count"])
    return result[:top]


# ========== 工具 ==========

def _safe_json(raw: str | None) -> dict:
    """安全解析 JSON 字符串，失败返回空 dict"""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def llm_store_get_model() -> str:
    """延迟导入避免循环依赖"""
    from app.llm import store as llm_store
    return llm_store.get_active_model()
