"""MCP Server 暴露层 · Notion 任务库写入器测试（backend/mcp_server/notion_task.py）。

客户端注入 FakeNotionRest（tests/fakes.py），不需要真实 Notion 账号。
核心场景：属性探测降级——任务库缺「类型」属性时跳过并报告，不阻断写入。
"""
import pytest

from backend.mcp_server.notion_task import (
    NotionTaskError,
    NotionTaskWriter,
    build_task_writer,
)
from backend.models import DataSource
from tests.fakes import FakeNotionRest

DB_ID = "task-db-123"

#: 模拟用户任务库真实结构（任务列表模板：状态选项为中文「未开始」，无「类型」属性）
TASK_DB_SCHEMA = {
    "properties": {
        "任务名称": {"type": "title"},
        "截止日期": {"type": "date"},
        "当前状态": {
            "type": "status",
            "status": {
                "options": [
                    {"id": "o1", "name": "未开始"},
                    {"id": "o2", "name": "进行中"},
                    {"id": "o3", "name": "已完成"},
                ],
                "groups": [{"id": "g1", "name": "To-do", "option_ids": ["o1"]}],
            },
        },
        "优先级": {"type": "select"},
        "备注": {"type": "rich_text"},
    }
}

#: 用户补了「类型」属性后的结构
TASK_DB_SCHEMA_WITH_TYPE = {
    "properties": {
        **TASK_DB_SCHEMA["properties"],
        "类型": {"type": "select", "select": {"options": []}},
    }
}

TASK_CONFIG = {"task_database_id": DB_ID}


def writer_with(fake: FakeNotionRest, config: dict | None = None) -> NotionTaskWriter:
    return NotionTaskWriter(client=fake, config=config or TASK_CONFIG)


def rest_calls(fake: FakeNotionRest, method: str) -> list[dict]:
    return [kwargs for m, kwargs in fake.calls if m == method]


# ---------- create_task ----------


def test_create_task_writes_core_props_and_reports_missing_type():
    """任务库无「类型」属性：写入 名称/截止日期/状态，类型进 missing_props。"""
    fake = FakeNotionRest(database_schema=TASK_DB_SCHEMA)
    result = writer_with(fake).create_task(
        {"title": "高数作业", "deadline": "2026-08-26", "task_type": "作业"}
    )

    assert result["page_id"] == "new-page"
    assert result["missing_props"] == ["类型"]

    creates = rest_calls(fake, "create_page")
    assert len(creates) == 1
    props = creates[0]["properties"]
    assert props["任务名称"]["title"][0]["text"]["content"] == "高数作业"
    assert props["截止日期"]["date"] == {"start": "2026-08-26"}  # date-only，无 end
    # 状态选项名动态取自 schema（中文模板为「未开始」，不是分组名 To-do）
    assert props["当前状态"]["status"] == {"name": "未开始"}
    assert "类型" not in props
    assert creates[0]["parent_database_id"] == DB_ID


def test_create_task_status_falls_back_to_first_option():
    """无 To-do 分组时取首个选项；status 属性无选项则不写状态。"""
    schema = {
        "properties": {
            "任务名称": {"type": "title"},
            "当前状态": {"type": "status", "status": {"options": [{"id": "x", "name": "待办"}]}},
        }
    }
    fake = FakeNotionRest(database_schema=schema)
    writer_with(fake).create_task({"title": "t"})
    props = rest_calls(fake, "create_page")[0]["properties"]
    assert props["当前状态"]["status"] == {"name": "待办"}

    schema2 = {"properties": {"任务名称": {"type": "title"}, "当前状态": {"type": "status", "status": {}}}}
    fake2 = FakeNotionRest(database_schema=schema2)
    writer_with(fake2).create_task({"title": "t"})
    props2 = rest_calls(fake2, "create_page")[0]["properties"]
    assert "当前状态" not in props2


def test_create_task_writes_type_when_property_exists():
    """任务库补了「类型」属性后自动写入（零代码改动生效）。"""
    fake = FakeNotionRest(database_schema=TASK_DB_SCHEMA_WITH_TYPE)
    result = writer_with(fake).create_task(
        {"title": "电路实验", "deadline": "2026-08-27", "task_type": "实验"}
    )

    assert result["missing_props"] == []
    creates = rest_calls(fake, "create_page")
    assert creates[0]["properties"]["类型"]["select"] == {"name": "实验"}


def test_create_task_skips_deadline_when_date_prop_missing():
    fake = FakeNotionRest(database_schema={"properties": {"任务名称": {"type": "title"}}})
    result = writer_with(fake).create_task({"title": "裸标题", "deadline": "2026-08-26"})
    assert result["missing_props"] == ["截止日期"]
    props = rest_calls(fake, "create_page")[0]["properties"]
    assert "截止日期" not in props


def test_create_task_without_deadline_or_type():
    """只给标题的最小调用：不触发缺失报告。"""
    fake = FakeNotionRest(database_schema=TASK_DB_SCHEMA)
    result = writer_with(fake).create_task({"title": "取快递"})
    assert result["missing_props"] == []
    props = rest_calls(fake, "create_page")[0]["properties"]
    assert props["任务名称"]["title"][0]["text"]["content"] == "取快递"
    assert "截止日期" not in props


def test_create_task_missing_database_id_raises():
    fake = FakeNotionRest(database_schema=TASK_DB_SCHEMA)
    writer = NotionTaskWriter(client=fake, config={})
    with pytest.raises(NotionTaskError, match="task_database_id"):
        writer.create_task({"title": "x"})


def test_create_task_transport_error_raises_chinese_message():
    class BrokenRest:
        def retrieve_database(self, database_id):
            raise RuntimeError("网络超时")

    with pytest.raises(NotionTaskError, match="网络超时"):
        writer_with(BrokenRest()).create_task({"title": "x"})


# ---------- build_task_writer（从 data_sources 构造） ----------


def test_build_task_writer_none_without_notion_source(db_session):
    with db_session() as db:
        assert build_task_writer(db) is None


def test_build_task_writer_requires_authorization(db_session):
    with db_session() as db:
        db.add(DataSource(source_type="notion", name="Notion", config="{}", enabled=1))
        db.commit()
        with pytest.raises(NotionTaskError, match="未授权"):
            build_task_writer(db)


def test_build_task_writer_requires_task_database_id(db_session, monkeypatch):
    monkeypatch.delenv("JREN_NOTION_TASK_DB", raising=False)
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
        with pytest.raises(NotionTaskError, match="task_database_id"):
            build_task_writer(db)


def test_build_task_writer_ok_with_config(db_session):
    with db_session() as db:
        db.add(
            DataSource(
                source_type="notion",
                name="Notion",
                config=(
                    '{"tokens": {"access_token": "tok", "expires_at": "9999999999"},'
                    f'"task_database_id": "{DB_ID}"}}'
                ),
                enabled=1,
            )
        )
        db.commit()
        writer = build_task_writer(db)
        assert writer is not None
        assert writer.props["title"] == "任务名称"  # 默认属性名
        assert writer.config["task_database_id"] == DB_ID


def test_build_task_writer_uses_env_database_id(db_session, monkeypatch):
    monkeypatch.setenv("JREN_NOTION_TASK_DB", "env-task-456")
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
        writer = build_task_writer(db)
        assert writer is not None
        assert writer.config["task_database_id"] == "env-task-456"  # 环境变量已写回 config
