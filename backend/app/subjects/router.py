"""科目路由：全员可见的科目列表 + 管理员科目 CRUD"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import get_current_user, require_admin
from app.database import get_db_ctx
from app.models import SubjectOut, SubjectCreate, SubjectUpdate
from app.knowledge import chroma_service

# 全员可访问：科目列表
router = APIRouter(prefix="/api/subjects", tags=["科目"])
# 管理员：科目 CRUD
admin_router = APIRouter(prefix="/api/admin/subjects", tags=["科目管理"])


def _row_to_subject(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "description": row["description"] or "",
        "sort_order": row["sort_order"],
        "created_at": str(row["created_at"]),
    }


def _list_subjects() -> list[dict]:
    with get_db_ctx() as db:
        cursor = db.execute(
            "SELECT * FROM subjects ORDER BY category ASC, sort_order ASC, id ASC"
        )
        return [_row_to_subject(r) for r in cursor.fetchall()]


@router.get("", response_model=list[SubjectOut])
async def list_subjects(current_user: dict = Depends(get_current_user)):
    """获取所有科目（全员可见，供选择）"""
    return _list_subjects()


@admin_router.post("", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
async def create_subject(req: SubjectCreate, admin: dict = Depends(require_admin)):
    """新增科目"""
    if req.category not in ("general", "professional"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="category 只能是 general 或 professional",
        )
    with get_db_ctx() as db:
        cursor = db.execute("SELECT id FROM subjects WHERE name = ?", (req.name,))
        if cursor.fetchone() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"科目 {req.name} 已存在",
            )
        cursor = db.execute(
            """INSERT INTO subjects (name, category, description, sort_order)
               VALUES (?, ?, ?, ?)""",
            (req.name, req.category, req.description, req.sort_order),
        )
        db.commit()
        cursor = db.execute("SELECT * FROM subjects WHERE id = ?", (cursor.lastrowid,))
        return _row_to_subject(cursor.fetchone())


@admin_router.put("/{subject_id}", response_model=SubjectOut)
async def update_subject(
    subject_id: int,
    req: SubjectUpdate,
    admin: dict = Depends(require_admin),
):
    """修改科目"""
    with get_db_ctx() as db:
        cursor = db.execute("SELECT id FROM subjects WHERE id = ?", (subject_id,))
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="科目不存在",
            )
        updates = []
        params = []
        for key in ("name", "category", "description", "sort_order"):
            value = getattr(req, key)
            if value is not None:
                updates.append(f"{key} = ?")
                params.append(value)
        if updates:
            params.append(subject_id)
            db.execute(f"UPDATE subjects SET {', '.join(updates)} WHERE id = ?", params)
            db.commit()
        cursor = db.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,))
        return _row_to_subject(cursor.fetchone())


@admin_router.delete("/{subject_id}")
async def delete_subject(subject_id: int, admin: dict = Depends(require_admin)):
    """删除科目（其名下文档在知识库中重置为未分类，不阻塞）"""
    with get_db_ctx() as db:
        cursor = db.execute("SELECT id FROM subjects WHERE id = ?", (subject_id,))
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="科目不存在",
            )
        db.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
        db.commit()

    # 将该科目名下文档片段重置为未分类
    try:
        chroma_service.clear_subject(subject_id)
    except Exception:
        pass

    return {"message": "ok"}
