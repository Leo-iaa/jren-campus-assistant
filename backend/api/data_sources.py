"""数据源绑定 CRUD。"""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from backend.api.deps import apply_updates, get_db, get_or_404
from backend.models import DataSource
from backend.schemas.datasource import (
    DataSourceCreate,
    DataSourceRead,
    DataSourceType,
    DataSourceUpdate,
)

router = APIRouter(prefix="/data-sources", tags=["数据源"])


@router.get("", response_model=list[DataSourceRead], summary="数据源列表（可按类型过滤）")
def list_data_sources(
    source_type: DataSourceType | None = None, db: Session = Depends(get_db)
):
    query = db.query(DataSource)
    if source_type is not None:
        query = query.filter(DataSource.source_type == source_type)
    return query.order_by(DataSource.id).all()


@router.post("", response_model=DataSourceRead, status_code=201, summary="绑定数据源")
def create_data_source(payload: DataSourceCreate, db: Session = Depends(get_db)):
    source = DataSource(**payload.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("/{source_id}", response_model=DataSourceRead, summary="数据源详情")
def get_data_source(source_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, DataSource, source_id)


@router.patch("/{source_id}", response_model=DataSourceRead, summary="更新数据源（部分字段）")
def update_data_source(
    source_id: int, payload: DataSourceUpdate, db: Session = Depends(get_db)
):
    source = get_or_404(db, DataSource, source_id)
    apply_updates(source, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(source)
    return source


@router.delete("/{source_id}", status_code=204, summary="解绑数据源")
def delete_data_source(source_id: int, db: Session = Depends(get_db)):
    source = get_or_404(db, DataSource, source_id)
    db.delete(source)
    db.commit()
    return Response(status_code=204)
