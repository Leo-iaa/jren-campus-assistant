"""兜底定时任务测试：21:00 生成后应自动确认并写 Notion（#72）。"""
from __future__ import annotations

from datetime import date, timedelta

import backend.mcp_server.scheduler_jobs as sj
from backend.models.course import Course, CourseSession
from backend.models.plan import PlanItem, PlanVersion


def _seed_course(db, day: date) -> None:
    """造一门「明天星期几」有课的课程，让任务体有内容可排。"""
    course = Course(name="测试课程", tier="A")
    db.add(course)
    db.flush()
    db.add(
        CourseSession(
            course_id=course.id,
            day_of_week=day.weekday(),
            start_time="08:00",
            end_time="09:40",
            location="教室",
            release_slot=0,
        )
    )
    db.commit()


class FakeWriter:
    """替身 writer：不外发请求，返回可控同步结果。

    confirm_plan 调用的是 ``sync_plan_to_calendar(db, plan_date)``。
    """

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple] = []

    def sync_plan_to_calendar(self, db, plan_date):
        if self.fail:
            raise RuntimeError("notion down")
        items = [
            i
            for i in db.query(PlanItem).filter(PlanItem.date == plan_date.isoformat())
            if i.status == "confirmed"
        ]
        self.calls.append((len(items), plan_date))
        return {"created": len(items), "updated": 0, "unchanged": 0}

    def close(self):
        pass


def test_job_auto_confirms_and_reports_notion_sync(db_session, monkeypatch):
    """任务执行后：计划项 confirmed + 版本快照 + Notion write_day 被调用。"""
    tomorrow = date.today() + timedelta(days=1)
    with db_session() as db:
        _seed_course(db, tomorrow)

    writer = FakeWriter()
    monkeypatch.setattr(sj, "_build_writer_safe", lambda db: (writer, None))
    # 任务体是函数级 `from backend.database import SessionLocal`，须 patch 真源头
    monkeypatch.setattr("backend.database.SessionLocal", db_session)

    sj.generate_tomorrow_plan_job()

    with db_session() as db:
        items = db.query(PlanItem).filter(PlanItem.date == tomorrow.isoformat()).all()
        assert items, "任务应生成次日计划项"
        assert all(i.status == "confirmed" for i in items), "兜底任务应自动确认（auto_confirm）"
        ver = db.query(PlanVersion).filter(PlanVersion.date == tomorrow.isoformat()).first()
        assert ver is not None, "应有版本快照"
    assert writer.calls, "确认时应调用 Notion write_day"


def test_job_survives_notion_error(db_session, monkeypatch):
    """Notion 挂了不应让任务崩溃：本地确认照常完成。"""
    tomorrow = date.today() + timedelta(days=1)
    with db_session() as db:
        _seed_course(db, tomorrow)

    writer = FakeWriter(fail=True)
    monkeypatch.setattr(sj, "_build_writer_safe", lambda db: (writer, "notion down"))
    monkeypatch.setattr("backend.database.SessionLocal", db_session)

    # 不应抛异常
    sj.generate_tomorrow_plan_job()

    with db_session() as db:
        items = db.query(PlanItem).filter(PlanItem.date == tomorrow.isoformat()).all()
        assert items, "本地计划项仍应生成并确认"
        assert all(i.status == "confirmed" for i in items)
        # 版本快照仍应写入（confirm 不因日历失败回滚）
        ver = db.query(PlanVersion).filter(PlanVersion.date == tomorrow.isoformat()).first()
        assert ver is not None


def test_job_survives_writer_build_failure(db_session, monkeypatch):
    """writer 构造失败（未绑定 Notion）也不崩溃：确认照常，sync 记录 error。"""
    tomorrow = date.today() + timedelta(days=1)
    with db_session() as db:
        _seed_course(db, tomorrow)

    monkeypatch.setattr(sj, "_build_writer_safe", lambda db: (None, "notion 未绑定"))
    monkeypatch.setattr("backend.database.SessionLocal", db_session)

    sj.generate_tomorrow_plan_job()

    with db_session() as db:
        items = db.query(PlanItem).filter(PlanItem.date == tomorrow.isoformat()).all()
        assert items and all(i.status == "confirmed" for i in items)