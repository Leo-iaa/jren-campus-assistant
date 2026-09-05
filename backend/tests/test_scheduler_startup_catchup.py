"""启动补偿测试：开机后补齐错过的今日/次日计划缺口（幂等，不重复生成）。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import backend.mcp_server.scheduler_jobs as sj
from backend.models.course import Course, CourseSession
from backend.models.plan import PlanItem, PlanVersion
from backend.mcp_server.service import confirm_plan, generate_plan

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeWriter:
    """替身 writer：不外发请求，返回可控同步结果。"""

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


def _seed_course(db, day: date) -> None:
    """造一门「day 星期几」有课的课程，让计划生成有内容可排。"""
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


def _at(hour: int, minute: int = 0) -> datetime:
    """真实「今天」的指定时刻（保留真实日期，让 service.tomorrow() 与注入时钟一致）。"""
    return datetime.now(_SHANGHAI).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def _patch(db_session, monkeypatch):
    """patch SessionLocal（函数级导入的真源头）与 Notion writer。"""
    monkeypatch.setattr("backend.database.SessionLocal", db_session)
    monkeypatch.setattr(sj, "_build_writer_safe", lambda db: (FakeWriter(), None))


def test_catchup_generates_today_plan_when_empty(db_session, monkeypatch):
    """今天无计划 + 早于 20:00 → 补生成并确认今日计划。"""
    today = date.today()
    with db_session() as db:
        _seed_course(db, today)

    _patch(db_session, monkeypatch)
    sj.run_startup_catchup(now=_at(10, 0))

    with db_session() as db:
        items = db.query(PlanItem).filter(PlanItem.date == today.isoformat()).all()
        assert items, "应补生成今日计划项"
        assert all(i.status == "confirmed" for i in items), "启动补偿应自动确认"
        ver = db.query(PlanVersion).filter(PlanVersion.date == today.isoformat()).first()
        assert ver is not None, "应有版本快照"


def test_catchup_skips_today_when_items_exist(db_session, monkeypatch):
    """今天已有计划项（哪怕只是 draft）→ 不重复生成。"""
    today = date.today()
    with db_session() as db:
        _seed_course(db, today)
        generate_plan(db, today)
        before = (
            db.query(PlanItem).filter(PlanItem.date == today.isoformat()).count()
        )
        assert before > 0

    _patch(db_session, monkeypatch)
    sj.run_startup_catchup(now=_at(10, 0))

    with db_session() as db:
        after = (
            db.query(PlanItem).filter(PlanItem.date == today.isoformat()).count()
        )
        assert after == before, "已有计划项时不应重复生成"


def test_catchup_skips_today_after_cutoff(db_session, monkeypatch):
    """今天无计划但已过 20:00 → 跳过今日补生成（今日仍为空）。"""
    today = date.today()
    with db_session() as db:
        _seed_course(db, today)

    _patch(db_session, monkeypatch)
    sj.run_startup_catchup(now=_at(21, 30))

    with db_session() as db:
        count = (
            db.query(PlanItem).filter(PlanItem.date == today.isoformat()).count()
        )
        assert count == 0, "过了截断时刻不应补生成今日计划"


def test_catchup_runs_tomorrow_job_after_gen_time(db_session, monkeypatch):
    """已过 21:00 + 明天无已确认计划 → 补跑次日生成任务。"""
    tomorrow = date.today() + timedelta(days=1)
    with db_session() as db:
        _seed_course(db, tomorrow)

    _patch(db_session, monkeypatch)
    sj.run_startup_catchup(now=_at(21, 30))

    with db_session() as db:
        items = db.query(PlanItem).filter(PlanItem.date == tomorrow.isoformat()).all()
        assert items, "应补跑次日计划生成"
        assert all(i.status == "confirmed" for i in items)
        ver = db.query(PlanVersion).filter(PlanVersion.date == tomorrow.isoformat()).first()
        assert ver is not None


def test_catchup_skips_tomorrow_when_confirmed(db_session, monkeypatch):
    """明天已有已确认计划 → 不补跑（幂等保护）。"""
    tomorrow = date.today() + timedelta(days=1)
    with db_session() as db:
        _seed_course(db, tomorrow)
        generate_plan(db, tomorrow)
        confirm_plan(db, tomorrow)
        before = (
            db.query(PlanItem).filter(PlanItem.date == tomorrow.isoformat()).count()
        )
        assert before > 0

    _patch(db_session, monkeypatch)
    sj.run_startup_catchup(now=_at(21, 30))

    with db_session() as db:
        after = (
            db.query(PlanItem).filter(PlanItem.date == tomorrow.isoformat()).count()
        )
        assert after == before, "次日计划已确认时不应重复生成"
