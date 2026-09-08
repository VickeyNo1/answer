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
    """删除模型配置（当前使用的模型不可删，须先切换）

    activate_model 会先把全表 is_active 清零，删掉激活模型后系统就没有任何激活模型，
    get_active_model() 会静默回退 .env 的 CHAT_MODEL；那个名字若不在 model_configs 里，
    compute_cost 单价回退 0.0，此后所有用量的 cost 恒为 0 且不报任何错。
    """
    existing = store.get_model(model_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="模型不存在",
        )
    if existing["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="不能删除当前使用的模型，请先切换到其他模型",
        )
    store.delete_model(model_id)
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
