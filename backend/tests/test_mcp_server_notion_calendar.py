"""MCP Server 暴露层 · Notion Calendar 写入器测试（backend/mcp_server/notion_calendar.py）。

客户端注入 FakeNotionRest（tests/fakes.py），不需要真实 Notion 账号。
"""
from datetime import date

import pytest

from backend.mcp_server.notion_calendar import (
    NotionCalendarError,
    NotionCalendarWriter,
    build_writer,
)
from backend.models import DataSource, PlanItem
from tests.fakes import FakeNotionRest

PLAN_DATE = date(2026, 8, 19)
DB_ID = "cal-db-123"

CALENDAR_CONFIG = {
    "calendar_database_id": DB_ID,
    "props": {"title": "名称", "date": "日期", "type": "类型"},
}


def add_plan_item(db, title: str, start: str = "10:00", end: str = "11:00", item_type: str = "task") -> PlanItem:
    item = PlanItem(
        date=PLAN_DATE.isoformat(),
        start_time=start,
        end_time=end,
        item_type=item_type,
        ref_id=None,
        title=title,
        status="confirmed",
    )
    db.add(item)
    db.commit()
    return item


def make_page(title: str, start: str, item_type: str = "task") -> dict:
    """模拟 Notion 查询返回的事件页（属性名与 CALENDAR_CONFIG 一致，响应格式 plain_text）。"""
    return {
        "id": f"page-{title}",
        "properties": {
            "名称": {"title": [{"type": "text", "plain_text": title}]},
            "日期": {"date": {"start": start}},
            "类型": {"select": {"name": item_type}},
        },
    }


def writer_with(fake: FakeNotionRest) -> NotionCalendarWriter:
    return NotionCalendarWriter(client=fake, config=CALENDAR_CONFIG)


def fake_rest(existing_pages: list[dict] | None = None) -> FakeNotionRest:
    """构造假 Notion REST 客户端（默认无已存在事件）。"""
    return FakeNotionRest(query_results=existing_pages or [])


def rest_calls(fake: FakeNotionRest, method: str) -> list[dict]:
    return [kwargs for m, kwargs in fake.calls if m == method]


# ---------- 幂等写入 ----------


def test_sync_creates_missing_events(db_session):
    with db_session() as db:
        add_plan_item(db, "高数作业", "10:00", "11:00", "task")
        fake = fake_rest()
        result = writer_with(fake).sync_plan_to_calendar(db, PLAN_DATE)

        assert result.created == 1 and result.updated == 0 and result.unchanged == 0

        creates = rest_calls(fake, "create_page")
        assert len(creates) == 1
        kwargs = creates[0]
        assert kwargs["parent_database_id"] == DB_ID
        props = kwargs["properties"]
        # 标题 / 日期（+08:00 偏移，避免 Notion 按 UTC 解析偏差）/ 类型
        # （不带 reminder：Notion API 限制 datetime 属性不能带提醒，08:00 提醒由微信推送承担）
        assert props["名称"]["title"][0]["text"]["content"] == "高数作业"
        assert props["日期"]["date"]["start"] == "2026-08-19T10:00:00+08:00"
        assert props["日期"]["date"]["end"] == "2026-08-19T11:00:00+08:00"
        assert "reminder" not in props["日期"]["date"]
        assert props["类型"]["select"] == {"name": "task"}


def test_sync_unchanged_when_event_matches(db_session):
    with db_session() as db:
        add_plan_item(db, "高数作业", "10:00", "11:00", "task")
        fake = fake_rest(
            existing_pages=[make_page("高数作业", "2026-08-19T10:00:00+08:00", "task")]
        )
        result = writer_with(fake).sync_plan_to_calendar(db, PLAN_DATE)

        assert result.created == 0 and result.updated == 0 and result.unchanged == 1
        assert rest_calls(fake, "create_page") == []
        assert rest_calls(fake, "update_page") == []


def test_sync_updates_when_time_changed(db_session):
    with db_session() as db:
        add_plan_item(db, "高数作业", "19:00", "20:00", "task")
        fake = fake_rest(
            existing_pages=[make_page("高数作业", "2026-08-19T10:00:00+08:00", "task")]
        )
        result = writer_with(fake).sync_plan_to_calendar(db, PLAN_DATE)

        assert result.updated == 1 and result.created == 0 and result.unchanged == 0
        updates = rest_calls(fake, "update_page")
        assert len(updates) == 1
        assert updates[0]["page_id"] == "page-高数作业"
        assert updates[0]["properties"]["日期"]["date"]["start"] == "2026-08-19T19:00:00+08:00"


def test_sync_same_title_different_time_creates_both(db_session):
    """同日同名但不同时段的事件各自建页（此前仅按标题匹配会互相覆盖 / 错位）。"""
    with db_session() as db:
        add_plan_item(db, "高数作业", "10:00", "11:00", "task")
        add_plan_item(db, "高数作业", "19:00", "20:00", "task")
        fake = fake_rest()
        result = writer_with(fake).sync_plan_to_calendar(db, PLAN_DATE)

        assert result.created == 2 and result.updated == 0 and result.unchanged == 0
        creates = rest_calls(fake, "create_page")
        assert len(creates) == 2
        starts = {c["properties"]["日期"]["date"]["start"] for c in creates}
        assert starts == {"2026-08-19T10:00:00+08:00", "2026-08-19T19:00:00+08:00"}


def test_sync_skips_when_no_plan_items(db_session):
    with db_session() as db:
        fake = FakeNotionRest()
        result = writer_with(fake).sync_plan_to_calendar(db, PLAN_DATE)
        assert result.created == 0 and result.updated == 0 and result.unchanged == 0
        assert fake.calls == []  # 无计划项时不发起任何查询


def test_sync_uses_configured_property_names(db_session):
    with db_session() as db:
        add_plan_item(db, "高数作业", "10:00", "11:00", "task")
        fake = fake_rest()
        writer = NotionCalendarWriter(
            client=fake,
            config={
                "calendar_database_id": DB_ID,
                "props": {"title": "Title", "date": "Date", "type": "Kind"},
            },
        )
        writer.sync_plan_to_calendar(db, PLAN_DATE)
        creates = rest_calls(fake, "create_page")
        assert "Title" in creates[0]["properties"]
        assert "Date" in creates[0]["properties"]
        assert "Kind" in creates[0]["properties"]


def test_sync_missing_database_id_raises(db_session):
    with db_session() as db:
        add_plan_item(db, "高数作业")
        fake = FakeNotionRest()
        writer = NotionCalendarWriter(client=fake, config={})
        with pytest.raises(NotionCalendarError, match="calendar_database_id"):
            writer.sync_plan_to_calendar(db, PLAN_DATE)


# ---------- build_writer（从 data_sources 构造） ----------


def test_build_writer_none_without_notion_source(db_session):
    with db_session() as db:
        assert build_writer(db) is None


def test_build_writer_requires_authorization(db_session):
    with db_session() as db:
        db.add(DataSource(source_type="notion", name="Notion", config="{}", enabled=1))
        db.commit()
        with pytest.raises(NotionCalendarError, match="未授权"):
            build_writer(db)


def test_build_writer_requires_calendar_database_id(db_session, monkeypatch):
    monkeypatch.delenv("JREN_NOTION_CALENDAR_DB", raising=False)
    with db_session() as db:
        db.add(
            DataSource(
                source_type="notion",
                name="Notion",
                config='{"tokens": {"access_token": "tok", "expires_at": "9999999999"}}',
                enabled=1,
            )
        )
        db.commit()
        with pytest.raises(NotionCalendarError, match="calendar_database_id"):
            build_writer(db)


def test_build_writer_ok_with_config(db_session):
    with db_session() as db:
        db.add(
            DataSource(
                source_type="notion",
                name="Notion",
                config=(
                    '{"tokens": {"access_token": "tok", "expires_at": "9999999999"},'
                    f'"calendar_database_id": "{DB_ID}"}}'
                ),
                enabled=1,
            )
        )
        db.commit()
        writer = build_writer(db)
        assert writer is not None
        assert writer.props["title"] == "名称"  # 默认属性名


def test_build_writer_uses_env_database_id(db_session, monkeypatch):
    monkeypatch.setenv("JREN_NOTION_CALENDAR_DB", "env-db-456")
    with db_session() as db:
        db.add(
            DataSource(
                source_type="notion",
                name="Notion",
                config='{"tokens": {"access_token": "tok", "expires_at": "9999999999"}}',
                enabled=1,
            )
        )
        db.commit()
        writer = build_writer(db)
        assert writer is not None
        assert writer.config["calendar_database_id"] == "env-db-456"  # 环境变量已写回 config
