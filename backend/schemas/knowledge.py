"""知识点与复习计划的请求/响应模型。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.course import DATE_PATTERN

ReviewStatus = Literal["pending", "done", "skipped", "overdue"]
KnowledgeStatus = Literal["active", "archived"]


# ---------- 知识点 ----------
class KnowledgePointBase(BaseModel):
    course_id: int
    title: str = Field(min_length=1, max_length=200)
    content_snapshot: str | None = None
    difficulty: int = Field(default=3, ge=1, le=5, description="难度 1-5")
    source_path: str | None = None
    status: KnowledgeStatus = "active"


class KnowledgePointCreate(KnowledgePointBase):
    pass


class KnowledgePointUpdate(BaseModel):
    course_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content_snapshot: str | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    source_path: str | None = None
    status: KnowledgeStatus | None = None


class KnowledgePointRead(KnowledgePointBase):
    id: int
    created_at: str

    model_config = ConfigDict(from_attributes=True)


# ---------- 复习计划 ----------
class ReviewScheduleBase(BaseModel):
    knowledge_point_id: int
    seq: int = Field(ge=1, description="第几次复习（1,2,3...）")
    due_date: str = Field(pattern=DATE_PATTERN, description="计划复习日期 YYYY-MM-DD")
    status: ReviewStatus = "pending"
    completed_at: str | None = None


class ReviewScheduleCreate(ReviewScheduleBase):
    pass


class ReviewScheduleUpdate(BaseModel):
    seq: int | None = Field(default=None, ge=1)
    due_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    status: ReviewStatus | None = None
    completed_at: str | None = None


class ReviewScheduleRead(ReviewScheduleBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
