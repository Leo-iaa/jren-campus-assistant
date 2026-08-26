"""MCP Server 暴露层 · 计划编排服务测试（backend/mcp_server/service.py）。

使用 conftest 的临时 SQLite 数据库夹具，不依赖任何外部服务。
"""
from datetime import date, timedelta

import pytest

from backend.models import (
    CalibrationStat,
    Course,
    CourseSession,
    KnowledgePoint,
    MiscItem,
    PlanItem,
    PlanVersion,
    ReviewSchedule,
    Task,
)
from backend.mcp_server.notion_calendar import CalendarSyncResult
from backend.mcp_server.service import (
    add_task,
    adjust_plan_item,
    confirm_plan,
    generate_plan,
    list_courses,
    list_reviews,
    list_tasks,
    mark_done,
    preview_plan_text,
    time_bucket_for,
)

# 2026-08-19 为周三（weekday()=2），课程时间块按此对齐
PLAN_DATE = date(2026, 8, 19)


class FakeCalendarWriter:
    """记录调用的假日历写入器（confirm_plan 的 notion_sync 注入点）。"""

    def __init__(self) -> None:
        self.calls: list[date] = []

    def sync_plan_to_calendar(self, db, plan_date: date) -> CalendarSyncResult:
        self.calls.append(plan_date)
        return CalendarSyncResult(created=1, updated=0, unchanged=0)


def seed_basic(db, plan_date: date = PLAN_DATE) -> None:
    """标准测试数据：2 门课（S 档硬块 + B 档释放块）+ 任务 + 复习 + 杂项。"""
    course = Course(name="高等数学", tier="S")
    db.add(course)
    db.flush()
    db.add(
        CourseSession(
            course_id=course.id,
            day_of_week=plan_date.weekday(),
            start_time="08:00",
            end_time="09:40",
            location="教西A1-101",
            release_slot=0,
        )
    )
    course_b = Course(name="大学英语", tier="B")
    db.add(course_b)
    db.flush()
    db.add(
        CourseSession(
            course_id=course_b.id,
            day_of_week=plan_date.weekday(),
            start_time="14:00",
            end_time="15:40",
            release_slot=1,
        )
    )
    db.add(Task(title="高数作业", course_id=course.id, estimated_minutes=60, status="todo"))
    kp = KnowledgePoint(course_id=course.id, title="泰勒展开", difficulty=3)
    db.add(kp)
    db.flush()
    db.add(
        ReviewSchedule(
            knowledge_point_id=kp.id, seq=1, due_date=plan_date.isoformat(), status="pending"
        )
    )
    db.add(MiscItem(title="取快递", duration_minutes=30, status="todo"))
    db.commit()


def plan_items(db, plan_date: date = PLAN_DATE) -> list[PlanItem]:
    return (
        db.query(PlanItem)
        .filter(PlanItem.date == plan_date.isoformat())
        .order_by(PlanItem.start_time, PlanItem.id)
        .all()
    )


# ---------- 生成 ----------


def test_generate_plan_basic(db_session):
    with db_session() as db:
        seed_basic(db)
        result = generate_plan(db, PLAN_DATE)

        assert result.placed_count == 5  # 2 课程 + 任务 + 复习 + 杂项
        assert result.dropped == []
        assert result.skipped == []

        items = plan_items(db)
        assert len(items) == 5
        assert all(item.status == "draft" for item in items)
        types = sorted(item.item_type for item in items)
        assert types == ["course", "course", "misc", "review", "task"]
        # 课程块保持原时间；B 档释放块也出现在计划中
        starts = {item.start_time for item in items if item.item_type == "course"}
        assert starts == {"08:00", "14:00"}


def test_generate_plan_skips_when_day_confirmed(db_session):
    """已确认的计划不自动重排：明确提示，不产生重复/覆盖。"""
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        confirm_plan(db, PLAN_DATE, calendar_writer=None)

        # 再次生成：直接返回「已确认不重排」
        result = generate_plan(db, PLAN_DATE)
        assert result.placed_count == 0
        assert any("已确认" in s for s in result.skipped)
        items = plan_items(db)
        assert len(items) == 5
        assert all(item.status == "confirmed" for item in items)

        # 新增任务后仍不重排（改动请走 adjust_plan_item）
        db.add(Task(title="线代作业", course_id=None, estimated_minutes=45, status="todo"))
        db.commit()
        result = generate_plan(db, PLAN_DATE)
        assert result.placed_count == 0
        assert not any(i.title == "线代作业" for i in plan_items(db))


def test_generate_plan_skips_collision_with_done_item(db_session):
    with db_session() as db:
        seed_basic(db)
        # 手工放一个已完成项占住 09:40（复习点会被规划器排到的位置）
        db.add(
            PlanItem(
                date=PLAN_DATE.isoformat(),
                start_time="09:40",
                end_time="10:40",
                item_type="task",
                ref_id=None,
                title="手改任务",
                status="done",
            )
        )
        db.commit()

        result = generate_plan(db, PLAN_DATE)
        # 与 09:40 冲突的复习点被跳过并报告，其余正常放置
        assert any("复习" in s and "冲突" in s for s in result.skipped)
        assert result.placed_count == 4
        assert all(
            i.start_time != "09:40" for i in plan_items(db) if i.status == "draft"
        )


def test_generate_plan_skips_misc_without_duration(db_session):
    with db_session() as db:
        seed_basic(db)
        db.add(MiscItem(title="没写时长的事", duration_minutes=None, status="todo"))
        db.commit()
        result = generate_plan(db, PLAN_DATE)
        assert any("没写时长的事" in s for s in result.skipped)
        assert result.placed_count == 5


def test_generate_plan_replaces_draft_with_same_start_time(db_session):
    """重排时新草案与旧 draft 同 start_time 不撞 UNIQUE（删除先落地再插入）。"""
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        # 任务时长改为 120 分钟 → 位置变化，但仍可能与旧草案某 start 相同
        task = db.query(Task).filter(Task.title == "高数作业").first()
        task.estimated_minutes = 120
        db.commit()

        result = generate_plan(db, PLAN_DATE)
        assert result.placed_count == 5  # 课程 2 + 任务 + 复习 + 杂项，全部重新放好
        assert result.skipped == []
        items = plan_items(db, PLAN_DATE)
        starts = [i.start_time for i in items]
        assert len(starts) == len(set(starts))  # 无重复 start_time


def test_generate_plan_ignores_overdue_tasks(db_session):
    with db_session() as db:
        seed_basic(db)
        db.add(
            Task(title="早该交的作业", estimated_minutes=30, status="todo", deadline="2026-08-10")
        )
        db.commit()
        result = generate_plan(db, PLAN_DATE)
        assert result.placed_count == 5
        assert not any(i.title == "早该交的作业" for i in plan_items(db))


# ---------- 预览 ----------


def test_preview_plan_text(db_session):
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        text = preview_plan_text(db, PLAN_DATE)

        assert "2026-08-19" in text and "周三" in text
        assert "⏳ 待确认" in text
        assert "📚 课程（2）" in text
        assert "高等数学" in text and "教西A1-101" in text  # 教室从 session 冗余展示
        assert "高数作业" in text
        assert "泰勒展开" in text
        assert "取快递" in text


def test_preview_plan_text_empty(db_session):
    with db_session() as db:
        text = preview_plan_text(db, PLAN_DATE)
        assert "今天还没有安排" in text


def test_preview_plan_text_notion_fallback(db_session, monkeypatch):
    """本地无计划时回退读 Notion 日历事件（AI 回答与用户日历一致）。"""

    class FakeWriter:
        def list_events_on(self, iso: str) -> list[dict]:
            assert iso == PLAN_DATE.isoformat()
            return [
                {"start": f"{iso}T08:00:00+08:00", "end": "", "title": "高等数学", "type": "course"},
                {"start": f"{iso}T14:00:00+08:00", "end": "", "title": "高数作业", "type": "task"},
            ]

    import backend.mcp_server.notion_calendar as nc

    monkeypatch.setattr(nc, "build_writer", lambda db: FakeWriter())
    with db_session() as db:
        text = preview_plan_text(db, PLAN_DATE)
    assert "Notion 日历中的安排" in text
    assert "08:00" in text and "高等数学" in text
    assert "14:00" in text and "高数作业" in text


def test_preview_plan_text_notion_unbound(db_session, monkeypatch):
    """未绑定 Notion 数据源时回退为空，预览回落"无安排"文案。"""

    import backend.mcp_server.notion_calendar as nc

    monkeypatch.setattr(nc, "build_writer", lambda db: None)
    with db_session() as db:
        text = preview_plan_text(db, PLAN_DATE)
    assert "今天还没有安排" in text


def test_preview_plan_text_confirmed(db_session):
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        confirm_plan(db, PLAN_DATE, calendar_writer=None)
        text = preview_plan_text(db, PLAN_DATE)
        assert "✅ 已确认" in text and "⏳" not in text


# ---------- 确认 ----------


def test_confirm_plan_writes_version_and_syncs_calendar(db_session):
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        writer = FakeCalendarWriter()

        result = confirm_plan(db, PLAN_DATE, calendar_writer=writer)
        assert result.confirmed_count == 5
        assert result.version == 1
        assert result.notion_sync == {"created": 1, "updated": 0, "unchanged": 0}
        assert writer.calls == [PLAN_DATE]
        assert all(i.status == "confirmed" for i in plan_items(db))

        version = db.query(PlanVersion).filter(PlanVersion.date == PLAN_DATE.isoformat()).first()
        assert version is not None and version.version == 1
        import json

        payload = json.loads(version.payload)
        assert len(payload) == 5

        # 再次确认：无 draft 可确认，不产生新版本
        result2 = confirm_plan(db, PLAN_DATE, calendar_writer=FakeCalendarWriter())
        assert result2.confirmed_count == 0
        assert result2.version is None
        assert db.query(PlanVersion).count() == 1


def test_confirm_plan_reports_notion_error_without_blocking(db_session):
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)

        class BrokenWriter:
            def sync_plan_to_calendar(self, db, plan_date):
                raise RuntimeError("网络超时")

        result = confirm_plan(db, PLAN_DATE, calendar_writer=BrokenWriter())
        assert result.confirmed_count == 5
        assert result.notion_sync == {"error": "网络超时"}
        assert all(i.status == "confirmed" for i in plan_items(db))


# ---------- 调整 ----------


def test_adjust_plan_item(db_session):
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        task_item = next(i for i in plan_items(db) if i.item_type == "task")

        updated = adjust_plan_item(db, task_item.id, "20:00", "21:00", title="高数作业（晚自习）")
        assert updated["start_time"] == "20:00"
        assert updated["end_time"] == "21:00"
        assert updated["status"] == "adjusted"
        assert updated["title"] == "高数作业（晚自习）"


def test_adjust_plan_item_conflict_raises(db_session):
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        task_item = next(i for i in plan_items(db) if i.item_type == "task")
        # 与 08:00-09:40 课程块重叠
        with pytest.raises(ValueError, match="时间冲突"):
            adjust_plan_item(db, task_item.id, "08:30", "09:00")


def test_adjust_plan_item_syncs_calendar_when_confirmed(db_session):
    """该日计划已确认（已写日历）→ 调整后增量同步 Notion 日历。"""
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        confirm_plan(db, PLAN_DATE, calendar_writer=None)
        task_item = next(i for i in plan_items(db) if i.item_type == "task")

        writer = FakeCalendarWriter()
        updated = adjust_plan_item(
            db, task_item.id, "20:00", "21:00", calendar_writer=writer
        )
        assert updated["start_time"] == "20:00"
        assert updated["notion_sync"] == {"created": 1, "updated": 0, "unchanged": 0}
        assert writer.calls == [PLAN_DATE]  # 同步了当日
        # 已确认计划保持不变（adjusted 项本身除外）
        assert any(i.status == "confirmed" for i in plan_items(db, PLAN_DATE))


def test_adjust_plan_item_no_calendar_sync_when_draft(db_session):
    """草案阶段不写日历（确认时才统一写入）：writer 不触发。"""
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        task_item = next(i for i in plan_items(db) if i.item_type == "task")

        writer = FakeCalendarWriter()
        updated = adjust_plan_item(
            db, task_item.id, "20:00", "21:00", calendar_writer=writer
        )
        assert "notion_sync" not in updated
        assert writer.calls == []


def test_adjust_plan_item_calendar_error_does_not_block(db_session):
    """日历同步失败不阻断调整（notion_sync 记录错误）。"""
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        confirm_plan(db, PLAN_DATE, calendar_writer=None)
        task_item = next(i for i in plan_items(db) if i.item_type == "task")

        class BrokenWriter:
            def sync_plan_to_calendar(self, db, plan_date):
                raise RuntimeError("网络超时")

        updated = adjust_plan_item(
            db, task_item.id, "20:00", "21:00", calendar_writer=BrokenWriter()
        )
        assert updated["notion_sync"] == {"error": "网络超时"}
        assert updated["start_time"] == "20:00"  # 调整本身成功


def test_adjust_plan_item_bad_time_raises(db_session):
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        task_item = next(i for i in plan_items(db) if i.item_type == "task")
        with pytest.raises(ValueError, match="时间格式"):
            adjust_plan_item(db, task_item.id, "25:00", "26:00")


# ---------- 完成 + 校准 ----------


def test_mark_done_review_links_and_calibrates(db_session):
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        review_item = next(i for i in plan_items(db) if i.item_type == "review")

        result = mark_done(db, review_item.id, actual_minutes=45)
        assert result["status"] == "done"
        assert result["calibration_recorded"] is True
        assert result["linked_review_status"] == "done"

        # 复习计划联动置 done
        rs = db.get(ReviewSchedule, review_item.ref_id)
        assert rs.status == "done" and rs.completed_at is not None

        # 校准分桶：review × 课程(高数) × 难度3 × morning（09:40 开始）
        stat = db.query(CalibrationStat).filter(CalibrationStat.item_type == "review").first()
        assert stat is not None
        assert stat.time_bucket == "morning"
        assert stat.difficulty == 3
        assert stat.sample_count == 1
        assert stat.factor == pytest.approx(45 / 30)

        # 幂等：重复标记不重复计数
        mark_done(db, review_item.id, actual_minutes=45)
        stat = db.query(CalibrationStat).filter(CalibrationStat.item_type == "review").first()
        assert stat.sample_count == 1


def test_mark_done_task_records_calibration(db_session):
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        task_item = next(i for i in plan_items(db) if i.item_type == "task")

        result = mark_done(db, task_item.id, actual_minutes=90)
        assert result["status"] == "done"

        stat = db.query(CalibrationStat).filter(CalibrationStat.item_type == "task").first()
        assert stat is not None
        assert stat.course_id is not None  # 高数作业关联课程
        assert stat.difficulty is None
        assert stat.factor == pytest.approx(90 / 60)


def test_mark_done_without_actual_minutes_skips_calibration(db_session):
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        task_item = next(i for i in plan_items(db) if i.item_type == "task")
        result = mark_done(db, task_item.id)
        assert result["status"] == "done"
        assert result["calibration_recorded"] is False
        assert db.query(CalibrationStat).count() == 0


def test_mark_done_misc_rejected_for_calibration(db_session):
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        misc_item = next(i for i in plan_items(db) if i.item_type == "misc")
        with pytest.raises(ValueError, match="仅 task/review"):
            mark_done(db, misc_item.id, actual_minutes=20)


# ---------- 查询 ----------


def test_list_courses(db_session):
    with db_session() as db:
        seed_basic(db)
        courses = list_courses(db)
        assert len(courses) == 2
        tiers = {c["name"]: c["tier"] for c in courses}
        assert tiers == {"高等数学": "S", "大学英语": "B"}


def test_list_tasks_filter(db_session):
    with db_session() as db:
        seed_basic(db)
        db.add(Task(title="已完成的事", status="done"))
        db.commit()
        todos = list_tasks(db, status="todo")
        assert len(todos) == 1 and todos[0]["title"] == "高数作业"
        assert todos[0]["course_name"] == "高等数学"
        with pytest.raises(ValueError, match="未知任务状态"):
            list_tasks(db, status="bogus")


def test_list_reviews_filter(db_session):
    with db_session() as db:
        seed_basic(db)
        reviews = list_reviews(db, due_date=PLAN_DATE.isoformat())
        assert len(reviews) == 1
        assert reviews[0]["knowledge_point"] == "泰勒展开"
        assert reviews[0]["course_name"] == "高等数学"
        assert reviews[0]["difficulty"] == 3
        assert list_reviews(db) == reviews  # 不过滤时同样只有这一条


# ---------- 添加任务 + 计划联动 ----------


def _fixed_today(monkeypatch) -> date:
    """固定「今天」= 2026-08-24（周一，weekday()=0），避免依赖真实日期。"""
    today = date(2026, 8, 24)
    import backend.mcp_server.service as svc

    monkeypatch.setattr(svc, "shanghai_today", lambda: today)
    return today


def test_add_task_no_due_date_inserts_today(db_session, monkeypatch):
    """无 ddl 的任务直接插入今天（不等待、不确认），不动已有安排。"""
    today = _fixed_today(monkeypatch)
    with db_session() as db:
        seed_basic(db, today)
        generate_plan(db, today)
        before = {(i.start_time, i.end_time) for i in plan_items(db, today)}

        result = add_task(db, title="背单词", estimated_minutes=30)

        assert result.task["status"] == "todo"
        assert result.plan_action == "scheduled_today"
        assert result.placed is not None and result.placed["title"] == "背单词"
        assert "排进今天" in result.plan_message
        assert result.notion_sync is None
        # 已排好的项一个没动（增量插入）
        after = {(i.start_time, i.end_time) for i in plan_items(db, today) if i.title != "背单词"}
        assert after == before


def test_add_task_ddl_today_inserts_today(db_session, monkeypatch):
    """ddl=今天 → 插入今天（类型/时长正确落库）。"""
    today = _fixed_today(monkeypatch)
    with db_session() as db:
        seed_basic(db, today)
        result = add_task(
            db, title="实验报告", due_date=today.isoformat(),
            task_type="实验", estimated_minutes=60,
        )
        assert result.plan_action == "scheduled_today"
        assert result.placed is not None
        assert "排进今天" in result.plan_message
        task = db.get(Task, result.task["id"])
        assert task.task_type == "实验" and task.deadline == today.isoformat()


def test_add_task_ddl_tomorrow_inserts_tomorrow(db_session, monkeypatch):
    """ddl=明天 → 直接插入明天（不占用今天，也不等 21:00）。"""
    today = _fixed_today(monkeypatch)
    tomorrow_d = today + timedelta(days=1)
    with db_session() as db:
        seed_basic(db, today)
        result = add_task(db, title="明日截止作业", due_date=tomorrow_d.isoformat())
        assert result.plan_action == "scheduled_tomorrow"
        assert result.placed is not None and result.placed["title"] == "明日截止作业"
        assert "排进明天" in result.plan_message
        assert any(
            i.date == tomorrow_d.isoformat() and i.title == "明日截止作业"
            for i in db.query(PlanItem).all()
        )


def test_add_task_inserts_into_confirmed_day_without_touching_others(db_session, monkeypatch):
    """今天计划已确认 → 新任务也直接插入（无确认概念），其它 confirmed 项不动。"""
    today = _fixed_today(monkeypatch)
    with db_session() as db:
        seed_basic(db, today)
        generate_plan(db, today)
        confirm_plan(db, today, calendar_writer=None)
        before = {(i.start_time, i.end_time) for i in plan_items(db, today)}

        result = add_task(db, title="临时加的事", due_date=today.isoformat(), estimated_minutes=30)
        assert result.plan_action == "scheduled_today"
        assert result.placed is not None
        items = plan_items(db, today)
        new_items = [i for i in items if i.title == "临时加的事"]
        assert len(new_items) == 1
        assert new_items[0].status == "confirmed"  # 与当日状态一致
        assert {(i.start_time, i.end_time) for i in items if i.title != "临时加的事"} == before


def test_add_task_slot_full_reports(db_session, monkeypatch):
    """目标日 8:00-22:00 无空闲时段 → 明确提示排不下+引导手动安排。"""
    today = _fixed_today(monkeypatch)
    with db_session() as db:
        db.add(
            PlanItem(
                date=today.isoformat(), start_time="08:00", end_time="22:00",
                item_type="misc", ref_id=None, title="全天占位", status="confirmed",
            )
        )
        db.commit()
        result = add_task(db, title="挤不进去的事", estimated_minutes=30)
        assert result.plan_action == "deferred"
        assert "排不下了" in result.plan_message
        assert "挪到 HH:MM" in result.plan_message


def test_add_task_overdue_not_scheduled(db_session, monkeypatch):
    """ddl 已过 → 不自动排，明确提示手动处理。"""
    today = _fixed_today(monkeypatch)
    with db_session() as db:
        seed_basic(db, today)
        result = add_task(db, title="补录过期任务", due_date="2026-08-20")
        assert result.plan_action == "deferred"
        assert "已过" in result.plan_message
        assert not any(i.title == "补录过期任务" for i in plan_items(db, today))


def test_add_task_notion_writer_success_saves_source_ref(db_session, monkeypatch):
    _fixed_today(monkeypatch)
    with db_session() as db:
        class OkWriter:
            def create_task(self, payload):
                return {"page_id": "page-123", "missing_props": ["类型"]}

        result = add_task(db, title="高数作业", task_type="作业", task_writer=OkWriter())
        assert result.notion_sync == {
            "created": True,
            "page_id": "page-123",
            "missing_props": ["类型"],
        }
        assert db.get(Task, result.task["id"]).source_ref == "page-123"


def test_add_task_notion_writer_error_does_not_block(db_session, monkeypatch):
    """Notion 写入失败不阻断：本地任务仍在，错误进 notion_sync。"""
    _fixed_today(monkeypatch)
    with db_session() as db:
        class BrokenWriter:
            def create_task(self, payload):
                raise RuntimeError("网络超时")

        result = add_task(db, title="作业", task_writer=BrokenWriter())
        assert result.notion_sync == {"error": "网络超时"}
        assert db.get(Task, result.task["id"]) is not None


def test_add_task_validation(db_session):
    with db_session() as db:
        with pytest.raises(ValueError, match="标题不能为空"):
            add_task(db, title="   ")
        with pytest.raises(ValueError, match="未知任务类型"):
            add_task(db, title="x", task_type="随笔")
        with pytest.raises(ValueError, match="日期格式"):
            add_task(db, title="x", due_date="2026/08/24")
        with pytest.raises(ValueError, match="课程不存在"):
            add_task(db, title="x", course_id=999)
        assert db.query(Task).count() == 0  # 校验失败不落库


# ---------- 工具函数 ----------


def test_time_bucket_for():
    assert time_bucket_for("09:00") == "morning"
    assert time_bucket_for("12:00") == "afternoon"
    assert time_bucket_for("14:30") == "afternoon"
    assert time_bucket_for("18:00") == "evening"
    assert time_bucket_for("21:30") == "evening"
