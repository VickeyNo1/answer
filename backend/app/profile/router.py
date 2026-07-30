"""学生记忆路由（设计 §5.4-5.5）

学生端 3 接口：错题本列表 / 重练判分 / 我的画像
管理端 2 接口：查看学生画像 / 全校错题统计
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.deps import get_current_user, require_admin
from app.database import get_db
from app.admin.entitlements import get_effective_memory_enabled
from app.profile import store as profile_store
from app.models import (
    PaginatedWrongQuestions,
    WrongQuestionRetryRequest,
    WrongQuestionRetryResponse,
    ProfileOut,
    WeakKpItem,
    RecentExamSummary,
    AdminStudentProfile,
    WrongStatsOut,
    HotWrongKpItem,
    AdminWrongStatItem,
)

router = APIRouter(prefix="/api", tags=["学生记忆"])
admin_router = APIRouter(prefix="/api/admin", tags=["管理端-学生记忆"])


# ========== 学生端 ==========


@router.get("/wrong-questions", response_model=PaginatedWrongQuestions)
async def list_wrong_questions(
    subject: str | None = Query(None, description="按科目筛选"),
    chapter_id: str | None = Query(None, description="按章节 ID 筛选"),
    mastered: int | None = Query(None, description="0=未掌握 / 1=已掌握"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """错题本列表（记忆开关关时 403）"""
    if not get_effective_memory_enabled(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="记忆功能未开启",
        )
    return profile_store.list_wrong_questions(
        db, current_user["id"], subject, chapter_id, mastered, page, page_size,
    )


@router.post("/wrong-questions/{wq_id}/retry",
             response_model=WrongQuestionRetryResponse)
async def retry_wrong_question(
    wq_id: int,
    req: WrongQuestionRetryRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """重练判分（记忆开关关时 403；非本人 403；不存在 404）"""
    if not get_effective_memory_enabled(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="记忆功能未开启",
        )
    # 区分不存在(404)与非本人(403)
    cursor = db.execute(
        "SELECT user_id FROM wrong_questions WHERE id = %s", (wq_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="错题不存在",
        )
    if row["user_id"] != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权操作他人的错题",
        )
    result = profile_store.retry_wrong_question(db, wq_id, current_user["id"], req.answer)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="错题不存在",
        )
    return result


@router.get("/me/profile", response_model=ProfileOut)
async def get_my_profile(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """我的画像（透明可见；开关关时仍可看，但 memory_enabled=false）"""
    memory_enabled = get_effective_memory_enabled(current_user)
    profile_row = profile_store.get_profile(db, current_user["id"])
    style_profile = (profile_row or {}).get("style_profile") if profile_row else None
    weak_kps = profile_store.compute_weak_kps(db, current_user["id"])
    recent_exam = profile_store.get_recent_exam(db, current_user["id"])

    return ProfileOut(
        style_profile=style_profile,
        weak_kps=[WeakKpItem(**kp) for kp in weak_kps],
        recent_exam=RecentExamSummary(**recent_exam) if recent_exam else None,
        memory_enabled=memory_enabled,
    )


# ========== 管理端 ==========


@admin_router.get("/students/{student_id}/profile",
                  response_model=AdminStudentProfile)
async def admin_get_student_profile(
    student_id: int,
    admin: dict = Depends(require_admin),
    db=Depends(get_db),
):
    """查看指定学生画像（style_profile + weak_kps + recent_exam + wrong_stats）"""
    cursor = db.execute(
        "SELECT id FROM users WHERE id = %s AND role = 'student'", (student_id,),
    )
    if cursor.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="学生不存在",
        )
    data = profile_store.get_admin_student_profile(db, student_id)
    return AdminStudentProfile(
        style_profile=data["style_profile"],
        weak_kps=[WeakKpItem(**kp) for kp in data["weak_kps"]],
        recent_exam=RecentExamSummary(**data["recent_exam"]) if data["recent_exam"] else None,
        wrong_stats=WrongStatsOut(
            total=data["wrong_stats"]["total"],
            unmastered=data["wrong_stats"]["unmastered"],
            hot_wrong_kps=[
                HotWrongKpItem(**kp) for kp in data["wrong_stats"]["hot_wrong_kps"]
            ],
        ),
    )


@admin_router.get("/wrong-questions/stats",
                  response_model=list[AdminWrongStatItem])
async def admin_wrong_question_stats(
    days: int = Query(30, ge=1, le=365, description="统计近 N 天"),
    top: int = Query(10, ge=1, le=50, description="取 Top N 知识点"),
    admin: dict = Depends(require_admin),
    db=Depends(get_db),
):
    """全校错题 Top 知识点统计"""
    return profile_store.list_admin_wrong_stats(db, days, top)
