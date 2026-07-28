"""管理员模块：学生 CRUD + Excel 批量导入 + 统计数据"""
import io
import bcrypt
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status
from openpyxl import load_workbook

from app.auth.deps import require_admin
from app.database import get_db, get_db_ctx
from app.models import (
    StudentCreate,
    StudentUpdate,
    UserInfo,
    StatsResponse,
)
from app.admin.stats import get_stats

router = APIRouter(prefix="/api/admin", tags=["管理员"])


def _hash_password(password: str) -> str:
    """bcrypt 加密密码"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _row_to_userinfo(row) -> dict:
    """将查询结果行转换为 UserInfo 兼容的 dict"""
    return {
        "id": row["id"],
        "student_id": row["student_id"],
        "name": row["name"],
        "role": row["role"],
        "created_at": str(row["created_at"]),
    }


# ========== 学生 CRUD ==========


@router.post("/students", response_model=UserInfo, status_code=status.HTTP_201_CREATED)
async def create_student(
    req: StudentCreate,
    admin: dict = Depends(require_admin),
):
    """创建学生账号"""
    with get_db_ctx() as db:
        # 检查学号是否已存在
        cursor = db.execute(
            "SELECT id FROM users WHERE student_id = %s", (req.student_id,)
        )
        if cursor.fetchone() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"学号 {req.student_id} 已存在",
            )

        password_hash = _hash_password(req.password)
        cursor = db.execute(
            """
            INSERT INTO users (student_id, password_hash, name, role)
            VALUES (%s, %s, %s, 'student')
            """,
            (req.student_id, password_hash, req.name),
        )
        db.commit()

        # 查询新建的用户
        cursor = db.execute("SELECT * FROM users WHERE id = %s", (cursor.lastrowid,))
        return _row_to_userinfo(cursor.fetchone())


@router.get("/students")
async def list_students(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, description="搜索学号或姓名"),
    admin: dict = Depends(require_admin),
):
    """获取学生列表（分页）"""
    with get_db_ctx() as db:
        # 构建查询条件
        where = "WHERE role = 'student'"
        params = []
        if keyword:
            where += " AND (student_id LIKE %s OR name LIKE %s)"
            kw = f"%{keyword}%"
            params.extend([kw, kw])

        # 查询总数
        cursor = db.execute(f"SELECT COUNT(*) as cnt FROM users {where}", params)
        total = cursor.fetchone()["cnt"]

        # 分页查询
        offset = (page - 1) * size
        params.extend([size, offset])
        cursor = db.execute(
            f"""
            SELECT id, student_id, name, role, created_at
            FROM users {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        rows = cursor.fetchall()
        items = [_row_to_userinfo(row) for row in rows]

    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
    }


@router.put("/students/{student_id}", response_model=UserInfo)
async def update_student(
    student_id: int,
    req: StudentUpdate,
    admin: dict = Depends(require_admin),
):
    """修改学生信息（name 和 password 均为可选）"""
    with get_db_ctx() as db:
        cursor = db.execute(
            "SELECT * FROM users WHERE id = %s AND role = 'student'",
            (student_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="学生不存在",
            )

        updates = []
        params = []
        if req.name is not None:
            updates.append("name = %s")
            params.append(req.name)
        if req.password is not None:
            updates.append("password_hash = %s")
            params.append(_hash_password(req.password))

        if updates:
            params.append(student_id)
            db.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id = %s",
                params,
            )
            db.commit()

        # 查询更新后的用户
        cursor = db.execute("SELECT * FROM users WHERE id = %s", (student_id,))
        return _row_to_userinfo(cursor.fetchone())


@router.delete("/students/{student_id}")
async def delete_student(
    student_id: int,
    admin: dict = Depends(require_admin),
):
    """删除学生（级联删除其对话和消息）"""
    with get_db_ctx() as db:
        cursor = db.execute(
            "SELECT * FROM users WHERE id = %s",
            (student_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="学生不存在",
            )

        if row["role"] == "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="不能删除管理员账号",
            )

        # 级联删除：先删消息，再删对话，最后删用户
        conv_ids_cursor = db.execute(
            "SELECT id FROM conversations WHERE user_id = %s",
            (student_id,),
        )
        conv_ids = [r["id"] for r in conv_ids_cursor.fetchall()]

        if conv_ids:
            placeholders = ",".join(["%s"] * len(conv_ids))
            db.execute(
                f"DELETE FROM messages WHERE conversation_id IN ({placeholders})",
                conv_ids,
            )
            db.execute(
                f"DELETE FROM conversations WHERE id IN ({placeholders})",
                conv_ids,
            )

        db.execute("DELETE FROM users WHERE id = %s", (student_id,))
        db.commit()

    return {"message": "ok"}


# ========== Excel 批量导入 ==========


@router.post("/students/batch")
async def batch_import_students(
    file: UploadFile = File(...),
    admin: dict = Depends(require_admin),
):
    """批量导入学生（Excel 格式：学号 | 姓名 | 密码）"""
    # 检查文件格式
    filename = file.filename or ""
    if not (filename.endswith(".xlsx") or filename.endswith(".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 .xlsx 和 .xls 格式",
        )

    # 读取文件内容
    content = await file.read()
    wb = load_workbook(io.BytesIO(content), read_only=True)
    ws = wb.active

    success = 0
    failed = 0
    errors = []

    with get_db_ctx() as db:
        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            # 跳过空行
            if not row or all(cell is None or str(cell).strip() == "" for cell in row):
                continue

            student_id = str(row[0]).strip() if row[0] else ""
            name = str(row[1]).strip() if row[1] else ""
            password = str(row[2]).strip() if len(row) > 2 and row[2] else ""

            # 校验
            if not student_id:
                failed += 1
                errors.append({"row": row_idx, "student_id": "", "reason": "学号不能为空"})
                continue
            if not name:
                failed += 1
                errors.append({"row": row_idx, "student_id": student_id, "reason": "姓名不能为空"})
                continue
            if not password:
                failed += 1
                errors.append({"row": row_idx, "student_id": student_id, "reason": "密码不能为空"})
                continue

            # 检查学号是否已存在
            cursor = db.execute(
                "SELECT id FROM users WHERE student_id = %s", (student_id,)
            )
            if cursor.fetchone() is not None:
                failed += 1
                errors.append({"row": row_idx, "student_id": student_id, "reason": "学号已存在"})
                continue

            # 创建学生
            try:
                password_hash = _hash_password(password)
                db.execute(
                    """
                    INSERT INTO users (student_id, password_hash, name, role)
                    VALUES (%s, %s, %s, 'student')
                    """,
                    (student_id, password_hash, name),
                )
                success += 1
            except Exception as e:
                failed += 1
                errors.append({"row": row_idx, "student_id": student_id, "reason": str(e)})

        db.commit()

    wb.close()

    return {
        "success": success,
        "failed": failed,
        "errors": errors,
    }


# ========== 统计数据 ==========


@router.get("/stats", response_model=StatsResponse)
async def get_admin_stats(
    admin: dict = Depends(require_admin),
):
    """获取系统统计数据"""
    return get_stats()
