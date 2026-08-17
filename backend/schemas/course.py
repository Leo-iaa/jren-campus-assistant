"""课程与课程时间块的请求/响应模型。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 时间与日期格式（数据库存 TEXT，ISO 风格）
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"  # 'HH:MM'
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"  # 'YYYY-MM-DD'

Tier = Literal["S", "A", "B", "C"]


# ---------- 课程 ----------
class CourseBase(BaseModel):
    """课程公共字段（档位 tier 为产品决策字段，默认 A）。"""

    name: str = Field(min_length=1, max_length=100)
    code: str | None = None
    tier: Tier = "A"
    color: str | None = None
    teacher: str | None = None
    notes: str | None = None


class CourseCreate(CourseBase):
    pass


class CourseUpdate(BaseModel):
    """部分更新：所有字段可选，未传字段保持不变。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    code: str | None = None
    tier: Tier | None = None
    color: str | None = None
    teacher: str | None = None
    notes: str | None = None


class CourseRead(CourseBase):
    id: int
    created_at: str

    model_config = ConfigDict(from_attributes=True)


# ---------- 课程时间块 ----------
class CourseSessionBase(BaseModel):
    day_of_week: int = Field(ge=0, le=6, description="0=周一 ... 6=周日")
    start_time: str = Field(pattern=TIME_PATTERN)
    end_time: str = Field(pattern=TIME_PATTERN)
    location: str | None = None
    release_slot: int = Field(default=0, ge=0, le=1, description="B/C 档：该时段是否释放（0/1）")


class CourseSessionCreate(CourseSessionBase):
    pass


class CourseSessionUpdate(BaseModel):
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    start_time: str | None = Field(default=None, pattern=TIME_PATTERN)
    end_time: str | None = Field(default=None, pattern=TIME_PATTERN)
    location: str | None = None
    release_slot: int | None = Field(default=None, ge=0, le=1)


class CourseSessionRead(CourseSessionBase):
    id: int
    course_id: int

    model_config = ConfigDict(from_attributes=True)
