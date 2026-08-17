"""杂事项 CRUD。"""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from backend.api.deps import apply_updates, get_db, get_or_404
from backend.models import MiscItem
from backend.schemas.task import MiscItemCreate, MiscItemRead, MiscItemUpdate, MiscStatus

router = APIRouter(prefix="/misc-items", tags=["杂事项"])


@router.get("", response_model=list[MiscItemRead], summary="杂事项列表（可按状态过滤）")
def list_misc_items(status: MiscStatus | None = None, db: Session = Depends(get_db)):
    query = db.query(MiscItem)
    if status is not None:
        query = query.filter(MiscItem.status == status)
    return query.order_by(MiscItem.id).all()


@router.post("", response_model=MiscItemRead, status_code=201, summary="创建杂事项")
def create_misc_item(payload: MiscItemCreate, db: Session = Depends(get_db)):
    item = MiscItem(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/{item_id}", response_model=MiscItemRead, summary="杂事项详情")
def get_misc_item(item_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, MiscItem, item_id)


@router.patch("/{item_id}", response_model=MiscItemRead, summary="更新杂事项（部分字段）")
def update_misc_item(item_id: int, payload: MiscItemUpdate, db: Session = Depends(get_db)):
    item = get_or_404(db, MiscItem, item_id)
    apply_updates(item, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=204, summary="删除杂事项")
def delete_misc_item(item_id: int, db: Session = Depends(get_db)):
    item = get_or_404(db, MiscItem, item_id)
    db.delete(item)
    db.commit()
    return Response(status_code=204)
