"""iCal 课表解析测试（真实教务导出格式的合成样例，见 tests/fakes.py）。"""
from __future__ import annotations

import pytest

from backend.mcp_client.ical import IcalAdapter, parse_ics
from tests.fakes import SAMPLE_ICS


def test_parse_merges_multi_vevent_same_slot():
    """同课程多 VEVENT（教师/教室更换）→ 按 (课程, 星期, 开始时间) 合并，保留最新。"""
    items, warnings = parse_ics(SAMPLE_ICS)
    by_name = {item.course_name: item for item in items}

    # 高等数学：两个 VEVENT 合并为一个；取首次上课日期更晚的（李四 / 教西A1-201）
    math = by_name["高等数学"]
    assert math.day_of_week == 0  # 2026-05-04 是周一
    assert math.start_time == "08:00"
    assert math.end_time == "09:40"
    assert math.teacher == "李四"
    assert math.location == "教西A1-201"

    # 大学英语：无 LOCATION → 从 DESCRIPTION 兜底取 教室/教师
    english = by_name["大学英语"]
    assert english.day_of_week == 1  # 2026-03-03 是周二
    assert english.start_time == "14:00"
    assert english.end_time == "15:40"
    assert english.location == "教西C2-301"
    assert english.teacher == "王五"

    # 非每周（DAILY）与无 RRULE 的单次事件 → 跳过并告警
    assert "临时讲座" not in by_name
    assert "调课单次" not in by_name
    assert len(warnings) == 2
    assert any("非每周" in w for w in warnings)
    assert any("无 RRULE" in w for w in warnings)

    assert len(items) == 2


def test_parse_room_without_teacher():
    """LOCATION 只有教室（无教师）也能正确解析。"""
    ics = SAMPLE_ICS.replace("LOCATION:教西A1-101 张三", "LOCATION:教西A1-101").replace(
        "LOCATION:教西A1-201 李四", "LOCATION:教西A1-201"
    )
    items, _ = parse_ics(ics)
    math = next(item for item in items if item.course_name == "高等数学")
    assert math.location == "教西A1-201"  # 合并后取最新 VEVENT
    assert math.teacher is None


def test_adapter_from_file(tmp_path):
    """IcalAdapter 支持从 .ics 文件解析。"""
    ics_file = tmp_path / "schedule.ics"
    ics_file.write_text(SAMPLE_ICS, encoding="utf-8")
    adapter = IcalAdapter(ics_path=str(ics_file))
    items, warnings = adapter.parse()
    assert len(items) == 2
    assert len(warnings) == 2


def test_adapter_requires_source():
    with pytest.raises(ValueError, match="ics_path 或 ics_content"):
        IcalAdapter()


def test_adapter_missing_file():
    adapter = IcalAdapter(ics_path="C:/不存在的文件.ics")
    with pytest.raises(ValueError, match="不存在"):
        adapter.parse()


def test_parse_ignores_valarm_and_calendar_meta():
    """VALARM / VTIMEZONE 等非 VEVENT 组件不影响解析。"""
    items, _ = parse_ics(SAMPLE_ICS)
    assert all(isinstance(item.course_name, str) for item in items)


def test_parse_skips_bad_time_event():
    """结束不晚于开始的事件被跳过并告警（此前仅告警仍入库，会让规划器崩溃）。"""
    ics = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:bad-1
SUMMARY:异常课
DTSTART;TZID=Asia/Shanghai:20260302T100000
DTEND;TZID=Asia/Shanghai:20260302T090000
RRULE:FREQ=WEEKLY;UNTIL=20260621T160000Z;INTERVAL=1
END:VEVENT
BEGIN:VEVENT
UID:good-1
SUMMARY:正常课
DTSTART;TZID=Asia/Shanghai:20260303T140000
DTEND;TZID=Asia/Shanghai:20260303T154000
RRULE:FREQ=WEEKLY;UNTIL=20260620T160000Z;INTERVAL=1
END:VEVENT
END:VCALENDAR
"""
    items, warnings = parse_ics(ics)
    assert [item.course_name for item in items] == ["正常课"]
    assert any("时间异常" in w for w in warnings)
