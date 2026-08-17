"""健康检查接口。"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.config import settings

router = APIRouter(tags=["系统"])


@router.get("/health", summary="健康检查（含数据库探活）")
def health_check(db: Session = Depends(get_db)) -> dict:
    """服务存活探针：执行 SELECT 1 验证数据库连接可用。"""
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "database": "connected",
    }
