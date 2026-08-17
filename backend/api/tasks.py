"""作业任务 CRUD。"""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from backend.api.deps import apply_updates, get_db, get_or_404
from backend.models import Course, Task
from backend.schemas.task import TaskCreate, TaskRead, TaskStatus, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["作业任务"])


@router.get("", response_model=list[TaskRead], summary="任务列表（可按课程/状态过滤）")
def list_tasks(
    course_id: int | None = None,
    status: TaskStatus | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Task)
    if course_id is not None:
        query = query.filter(Task.course_id == course_id)
    if status is not None:
        query = query.filter(Task.status == status)
    return query.order_by(Task.id).all()


@router.post("", response_model=TaskRead, status_code=201, summary="创建任务（course_id 可选）")
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    if payload.course_id is not None and db.get(Course, payload.course_id) is None:
        raise HTTPException(status_code=404, detail=f"所属课程不存在（id={payload.course_id}）")
    task = Task(**payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskRead, summary="任务详情")
def get_task(task_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Task, task_id)


@router.patch("/{task_id}", response_model=TaskRead, summary="更新任务（部分字段）")
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)):
    task = get_or_404(db, Task, task_id)
    data = payload.model_dump(exclude_unset=True)
    if "course_id" in data and data["course_id"] is not None and db.get(Course, data["course_id"]) is None:
        raise HTTPException(status_code=404, detail=f"所属课程不存在（id={data['course_id']}）")
    apply_updates(task, data)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=204, summary="删除任务")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = get_or_404(db, Task, task_id)
    db.delete(task)
    db.commit()
    return Response(status_code=204)
