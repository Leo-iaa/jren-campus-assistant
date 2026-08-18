"""课程时间块 CRUD（嵌套在课程下创建/列表，扁平化单条操作）。"""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from backend.api.deps import apply_updates, get_db, get_or_404
from backend.models import Course, CourseSession
from backend.schemas.course import CourseSessionCreate, CourseSessionRead, CourseSessionUpdate

router = APIRouter(tags=["课程时间块"])


@router.get("/courses/{course_id}/sessions", response_model=list[CourseSessionRead], summary="某课程的时间块列表")
def list_sessions(course_id: int, db: Session = Depends(get_db)):
    get_or_404(db, Course, course_id)
    return (
        db.query(CourseSession)
        .filter(CourseSession.course_id == course_id)
        .order_by(CourseSession.day_of_week, CourseSession.start_time)
        .all()
    )


@router.post("/courses/{course_id}/sessions", response_model=CourseSessionRead, status_code=201, summary="为课程添加时间块")
def create_session(course_id: int, payload: CourseSessionCreate, db: Session = Depends(get_db)):
    get_or_404(db, Course, course_id)
    session = CourseSession(course_id=course_id, **payload.model_dump())
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/course-sessions/{session_id}", response_model=CourseSessionRead, summary="时间块详情")
def get_session(session_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, CourseSession, session_id)


@router.patch("/course-sessions/{session_id}", response_model=CourseSessionRead, summary="更新时间块（部分字段）")
def update_session(session_id: int, payload: CourseSessionUpdate, db: Session = Depends(get_db)):
    session = get_or_404(db, CourseSession, session_id)
    apply_updates(session, payload.model_dump(exclude_unset=True))
    # PATCH 可能只传一端，schema 无法跨字段校验已有值 → 在此对合并后时间做校验
    if session.end_time <= session.start_time:
        db.rollback()
        raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")
    db.commit()
    db.refresh(session)
    return session


@router.delete("/course-sessions/{session_id}", status_code=204, summary="删除时间块")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    session = get_or_404(db, CourseSession, session_id)
    db.delete(session)
    db.commit()
    return Response(status_code=204)
