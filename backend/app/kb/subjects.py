"""科目注册表与科目列表接口（契约见 doc/知识库科目枚举约定.md）

枚举字典由知识库侧定义与维护，后端不得自造枚举值。
当前 /kb/subjects 发现接口未上线，先硬编码注册表；上线后改为动态获取。
"""
from fastapi import APIRouter, Depends

from app.auth.deps import get_current_user
from app.models import SubjectItem

# 科目注册表（与 doc/知识库科目枚举约定.md §1 保持一致；只增不改）
SUBJECT_REGISTRY = [
    {"subject": "cpa_acc", "name": "CPA 会计", "status": "online"},
    {"subject": "cpa_audit", "name": "CPA 审计", "status": "offline"},
    {"subject": "zj_acc", "name": "中级财务会计", "status": "offline"},
    {"subject": "gj_acc", "name": "高级财务会计", "status": "offline"},
]

DEFAULT_SUBJECT = "cpa_acc"

router = APIRouter(prefix="/api/subjects", tags=["科目"])


def is_valid_subject(subject: str) -> bool:
    """校验 subject 是否在注册表中"""
    return any(s["subject"] == subject for s in SUBJECT_REGISTRY)


def online_subjects() -> list[dict]:
    """获取已上线的科目（筛选框只渲染 online 项）"""
    return [s for s in SUBJECT_REGISTRY if s["status"] == "online"]


@router.get("", response_model=list[SubjectItem])
async def list_subjects(current_user: dict = Depends(get_current_user)):
    """获取可选科目列表（全员可见，仅返回已上线科目）"""
    return online_subjects()
