"""查询：课程 / 任务 / 复习计划列表。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.models import Course, KnowledgePoint, ReviewSchedule, Task
from backend.mcp_server._common import parse_date
from backend.mcp_server.task_intake import task_to_dict


def list_courses(db: Session) -> list[dict]:
    """课程列表（含档位）。"""
    rows = db.query(Course).order_by(Course.id).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "code": c.code,
            "tier": c.tier,
            "color": c.color,
            "teacher": c.teacher,
            "notes": c.notes,
        }
        for c in rows
    ]


def list_tasks(db: Session, status: str | None = None) -> list[dict]:
    """任务列表（可按状态过滤：todo/doing/done/cancelled）。"""
    query = db.query(Task)
    if status:
        if status not in ("todo", "doing", "done", "cancelled"):
            raise ValueError(f"未知任务状态: {status!r}（应为 todo/doing/done/cancelled）")
        query = query.filter(Task.status == status)
    rows = query.order_by(Task.id).all()
    return [task_to_dict(t) for t in rows]


def list_reviews(db: Session, due_date: str | None = None) -> list[dict]:
    """复习计划列表（可按到期日过滤，'YYYY-MM-DD'）。"""
    query = db.query(ReviewSchedule)
    if due_date:
        parse_date(due_date)  # 校验格式
        query = query.filter(ReviewSchedule.due_date == due_date)
    rows = query.order_by(ReviewSchedule.due_date, ReviewSchedule.id).all()
    result: list[dict] = []
    for rs in rows:
        kp = db.get(KnowledgePoint, rs.knowledge_point_id)
        course = db.get(Course, kp.course_id) if kp else None
        result.append(
            {
                "id": rs.id,
                "seq": rs.seq,
                "due_date": rs.due_date,
                "status": rs.status,
                "knowledge_point_id": rs.knowledge_point_id,
                "knowledge_point": kp.title if kp else None,
                "difficulty": kp.difficulty if kp else None,
                "course_id": course.id if course else None,
                "course_name": course.name if course else None,
                "completed_at": rs.completed_at,
            }
        )
    return result
