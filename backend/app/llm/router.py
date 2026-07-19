"""大模型管理路由：模型配置 CRUD + 切换 + 用量费用统计（仅管理员）"""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.deps import require_admin
from app.models import (
    ModelConfigOut,
    ModelConfigCreate,
    ModelConfigUpdate,
    UsageStatsOut,
)
from app.llm import store

router = APIRouter(prefix="/api/admin/models", tags=["大模型管理"])


@router.get("", response_model=list[ModelConfigOut])
async def list_models(admin: dict = Depends(require_admin)):
    """获取所有模型配置"""
    return store.list_models()


@router.get("/usage", response_model=UsageStatsOut)
async def usage_stats(
    days: int = Query(7, ge=1, le=90),
    admin: dict = Depends(require_admin),
):
    """用量与费用统计"""
    return store.get_usage_stats(days)


@router.post("", response_model=ModelConfigOut, status_code=status.HTTP_201_CREATED)
async def create_model(req: ModelConfigCreate, admin: dict = Depends(require_admin)):
    """新增模型配置"""
    if store.get_model_by_name(req.model_name) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"模型 {req.model_name} 已存在",
        )
    return store.create_model(
        req.provider, req.model_name, req.display_name,
        req.price_in, req.price_out, req.enabled,
    )


@router.put("/{model_id}", response_model=ModelConfigOut)
async def update_model(
    model_id: int,
    req: ModelConfigUpdate,
    admin: dict = Depends(require_admin),
):
    """修改模型配置（单价/名称/启用等）"""
    result = store.update_model(model_id, req.model_dump())
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="模型不存在",
        )
    return result


@router.delete("/{model_id}")
async def delete_model(model_id: int, admin: dict = Depends(require_admin)):
    """删除模型配置"""
    if not store.delete_model(model_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="模型不存在",
        )
    return {"message": "ok"}


@router.post("/{model_id}/activate", response_model=ModelConfigOut)
async def activate_model(model_id: int, admin: dict = Depends(require_admin)):
    """设为当前使用的模型"""
    result = store.activate_model(model_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="模型不存在",
        )
    return result
