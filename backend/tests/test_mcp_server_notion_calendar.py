"""MCP Server 暴露层 · Notion Calendar 写入器测试（backend/mcp_server/notion_calendar.py）。

传输层注入 FakeJsonRpcTransport（tests/fakes.py），不需要真实 Notion 账号。
"""
from datetime import date

import pytest

from backend.mcp_client.transport import McpClient
from backend.mcp_server.notion_calendar import (
    NotionCalendarError,
    NotionCalendarWriter,
    build_writer,
)
from backend.models import DataSource, PlanItem
from tests.fakes import FakeJsonRpcTransport

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


def writer_with(fake: FakeJsonRpcTransport) -> NotionCalendarWriter:
    return NotionCalendarWriter(client=McpClient(fake), config=CALENDAR_CONFIG)


def fake_transport(existing_pages: list[dict] | None = None) -> FakeJsonRpcTransport:
    """构造含全部工具响应的假传输（默认无已存在事件）。"""
    return FakeJsonRpcTransport(
        call_results={
            "query_database": {"structuredContent": {"results": existing_pages or []}},
            "create_page": {"structuredContent": {"id": "new-page"}},
            "update_page": {"structuredContent": {"id": "updated-page"}},
        }
    )


def tool_calls(fake: FakeJsonRpcTransport, name: str) -> list[dict]:
    return [
        params for method, params in fake.calls
        if method == "tools/call" and params["name"] == name
    ]


# ---------- 幂等写入 ----------


def test_sync_creates_missing_events_with_reminder(db_session):
    with db_session() as db:
        add_plan_item(db, "高数作业", "10:00", "11:00", "task")
        fake = fake_transport()
        result = writer_with(fake).sync_plan_to_calendar(db, PLAN_DATE)

        assert result.created == 1 and result.updated == 0 and result.unchanged == 0

        creates = tool_calls(fake, "create_page")
        assert len(creates) == 1
        args = creates[0]["arguments"]
        assert args["parent"] == {"database_id": DB_ID}
        props = args["properties"]
        # 标题 / 日期（+08:00 偏移，避免 Notion 按 UTC 解析偏差）/ 08:00 提醒 / 类型
        assert props["名称"]["title"][0]["text"]["content"] == "高数作业"
        assert props["日期"]["date"]["start"] == "2026-08-19T10:00:00+08:00"
        assert props["日期"]["date"]["end"] == "2026-08-19T11:00:00+08:00"
        assert props["日期"]["date"]["reminder"] == {"time": "08:00"}
        assert props["类型"]["select"] == {"name": "task"}


def test_sync_unchanged_when_event_matches(db_session):
    with db_session() as db:
        add_plan_item(db, "高数作业", "10:00", "11:00", "task")
        fake = fake_transport(
            existing_pages=[make_page("高数作业", "2026-08-19T10:00:00+08:00", "task")]
        )
        result = writer_with(fake).sync_plan_to_calendar(db, PLAN_DATE)

        assert result.created == 0 and result.updated == 0 and result.unchanged == 1
        assert tool_calls(fake, "create_page") == []
        assert tool_calls(fake, "update_page") == []


def test_sync_updates_when_time_changed(db_session):
    with db_session() as db:
        add_plan_item(db, "高数作业", "19:00", "20:00", "task")
        fake = fake_transport(
            existing_pages=[make_page("高数作业", "2026-08-19T10:00:00+08:00", "task")]
        )
        result = writer_with(fake).sync_plan_to_calendar(db, PLAN_DATE)

        assert result.updated == 1 and result.created == 0 and result.unchanged == 0
        updates = tool_calls(fake, "update_page")
        assert len(updates) == 1
        assert updates[0]["arguments"]["page_id"] == "page-高数作业"
        assert updates[0]["arguments"]["properties"]["日期"]["date"]["start"] == "2026-08-19T19:00:00+08:00"


def test_sync_skips_when_no_plan_items(db_session):
    with db_session() as db:
        fake = FakeJsonRpcTransport()
        result = writer_with(fake).sync_plan_to_calendar(db, PLAN_DATE)
        assert result.created == 0 and result.updated == 0 and result.unchanged == 0
        assert fake.calls == []  # 无计划项时不发起任何查询


def test_sync_uses_configured_property_names(db_session):
    with db_session() as db:
        add_plan_item(db, "高数作业", "10:00", "11:00", "task")
        fake = fake_transport()
        writer = NotionCalendarWriter(
            client=McpClient(fake),
            config={
                "calendar_database_id": DB_ID,
                "props": {"title": "Title", "date": "Date", "type": "Kind"},
            },
        )
        writer.sync_plan_to_calendar(db, PLAN_DATE)
        creates = tool_calls(fake, "create_page")
        assert "Title" in creates[0]["arguments"]["properties"]
        assert "Date" in creates[0]["arguments"]["properties"]
        assert "Kind" in creates[0]["arguments"]["properties"]


def test_sync_missing_database_id_raises(db_session):
    with db_session() as db:
        add_plan_item(db, "高数作业")
        fake = FakeJsonRpcTransport()
        writer = NotionCalendarWriter(client=McpClient(fake), config={})
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
