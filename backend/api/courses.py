"""课程 CRUD（含 tier 档位过滤）。"""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from backend.api.deps import apply_updates, get_db, get_or_404
from backend.models import Course
from backend.schemas.course import CourseCreate, CourseRead, CourseUpdate, Tier

router = APIRouter(prefix="/courses", tags=["课程"])


@router.get("", response_model=list[CourseRead], summary="课程列表（可按档位过滤）")
def list_courses(tier: Tier | None = None, db: Session = Depends(get_db)):
    query = db.query(Course)
    if tier is not None:
        query = query.filter(Course.tier == tier)
    return query.order_by(Course.id).all()


@router.post("", response_model=CourseRead, status_code=201, summary="创建课程")
def create_course(payload: CourseCreate, db: Session = Depends(get_db)):
    course = Course(**payload.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.get("/{course_id}", response_model=CourseRead, summary="课程详情")
def get_course(course_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Course, course_id)


@router.patch("/{course_id}", response_model=CourseRead, summary="更新课程（部分字段）")
def update_course(course_id: int, payload: CourseUpdate, db: Session = Depends(get_db)):
    course = get_or_404(db, Course, course_id)
    apply_updates(course, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(course)
    return course


@router.delete("/{course_id}", status_code=204, summary="删除课程（级联删除时间块/知识点/复习计划）")
def delete_course(course_id: int, db: Session = Depends(get_db)):
    course = get_or_404(db, Course, course_id)
    db.delete(course)
    db.commit()
    return Response(status_code=204)
