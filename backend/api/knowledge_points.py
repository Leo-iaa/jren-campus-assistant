"""知识点 CRUD。"""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from backend.api.deps import apply_updates, get_db, get_or_404
from backend.models import Course, KnowledgePoint
from backend.schemas.knowledge import KnowledgePointCreate, KnowledgePointRead, KnowledgePointUpdate

router = APIRouter(prefix="/knowledge-points", tags=["知识点"])


@router.get("", response_model=list[KnowledgePointRead], summary="知识点列表（可按课程过滤）")
def list_knowledge_points(course_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(KnowledgePoint)
    if course_id is not None:
        query = query.filter(KnowledgePoint.course_id == course_id)
    return query.order_by(KnowledgePoint.id).all()


@router.post("", response_model=KnowledgePointRead, status_code=201, summary="创建知识点")
def create_knowledge_point(payload: KnowledgePointCreate, db: Session = Depends(get_db)):
    if db.get(Course, payload.course_id) is None:
        raise HTTPException(status_code=404, detail=f"所属课程不存在（id={payload.course_id}）")
    point = KnowledgePoint(**payload.model_dump())
    db.add(point)
    db.commit()
    db.refresh(point)
    return point


@router.get("/{kp_id}", response_model=KnowledgePointRead, summary="知识点详情")
def get_knowledge_point(kp_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, KnowledgePoint, kp_id)


@router.patch("/{kp_id}", response_model=KnowledgePointRead, summary="更新知识点（部分字段）")
def update_knowledge_point(kp_id: int, payload: KnowledgePointUpdate, db: Session = Depends(get_db)):
    point = get_or_404(db, KnowledgePoint, kp_id)
    data = payload.model_dump(exclude_unset=True)
    if "course_id" in data and data["course_id"] is not None and db.get(Course, data["course_id"]) is None:
        raise HTTPException(status_code=404, detail=f"所属课程不存在（id={data['course_id']}）")
    apply_updates(point, data)
    db.commit()
    db.refresh(point)
    return point


@router.delete("/{kp_id}", status_code=204, summary="删除知识点（级联删除其复习计划）")
def delete_knowledge_point(kp_id: int, db: Session = Depends(get_db)):
    point = get_or_404(db, KnowledgePoint, kp_id)
    db.delete(point)
    db.commit()
    return Response(status_code=204)
