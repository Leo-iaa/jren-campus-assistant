"""复习计划 CRUD（按知识点过滤 / 状态过滤）。"""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from backend.api.deps import apply_updates, get_db, get_or_404
from backend.models import KnowledgePoint, ReviewSchedule
from backend.schemas.knowledge import (
    ReviewScheduleCreate,
    ReviewScheduleRead,
    ReviewScheduleUpdate,
    ReviewStatus,
)

router = APIRouter(prefix="/review-schedules", tags=["复习计划"])


@router.get("", response_model=list[ReviewScheduleRead], summary="复习计划列表（可按知识点/状态过滤）")
def list_review_schedules(
    knowledge_point_id: int | None = None,
    status: ReviewStatus | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(ReviewSchedule)
    if knowledge_point_id is not None:
        query = query.filter(ReviewSchedule.knowledge_point_id == knowledge_point_id)
    if status is not None:
        query = query.filter(ReviewSchedule.status == status)
    return query.order_by(ReviewSchedule.id).all()


@router.post("", response_model=ReviewScheduleRead, status_code=201, summary="创建复习计划")
def create_review_schedule(payload: ReviewScheduleCreate, db: Session = Depends(get_db)):
    if db.get(KnowledgePoint, payload.knowledge_point_id) is None:
        raise HTTPException(
            status_code=404, detail=f"所属知识点不存在（id={payload.knowledge_point_id}）"
        )
    schedule = ReviewSchedule(**payload.model_dump())
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.get("/{schedule_id}", response_model=ReviewScheduleRead, summary="复习计划详情")
def get_review_schedule(schedule_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, ReviewSchedule, schedule_id)


@router.patch("/{schedule_id}", response_model=ReviewScheduleRead, summary="更新复习计划（部分字段）")
def update_review_schedule(
    schedule_id: int, payload: ReviewScheduleUpdate, db: Session = Depends(get_db)
):
    schedule = get_or_404(db, ReviewSchedule, schedule_id)
    apply_updates(schedule, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(schedule)
    return schedule


@router.delete("/{schedule_id}", status_code=204, summary="删除复习计划")
def delete_review_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = get_or_404(db, ReviewSchedule, schedule_id)
    db.delete(schedule)
    db.commit()
    return Response(status_code=204)
