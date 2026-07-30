"""考试路由（设计 §4.6）：学生端 6 接口（创建/暂存/交卷/列表/详情/异议）"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.deps import get_current_user, require_admin
from app.database import get_db
from app.exam import judger, store
from app.kb.client import KbDrawError
from app.kb.subjects import DEFAULT_SUBJECT, is_valid_subject
from app.models import (
    AdminExamListOut,
    AdminScoreUpdateRequest,
    AdminScoreUpdateResponse,
    ExamAnswersSaveRequest,
    ExamCreateRequest,
    ExamCreateResponse,
    ExamDetailResponse,
    ExamListItem,
    ExamSubmitResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exams", tags=["考试"])

MAX_PER_TYPE = 50  # 单题型题量上限（知识库侧契约，见 doc/知识库对接文档.md §1.6）


def _validate_counts(counts: dict[str, int]) -> dict[str, int]:
    """校验题型枚举与数量，返回剔除 0 值后的 counts（全 0 → 400）"""
    cleaned: dict[str, int] = {}
    for qtype, num in (counts or {}).items():
        if qtype not in judger.FULL_SCORES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的题型：{qtype}",
            )
        if not isinstance(num, int) or num < 0 or num > MAX_PER_TYPE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{qtype} 题量需为 0-{MAX_PER_TYPE} 的整数",
            )
        if num > 0:
            cleaned[qtype] = num
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请至少选择 1 道题",
        )
    return cleaned


def _owned_exam(db, exam_id: int, user_id: int) -> dict:
    """取试卷并校验归属（不存在 404 / 非本人 403）"""
    exam = store.get_exam(db, exam_id)
    if exam is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="试卷不存在",
        )
    if exam["user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问他人的试卷",
        )
    return exam


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ExamCreateResponse)
async def create_exam(
    req: ExamCreateRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """创建试卷（组卷）：每人同时只允许 1 张 ongoing；抽题失败不降级直接 502"""
    counts = _validate_counts(req.counts)
    subject = req.subject if req.subject and is_valid_subject(req.subject) else DEFAULT_SUBJECT

    try:
        return store.create_exam(db, current_user["id"], subject, req.chapter_ids, counts)
    except store.ExamOngoingExists as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"你还有未完成的试卷（id={e.exam_id}），请先完成或交卷",
        )
    except store.ExamNoQuestion as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except KbDrawError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="知识库暂时不可用，请稍后再试",
        )


@router.put("/{exam_id}/answers")
async def save_answers(
    exam_id: int,
    req: ExamAnswersSaveRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """暂存作答（可多次调用覆盖）：仅本人的 ongoing 试卷可暂存"""
    exam = _owned_exam(db, exam_id, current_user["id"])
    if exam["status"] != "ongoing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="试卷已交卷，不能再修改作答",
        )
    if not req.answers:
        return {"message": "ok"}

    try:
        store.save_answers(db, exam_id, req.answers)
    except store.ExamSeqNotFound as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"message": "ok"}


@router.post("/{exam_id}/submit", response_model=ExamSubmitResponse)
async def submit_exam(
    exam_id: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """交卷：客观题即时判分；有主观题置 grading 并提交后台 LLM 判卷，否则直接 graded"""
    exam = _owned_exam(db, exam_id, current_user["id"])
    if exam["status"] != "ongoing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="试卷已交卷",
        )

    objective_score, pending = store.submit_exam(db, exam_id)
    if pending:
        # 主观题交给后台线程池判卷，本接口立即返回；学生端轮询详情等 graded
        judger.submit_grading(exam_id)
        logger.info("exam_submit exam_id=%s 待判主观题=%d 已提交后台判卷",
                    exam_id, pending)
    return ExamSubmitResponse(
        id=exam_id,
        status="grading" if pending else "graded",
        objective_score=objective_score,
        pending_subjective=pending,
    )


@router.get("", response_model=list[ExamListItem])
async def list_exams(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """我的考试列表（倒序）"""
    rows = store.list_exams(db, current_user["id"])
    return [
        ExamListItem(
            id=r["id"],
            subject=r["subject"],
            status=r["status"],
            question_count=r["question_count"],
            total_score=float(r["total_score"]),
            obtained_score=None if r["obtained_score"] is None else float(r["obtained_score"]),
            created_at=str(r["created_at"]),
            submitted_at=None if r["submitted_at"] is None else str(r["submitted_at"]),
        )
        for r in rows
    ]


@router.get("/{exam_id}", response_model=ExamDetailResponse)
async def get_exam_detail(
    exam_id: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """成绩单详情：graded 后才返回参考答案/解析/得分/掌握度"""
    exam = _owned_exam(db, exam_id, current_user["id"])
    return store.build_detail(db, exam)


@router.post("/{exam_id}/answers/{seq}/dispute")
async def dispute_answer(
    exam_id: int,
    seq: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """主观题判分异议：仅 graded 后的主观题可标记"""
    exam = _owned_exam(db, exam_id, current_user["id"])
    if exam["status"] != "graded":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="判卷完成后才能提出异议",
        )

    row = next((r for r in store.get_answers(db, exam_id) if r["seq"] == seq), None)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="题号不存在",
        )
    if judger.is_objective(row["question_type"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="客观题判分由程序判定，不支持异议",
        )

    store.mark_disputed(db, row["id"])
    return {"message": "ok"}


# ========== 管理端（v4.0 M2 B4） ==========

admin_router = APIRouter(prefix="/api/admin/exams", tags=["管理员-考试"])


@admin_router.get("", response_model=AdminExamListOut)
async def admin_list_exams(
    student_id: str | None = Query(None, description="按学号筛选"),
    subject: str | None = Query(None, description="按科目枚举筛选"),
    date_from: str | None = Query(None, description="起始日期 YYYY-MM-DD"),
    date_to: str | None = Query(None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: dict = Depends(require_admin),
    db=Depends(get_db),
):
    """管理端考试列表（筛选 + 分页，含学生信息）"""
    return store.list_admin_exams(db, student_id, subject, date_from, date_to,
                                  page, page_size)


@admin_router.get("/{exam_id}", response_model=ExamDetailResponse)
async def admin_get_exam(
    exam_id: int,
    admin: dict = Depends(require_admin),
    db=Depends(get_db),
):
    """管理端考试详情：grading 中也展示参考答案/解析/得分（复核用）"""
    exam = store.get_exam(db, exam_id)
    if exam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="试卷不存在")
    return store.build_detail(db, exam, reveal=True)


@admin_router.put("/{exam_id}/answers/{seq}/score",
                  response_model=AdminScoreUpdateResponse)
async def admin_update_score(
    exam_id: int,
    seq: int,
    req: AdminScoreUpdateRequest,
    admin: dict = Depends(require_admin),
    db=Depends(get_db),
):
    """管理员复核改分：score 范围 [0, full_score]，改后重算总分"""
    exam = store.get_exam(db, exam_id)
    if exam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="试卷不存在")

    row = next((r for r in store.get_answers(db, exam_id) if r["seq"] == seq), None)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题号不存在")

    full = float(row["full_score"])
    if req.score < 0 or req.score > full:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"分数需在 0-{full} 之间",
        )
    return store.update_answer_score(db, exam_id, seq, req.score, req.reason)
