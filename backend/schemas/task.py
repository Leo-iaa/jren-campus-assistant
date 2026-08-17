"""作业任务与杂事项的请求/响应模型。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.course import DATE_PATTERN

TaskSource = Literal["notion", "manual"]
TaskStatus = Literal["todo", "doing", "done", "cancelled"]
MiscStatus = Literal["todo", "done", "cancelled"]


# ---------- 作业任务 ----------
class TaskBase(BaseModel):
    course_id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    deadline: str | None = Field(default=None, pattern=DATE_PATTERN)
    estimated_minutes: int | None = Field(default=None, ge=1)
    source: TaskSource = "manual"
    source_ref: str | None = None
    status: TaskStatus = "todo"


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    course_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    deadline: str | None = Field(default=None, pattern=DATE_PATTERN)
    estimated_minutes: int | None = Field(default=None, ge=1)
    source: TaskSource | None = None
    source_ref: str | None = None
    status: TaskStatus | None = None


class TaskRead(TaskBase):
    id: int
    created_at: str

    model_config = ConfigDict(from_attributes=True)


# ---------- 杂事项 ----------
class MiscItemBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    duration_minutes: int | None = Field(default=None, ge=1)
    preferred_time: str | None = None
    deadline: str | None = Field(default=None, pattern=DATE_PATTERN)
    status: MiscStatus = "todo"


class MiscItemCreate(MiscItemBase):
    pass


class MiscItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    duration_minutes: int | None = Field(default=None, ge=1)
    preferred_time: str | None = None
    deadline: str | None = Field(default=None, pattern=DATE_PATTERN)
    status: MiscStatus | None = None


class MiscItemRead(MiscItemBase):
    id: int
    created_at: str

    model_config = ConfigDict(from_attributes=True)
