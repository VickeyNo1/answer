from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.auth.router import router as auth_router
from app.chat.router import router as chat_router
from app.knowledge.router import router as knowledge_router
from app.admin.router import router as admin_router
from app.llm.router import router as llm_router
from app.subjects.router import router as subjects_router, admin_router as subjects_admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时建表"""
    init_db()
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
app.include_router(chat_router)
app.include_router(knowledge_router)
app.include_router(admin_router)
app.include_router(llm_router)
app.include_router(subjects_router)
app.include_router(subjects_admin_router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


# 挂载静态文件目录 (uploads)，目录不存在时跳过
import os
if os.path.isdir(settings.UPLOAD_DIR):
    app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")
