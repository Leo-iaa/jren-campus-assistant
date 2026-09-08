"""update_task MCP 工具测试（#83：报错口误改时长/改期）。"""
from __future__ import annotations

import pytest

from backend.models import Task
from backend.mcp_server import service as svc


@pytest.fixture()
def task(db_session):
    with db_session() as db:
        t = Task(
            title="打印简历初稿",
            task_type="其他",
            deadline="2026-09-22",
            estimated_minutes=90,
            source="manual",
            status="todo",
        )
        db.add(t)
        db.commit()
        return t.id


class FakeWriter:
    """替身 writer：记录调用，不外发。"""

    def __init__(self):
        self.updates: list[tuple] = []
        self.statuses: list[tuple] = []

    def update_task(self, page_id, payload):
        self.updates.append((page_id, payload))
        return {"updated": True, "missing_props": []}

    def set_status(self, page_id, done):
        self.statuses.append((page_id, done))
        return {"updated": True, "missing_props": []}


def test_update_estimated_minutes(db_session, task):
    writer = FakeWriter()
    with db_session() as db:
        t = db.get(Task, task)
        t.source_ref = "page-123"
        db.commit()

    result = svc.update_task(
        db_session(), task_id=task, estimated_minutes=60, task_writer=writer
    )
    assert result.task["estimated_minutes"] == 60
    assert "60 分钟" in result.plan_message
    assert result.notion_sync is not None


def test_update_due_date_and_type(db_session, task):
    with db_session() as db:
        t = db.get(Task, task)
        t.source_ref = "page-123"
        db.commit()
    writer = FakeWriter()

    result = svc.update_task(
        db_session(),
        task_id=task,
        due_date="2026-09-20",
        task_type="作业",
        task_writer=writer,
    )
    assert result.task["deadline"] == "2026-09-20"
    assert result.task["task_type"] == "作业"
    assert writer.updates and writer.updates[0][0] == "page-123"
    assert writer.updates[0][1]["deadline"] == "2026-09-20"
    assert "Notion 任务库已同步" in result.plan_message


def test_update_status_done(db_session, task):
    with db_session() as db:
        t = db.get(Task, task)
        t.source_ref = "page-123"
        db.commit()
    writer = FakeWriter()

    result = svc.update_task(
        db_session(), task_id=task, status="done", task_writer=writer
    )
    assert result.task["status"] == "done"
    assert writer.statuses and writer.statuses[0][1] is True


def test_update_partial_keeps_other_fields(db_session, task):
    result = svc.update_task(db_session(), task_id=task, estimated_minutes=45)
    assert result.task["estimated_minutes"] == 45
    assert result.task["deadline"] == "2026-09-22"  # 未传字段不变
    assert result.task["title"] == "打印简历初稿"


def test_update_nonexistent_task(db_session):
    with pytest.raises(ValueError, match="任务不存在"):
        svc.update_task(db_session(), task_id=99999, estimated_minutes=30)


def test_update_invalid_fields(db_session, task):
    with pytest.raises(ValueError, match="未知任务类型"):
        svc.update_task(db_session(), task_id=task, task_type="摸鱼")
    with pytest.raises(ValueError, match="未知任务状态"):
        svc.update_task(db_session(), task_id=task, status="睡觉")
    with pytest.raises(ValueError, match="预估时长"):
        svc.update_task(db_session(), task_id=task, estimated_minutes=0)
