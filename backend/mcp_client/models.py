"""MCP 数据接入层的数据结构（纯 dataclass，不依赖 ORM）。

约定与 ``backend/scheduler/interfaces.py`` 一致：接口返回类型为纯数据结构，
落库映射由 ``service.py`` 负责。
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskItem:
    """作业任务（Notion 导入 → tasks 表，source='notion'）。"""

    title: str
    source_ref: str  # Notion 页面 ID（幂等 upsert 依据）
    description: str | None = None
    deadline: str | None = None  # 'YYYY-MM-DD' 或原样文本
    course_name: str | None = None  # 用于按名称关联 courses 表
    status: str = "todo"  # todo / doing / done / cancelled


@dataclass(frozen=True)
class NoteItem:
    """Obsidian 笔记（查询结果；知识点提取归知识提取模块，本层不落库）。"""

    path: str  # vault 内相对路径
    title: str
    excerpt: str = ""  # 搜索命中片段
    content: str | None = None  # 读取全文时填充


@dataclass(frozen=True)
class CourseSessionItem:
    """课程时间块（iCal 解析 → courses + course_sessions）。"""

    course_name: str
    day_of_week: int  # 0=周一
    start_time: str  # 'HH:MM'
    end_time: str
    location: str | None = None
    teacher: str | None = None
    course_code: str | None = None


@dataclass(frozen=True)
class SyncResult:
    """一次数据源同步的汇总结果（供 API 返回）。"""

    source_id: int
    source_type: str
    synced_at: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)
