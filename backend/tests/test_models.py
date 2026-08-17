"""ORM 模型层测试：建表完整性、约束、级联行为（对照 docs/database.md DDL）。"""
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from backend import models

EXPECTED_TABLES = {
    "settings",
    "courses",
    "course_sessions",
    "knowledge_points",
    "review_schedules",
    "tasks",
    "plan_items",
    "misc_items",
    "data_sources",
    "calibration_stats",
    "plan_versions",
}


def _seed_course(db_session, name="高数", tier="A"):
    session = db_session()
    course = models.Course(name=name, tier=tier)
    session.add(course)
    session.commit()
    session.refresh(course)
    return course.id


# ---------- 建表完整性 ----------
def test_all_11_tables_created(db_session):
    engine = db_session().get_bind()
    tables = set(inspect(engine).get_table_names())
    assert EXPECTED_TABLES <= tables


# ---------- courses ----------
def test_course_default_tier_is_a(db_session):
    course_id = _seed_course(db_session)
    assert db_session().get(models.Course, course_id).tier == "A"


def test_course_tier_check_constraint(db_session):
    session = db_session()
    session.add(models.Course(name="非法档位", tier="X"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_course_name_not_null(db_session):
    session = db_session()
    session.add(models.Course(name=None, tier="A"))
    with pytest.raises(IntegrityError):
        session.commit()


# ---------- course_sessions ----------
def test_session_unique_conflict(db_session):
    course_id = _seed_course(db_session)
    session = db_session()
    session.add(
        models.CourseSession(course_id=course_id, day_of_week=0, start_time="08:00", end_time="09:40")
    )
    session.commit()
    session.add(
        models.CourseSession(course_id=course_id, day_of_week=0, start_time="08:00", end_time="10:00")
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_session_day_of_week_range(db_session):
    course_id = _seed_course(db_session)
    session = db_session()
    session.add(
        models.CourseSession(course_id=course_id, day_of_week=7, start_time="08:00", end_time="09:40")
    )
    with pytest.raises(IntegrityError):
        session.commit()


# ---------- knowledge_points ----------
def test_knowledge_point_difficulty_range(db_session):
    course_id = _seed_course(db_session)
    session = db_session()
    session.add(models.KnowledgePoint(course_id=course_id, title="x", difficulty=6))
    with pytest.raises(IntegrityError):
        session.commit()


def test_knowledge_point_status_check(db_session):
    course_id = _seed_course(db_session)
    session = db_session()
    session.add(models.KnowledgePoint(course_id=course_id, title="x", status="deleted"))
    with pytest.raises(IntegrityError):
        session.commit()


# ---------- review_schedules ----------
def test_review_unique_seq_per_kp(db_session):
    course_id = _seed_course(db_session)
    session = db_session()
    kp = models.KnowledgePoint(course_id=course_id, title="极限")
    session.add(kp)
    session.commit()
    session.refresh(kp)
    session.add(models.ReviewSchedule(knowledge_point_id=kp.id, seq=1, due_date="2026-08-18"))
    session.commit()
    session.add(models.ReviewSchedule(knowledge_point_id=kp.id, seq=1, due_date="2026-08-19"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_review_status_check(db_session):
    course_id = _seed_course(db_session)
    session = db_session()
    kp = models.KnowledgePoint(course_id=course_id, title="极限")
    session.add(kp)
    session.commit()
    session.refresh(kp)
    session.add(
        models.ReviewSchedule(knowledge_point_id=kp.id, seq=1, due_date="2026-08-18", status="nope")
    )
    with pytest.raises(IntegrityError):
        session.commit()


# ---------- tasks / misc_items ----------
def test_task_source_check(db_session):
    session = db_session()
    session.add(models.Task(title="x", source="wechat"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_misc_status_check(db_session):
    session = db_session()
    session.add(models.MiscItem(title="x", status="later"))
    with pytest.raises(IntegrityError):
        session.commit()


# ---------- plan_items / plan_versions ----------
def test_plan_item_time_conflict(db_session):
    session = db_session()
    session.add(
        models.PlanItem(date="2026-08-18", start_time="10:00", end_time="11:00", item_type="task", title="A")
    )
    session.commit()
    session.add(
        models.PlanItem(date="2026-08-18", start_time="10:00", end_time="10:30", item_type="review", title="B")
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_plan_versions_unique(db_session):
    session = db_session()
    session.add(models.PlanVersion(date="2026-08-18", version=1, payload="{}"))
    session.commit()
    session.add(models.PlanVersion(date="2026-08-18", version=1, payload="{}"))
    with pytest.raises(IntegrityError):
        session.commit()


# ---------- settings / calibration_stats ----------
def test_settings_unique_key(db_session):
    session = db_session()
    session.add(models.Setting(key="review_daily_cap", value="8"))
    session.commit()
    session.add(models.Setting(key="review_daily_cap", value="10"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_calibration_unique_bucket(db_session):
    """同一分桶（课程×时段×难度×类型）只能有一条。

    注意 SQLite 语义：UNIQUE 中 NULL 彼此视为不同，
    因此真实分桶（非 NULL 的 course_id/difficulty）才能触发冲突。
    """
    course_id = _seed_course(db_session)
    session = db_session()
    session.add(
        models.CalibrationStat(course_id=course_id, time_bucket="evening", difficulty=3, item_type="task")
    )
    session.commit()
    session.add(
        models.CalibrationStat(course_id=course_id, time_bucket="evening", difficulty=3, item_type="task")
    )
    with pytest.raises(IntegrityError):
        session.commit()


# ---------- 级联行为 ----------
def test_cascade_delete_course(db_session):
    """删课程 → 时间块/知识点/复习计划级联删除；任务保留且 course_id 置 NULL。"""
    session = db_session()
    course = models.Course(name="高数")
    session.add(course)
    session.flush()
    session.add(
        models.CourseSession(course_id=course.id, day_of_week=0, start_time="08:00", end_time="09:40")
    )
    kp = models.KnowledgePoint(course_id=course.id, title="极限")
    session.add(kp)
    session.flush()
    session.add(models.ReviewSchedule(knowledge_point_id=kp.id, seq=1, due_date="2026-08-18"))
    task = models.Task(course_id=course.id, title="作业1")
    session.add(task)
    session.commit()

    session.delete(course)
    session.commit()

    assert session.query(models.CourseSession).count() == 0
    assert session.query(models.KnowledgePoint).count() == 0
    assert session.query(models.ReviewSchedule).count() == 0
    assert session.query(models.Task).count() == 1
    assert session.get(models.Task, task.id).course_id is None


def test_cascade_delete_knowledge_point(db_session):
    """删知识点 → 其复习计划级联删除。"""
    course_id = _seed_course(db_session)
    session = db_session()
    kp = models.KnowledgePoint(course_id=course_id, title="极限")
    session.add(kp)
    session.flush()
    session.add(models.ReviewSchedule(knowledge_point_id=kp.id, seq=1, due_date="2026-08-18"))
    session.commit()

    session.delete(kp)
    session.commit()

    assert session.query(models.ReviewSchedule).count() == 0
