from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import settings_store
from app.config import get_settings
from app.database import init_db, get_db_ctx
from app.auth.router import router as auth_router, me_router
from app.chat.router import router as chat_router
from app.chat import concurrency
from app.admin.router import router as admin_router
from app.llm.router import router as llm_router
from app.kb import client as kb_client
from app.kb.subjects import router as subjects_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时建表、加载全局设置缓存、初始化并发闸门"""
    init_db()
    settings_store.load_settings()
    concurrency.init(settings_store.get_int("chat_concurrency"))
    yield


app = FastAPI(
    title="会计答疑智能体",
    description="面向会计专业学生的 AI 智能答疑系统",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 中间件
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(me_router)
app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(llm_router)
app.include_router(subjects_router)


@app.get("/api/health")
def health_check():
    """健康检查（无需认证）：任一依赖 fail 时 status=degraded，HTTP 仍 200"""
    mysql_ok = True
    try:
        with get_db_ctx() as db:
            db.execute("SELECT 1")
    except Exception:
        mysql_ok = False

    kb_ok = kb_client.probe()

    return {
        "status": "ok" if (mysql_ok and kb_ok) else "degraded",
        "mysql": "ok" if mysql_ok else "fail",
        "kb": "ok" if kb_ok else "fail",
    }
