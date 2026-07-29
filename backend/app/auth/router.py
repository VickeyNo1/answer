import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from app.database import get_db
from app.models import LoginRequest, PasswordUpdate, TokenResponse, UserInfo
from app.auth.jwt_handler import create_access_token
from app.auth.deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["认证"])

# /api/me/* 子路由（前缀与 /api/auth 不同，单独注册，见 app/main.py）
me_router = APIRouter(prefix="/api/me", tags=["认证"])


def _hash_password(password: str) -> str:
    """bcrypt 加密密码"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db=Depends(get_db)):
    """用户登录"""
    cursor = db.execute(
        "SELECT * FROM users WHERE student_id = %s", (req.student_id,)
    )
    user = cursor.fetchone()

    if user is None or not _verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="学号或密码错误",
        )

    token = create_access_token(user_id=user["id"], role=user["role"])
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        role=user["role"],
    )


@router.get("/me", response_model=UserInfo)
async def get_me(current_user: dict = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserInfo(
        id=current_user["id"],
        student_id=current_user["student_id"],
        name=current_user["name"],
        role=current_user["role"],
        created_at=str(current_user["created_at"]),
    )


@me_router.put("/password")
async def change_password(
    req: PasswordUpdate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """学生自助修改密码（旧密码校验失败/新密码过短 → 400）"""
    if not _verify_password(req.old_password, current_user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码错误",
        )
    if len(req.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码长度不能少于 6 位",
        )

    db.execute(
        "UPDATE users SET password_hash = %s WHERE id = %s",
        (_hash_password(req.new_password), current_user["id"]),
    )
    db.commit()
    return {"message": "ok"}
