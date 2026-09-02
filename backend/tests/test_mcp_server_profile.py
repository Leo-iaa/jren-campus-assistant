"""用户画像集成测试：学习埋点（adjust/mark_done/add_task）+ 规划器消费 + MCP 工具。

使用 conftest 的临时 SQLite 数据库夹具，不依赖任何外部服务。
覆盖 Issue #63 验收清单：
- 行为事件落库 + 学习规则刷新（阈值：2 次不触发 / 3 次触发）
- 规划器消费：偏好时段优先、晚间脑力截止、固定安排屏障、空画像行为不变
- get_user_profile / update_user_profile 工具（含手动偏好增删改）
"""
import json
from datetime import date, time

import pytest

from backend.mcp_server.profile_store import (
    get_profile,
    parse_fixed_activities,
    save_manual_prefs,
)
from backend.mcp_server.service import (
    add_task,
    adjust_plan_item,
    generate_plan,
    mark_done,
    shanghai_today,
)
from backend.models import (
    Course,
    CourseSession,
    KnowledgePoint,
    MiscItem,
    PlanItem,
    ProfileEvent,
    ReviewSchedule,
    Task,
    UserProfile,
)
from backend.scheduler.profile import evaluate_rules

# 2026-08-19 为周三（weekday()=2），课程时间块按此对齐
PLAN_DATE = date(2026, 8, 19)


def seed_basic(db, plan_date: date = PLAN_DATE) -> None:
    """标准测试数据：1 门 S 档硬课 + 任务 + 复习 + 杂项（无 B 档释放块）。"""
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


def item_by_title(db, title: str, plan_date: date = PLAN_DATE) -> PlanItem:
    return (
        db.query(PlanItem)
        .filter(PlanItem.date == plan_date.isoformat(), PlanItem.title == title)
        .first()
    )


def feature(db, key: str) -> UserProfile | None:
    return db.query(UserProfile).filter(UserProfile.feature_key == key).first()


# ---------- 学习埋点：adjust_plan_item ----------


def test_adjust_three_times_learns_prefer_bucket(db_session):
    with db_session() as db:
        seed_basic(db)
        course = db.query(Course).filter(Course.name == "高等数学").first()
        db.add(Task(title="高数作业B", course_id=course.id, estimated_minutes=60, status="todo"))
        db.add(Task(title="高数作业C", course_id=course.id, estimated_minutes=60, status="todo"))
        db.commit()
        generate_plan(db, PLAN_DATE)

        # 前 2 次跨时段调整（下午→晚上）：只记事件，不学习（阈值 3）
        adjust_plan_item(db, item_by_title(db, "高数作业").id, "19:00", "20:00")
        adjust_plan_item(db, item_by_title(db, "高数作业B").id, "20:00", "21:00")
        assert db.query(ProfileEvent).filter(ProfileEvent.event_type == "adjust").count() == 2
        assert feature(db, "prefer_bucket.高等数学") is None

        # 第 3 次跨时段调整 → 触发学习
        adjust_plan_item(db, item_by_title(db, "高数作业C").id, "21:00", "22:00")
        learned = feature(db, "prefer_bucket.高等数学")
        assert learned is not None
        assert learned.value == "evening"
        assert learned.confidence == 3
        assert learned.source == "learned"
        assert "高数作业" in learned.evidence and "晚上" in learned.evidence


def test_adjust_within_same_bucket_does_not_learn(db_session):
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        task_item = item_by_title(db, "高数作业")
        # 19:00→20:00 都是晚上：同段微调不构成「挪时段」信号
        for _ in range(3):
            adjust_plan_item(db, task_item.id, "19:00", "20:00")
        assert feature(db, "prefer_bucket.高等数学") is None


def test_adjust_course_item_does_not_learn(db_session):
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        course_item = item_by_title(db, "高等数学")
        # 课程是固定安排，挪动不构成偏好信号（也防止把课表弄乱后误学习）
        for _ in range(3):
            adjust_plan_item(db, course_item.id, "16:00", "17:40")
        assert db.query(ProfileEvent).count() == 0


# ---------- 学习埋点：mark_done ----------


def test_mark_done_fit_bucket_across_days(db_session):
    """3 个不同日期的任务项在晚上完成 → fit_bucket.高等数学。"""
    for offset in range(3):
        with db_session() as db:
            d = date(2026, 8, 19 + offset)
            course = Course(name="高等数学", tier="S")
            db.add(course)
            db.flush()
            db.add(
                CourseSession(
                    course_id=course.id,
                    day_of_week=d.weekday(),
                    start_time="08:00",
                    end_time="09:40",
                    release_slot=0,
                )
            )
            db.add(
                Task(
                    title=f"高数作业{offset}",
                    course_id=course.id,
                    estimated_minutes=60,
                    status="todo",
                )
            )
            db.commit()
            generate_plan(db, d)
            task_item = item_by_title(db, f"高数作业{offset}", d)
            # 挪到晚上再完成（同时验证调整 + 完成两种信号不串）
            adjust_plan_item(db, task_item.id, "19:00", "20:00")
            mark_done(db, task_item.id)
    with db_session() as db:
        fit = feature(db, "fit_bucket.高等数学")
        assert fit is not None
        assert fit.value == "evening"
        assert fit.confidence == 3
        assert "晚上完成" in fit.evidence
        prefer = feature(db, "prefer_bucket.高等数学")
        assert prefer is not None and prefer.confidence == 3  # R1 同时触发


# ---------- 学习埋点：add_task（只记事件不学习） ----------


def test_add_task_records_event_but_does_not_learn(db_session):
    with db_session() as db:
        seed_basic(db)
        result = add_task(db, title="英语听力", due_date=shanghai_today().isoformat())
        assert result.placed is not None
        events = db.query(ProfileEvent).all()
        assert len(events) == 1
        assert events[0].event_type == "add_task"
        assert events[0].subject == "英语听力"  # 无课程 → 用标题
        assert feature(db, "prefer_bucket.英语听力") is None


# ---------- 规划器消费 ----------


def test_generate_plan_prefers_learned_bucket(db_session):
    """画像学到「高数偏好晚上」后，重新生成的任务应落在晚上。"""
    with db_session() as db:
        seed_basic(db)
        # 手动制造画像特征（等价于 3 次调整学到的结果）
        db.add(
            UserProfile(
                feature_key="prefer_bucket.高等数学",
                feature_type="prefer_bucket",
                value="evening",
                confidence=3,
                evidence="观察到 2026-08-19 至 2026-08-24 共 3 次把「高数作业」调整到晚上",
                source="learned",
            )
        )
        db.commit()

        generate_plan(db, PLAN_DATE)
        task_item = item_by_title(db, "高数作业")
        review_item = item_by_title(db, "复习 · 泰勒展开")
        assert task_item.start_time >= "18:00"  # 晚上
        assert review_item.start_time >= "18:00"  # 同课程复习同样偏好

        # 无画像时对照：任务应排在上午（见 test_planner_unchanged_without_profile）


def test_planner_unchanged_without_profile(db_session):
    """空画像 → 规划行为与旧版完全一致（无 user_profile / profile_events 行）。"""
    with db_session() as db:
        seed_basic(db)
        generate_plan(db, PLAN_DATE)
        assert db.query(UserProfile).count() == 0
        assert db.query(ProfileEvent).count() == 0
        task_item = item_by_title(db, "高数作业")
        # S 档课后复习 09:40-10:40（Issue #74）+ 知识点复习 10:40-11:10 把上午空档
        # 占到只剩 50 分钟；任务 60 分钟放不下 → 落到 12:00 分桶边界后的下午
        assert task_item.start_time == "12:00"


def test_generate_plan_respects_no_brain_after(db_session):
    """手动设置 21:00 后不排脑力 → task/review 结束时间不晚于 21:00，misc 不受限。"""
    with db_session() as db:
        save_manual_prefs(db, no_brain_after="21:00")
        course = Course(name="无课日", tier="S")
        db.add(course)
        db.flush()
        db.add(Task(title="长作业", course_id=None, estimated_minutes=180, status="todo"))
        db.add(MiscItem(title="夜跑", duration_minutes=60, status="todo"))
        db.commit()

        generate_plan(db, PLAN_DATE)
        task_item = item_by_title(db, "长作业")
        misc_item = item_by_title(db, "夜跑")
        assert task_item.end_time <= "21:00"
        # 杂项不受脑力截止约束（但贪心最早适配仍可能早于 21:00，只断言其合法存在）
        assert misc_item is not None
        assert all(
            it.end_time <= "22:00" for it in plan_items(db)
        )


def test_generate_plan_respects_fixed_activities(db_session):
    """固定安排（跑步 09:00-10:00）成为屏障：任务不落入该时段。"""
    with db_session() as db:
        save_manual_prefs(
            db,
            fixed_activities=json.dumps(
                [{"title": "跑步", "days": "三", "start": "09:00", "end": "10:00"}]
            ),
        )
        db.add(Task(title="无课作业", estimated_minutes=60, status="todo"))
        db.commit()

        generate_plan(db, PLAN_DATE)  # 周三 → 跑步生效
        task_item = item_by_title(db, "无课作业")
        # 屏障扣除后窗口：08:00-09:00 / 10:00-22:00 → 任务落在 08:00-09:00
        assert (task_item.start_time, task_item.end_time) == ("08:00", "09:00")


def test_fixed_activities_clipped_by_course(db_session):
    """固定安排与课程重叠 → 自动裁剪不报错，仅保留空闲时段内的部分。"""
    with db_session() as db:
        save_manual_prefs(
            db,
            fixed_activities=json.dumps(
                [{"title": "午休", "days": "三", "start": "08:30", "end": "12:00"}]
            ),
        )
        seed_basic(db)  # 高数课 08:00-09:40
        db.add(Task(title="课后作业", estimated_minutes=60, status="todo"))
        db.commit()

        generate_plan(db, PLAN_DATE)
        task_item = item_by_title(db, "课后作业")
        # 09:40-12:00 被午休屏障占用 → 任务最早从 12:00 起
        assert task_item.start_time >= "12:00"


def test_misc_preferred_time_maps_to_bucket(db_session):
    """杂项显式 preferred_time → 换算为偏好时段，优先排进该时段。"""
    with db_session() as db:
        db.add(MiscItem(title="跑步", duration_minutes=60, preferred_time="17:30", status="todo"))
        db.add(Task(title="占位作业", estimated_minutes=60, status="todo"))
        db.commit()
        generate_plan(db, PLAN_DATE)
        misc_item = item_by_title(db, "跑步")
        assert misc_item.start_time >= "12:00" and misc_item.start_time < "18:00"  # 下午


# ---------- 手动偏好 ----------


def test_save_manual_prefs_roundtrip(db_session):
    with db_session() as db:
        result = save_manual_prefs(db, rhythm="夜猫", no_brain_after="22:00")
        assert result["rhythm"] == "夜猫"
        assert result["no_brain_after"] == "22:00"

        result = save_manual_prefs(
            db,
            fixed_activities=json.dumps(
                [
                    {"title": "跑步", "days": "一三五", "start": "17:00", "end": "18:00"},
                    {"title": "午休", "days": "每天", "start": "12:30", "end": "13:30"},
                ]
            ),
        )
        assert result["fixed_activities"] == [
            {"title": "跑步", "days": "一三五", "start": "17:00", "end": "18:00"},
            {"title": "午休", "days": "每天", "start": "12:30", "end": "13:30"},
        ]

        # 空字符串清除
        result = save_manual_prefs(db, rhythm="", no_brain_after="")
        assert result["rhythm"] == "unknown"
        assert result["no_brain_after"] is None
        with db_session() as db2:
            assert db2.query(UserProfile).filter(UserProfile.feature_key == "rhythm").count() == 0


def test_save_manual_prefs_validates(db_session):
    with db_session() as db:
        with pytest.raises(ValueError):
            save_manual_prefs(db, rhythm="修仙党")
        with pytest.raises(ValueError):
            save_manual_prefs(db, no_brain_after="25:00")
        with pytest.raises(ValueError):
            save_manual_prefs(db, fixed_activities="不是JSON")
        with pytest.raises(ValueError):
            save_manual_prefs(db, fixed_activities=json.dumps([{"title": "跑步", "days": "八", "start": "17:00", "end": "18:00"}]))
        with pytest.raises(ValueError):
            save_manual_prefs(
                db,
                fixed_activities=json.dumps(
                    [
                        {"title": "跑步", "days": "三", "start": "17:00", "end": "18:00"},
                        {"title": "吃饭", "days": "三", "start": "17:30", "end": "18:30"},
                    ]
                ),
            )  # 同日重叠
        with pytest.raises(ValueError):
            save_manual_prefs(db, fixed_activities=json.dumps([{"title": "跑步", "days": "三", "start": "18:00", "end": "18:00"}]))


def test_parse_fixed_activities_normalizes():
    parsed = parse_fixed_activities(
        json.dumps([{"title": "跑步", "days": "六日", "start": "08:00", "end": "09:00"}])
    )
    assert parsed[0]["days"] == [5, 6]  # 周六=5 周日=6
    parsed_all = parse_fixed_activities(json.dumps([{"title": "午休", "days": "每天", "start": "12:00", "end": "13:00"}]))
    assert parsed_all[0]["days"] == [0, 1, 2, 3, 4, 5, 6]


def test_get_profile_sections(db_session):
    with db_session() as db:
        save_manual_prefs(db, rhythm="早鸟")
        db.add(
            UserProfile(
                feature_key="prefer_bucket.高等数学",
                feature_type="prefer_bucket",
                value="evening",
                confidence=3,
                evidence="观察到 2026-08-19 至 2026-08-24 共 3 次把「高数作业」调整到晚上",
                source="learned",
            )
        )
        db.commit()
        profile = get_profile(db)
        assert profile["rhythm"] == "早鸟"
        assert profile["no_brain_after"] is None
        assert profile["fixed_activities"] == []
        assert len(profile["learned"]) == 1
        assert profile["learned"][0]["evidence"].startswith("观察到")
        assert profile["recent_events"] == []
        assert profile["updated_at"] is not None


def test_refresh_removes_stale_learned_feature(db_session):
    """窗口内证据不再满足 → 旧特征删除（画像反映最近行为）。"""
    with db_session() as db:
        db.add(
            UserProfile(
                feature_key="prefer_bucket.高等数学",
                feature_type="prefer_bucket",
                value="evening",
                confidence=3,
                evidence="观察到 2026-08-01 至 2026-08-05 共 3 次把「高数作业」调整到晚上",
                source="learned",
            )
        )
        db.commit()
        # 当前无任何近期事件 → 刷新后删除过期特征
        from backend.mcp_server.profile_store import refresh_learned_features

        refresh_learned_features(db)
        db.commit()
        assert feature(db, "prefer_bucket.高等数学") is None
