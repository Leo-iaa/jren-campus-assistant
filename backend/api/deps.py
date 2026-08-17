"""API 公共依赖：数据库会话与通用查询辅助。"""
from collections.abc import Generator

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：为每个请求提供独立数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_or_404(db: Session, model: type, obj_id: int):
    """按主键查询，不存在则抛 404（中文错误信息）。"""
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} 不存在（id={obj_id}）")
    return obj


def apply_updates(obj, payload: dict) -> None:
    """把 PATCH 请求中显式提供的字段写入 ORM 对象（未传字段保持不变）。"""
    for key, value in payload.items():
        setattr(obj, key, value)


DbSession = Depends(get_db)
