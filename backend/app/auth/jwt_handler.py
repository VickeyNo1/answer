from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from app.config import get_settings


def create_access_token(user_id: int, role: str) -> str:
    """生成 JWT Token，24 小时过期"""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_access_token(token: str) -> dict | None:
    """验证 JWT Token，返回 payload；失败返回 None"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None
