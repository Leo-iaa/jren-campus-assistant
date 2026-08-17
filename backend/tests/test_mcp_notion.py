"""Notion adapter 测试：fake 传输层 + Notion 风格属性映射（全 mock，无真实账号）。"""
from __future__ import annotations

import json

import pytest

from backend.mcp_client.notion import NotionAdapter
from backend.mcp_client.transport import McpClient
from tests.fakes import FakeJsonRpcTransport


def _page(page_id: str, title: str, **props) -> dict:
    """构造 Notion 风格 page 对象（properties 用中文常用属性名）。"""
    properties: dict = {"标题": {"title": [{"plain_text": title}]}}
    if "deadline" in props:
        properties["截止日期"] = {"date": {"start": props["deadline"]}}
    if "course" in props:
        properties["课程"] = {"select": {"name": props["course"]}}
    if "status" in props:
        properties["状态"] = {"status": {"name": props["status"]}}
    if "description" in props:
        properties["描述"] = {"rich_text": [{"plain_text": props["description"]}]}
    return {"id": page_id, "properties": properties}


def _make_adapter(call_results: dict, config: dict | None = None) -> tuple[NotionAdapter, FakeJsonRpcTransport]:
    transport = FakeJsonRpcTransport(call_results=call_results)
    client = McpClient(transport)
    merged_config = config if config is not None else {"database_id": "db1"}
    return NotionAdapter(merged_config, client=client), transport


def test_fetch_tasks_maps_chinese_properties():
    rows = [
        _page("p1", "高数作业1", deadline="2026-08-20", course="高等数学", status="进行中"),
        _page("p2", "英语作文", deadline="2026-08-25", status="已完成"),
    ]
    adapter, transport = _make_adapter(
        {"query_database": {"structuredContent": {"results": rows}}}
    )
    tasks = adapter.fetch_tasks()
    assert len(tasks) == 2

    t1 = tasks[0]
    assert t1.title == "高数作业1"
    assert t1.source_ref == "p1"
    assert t1.deadline == "2026-08-20"
    assert t1.course_name == "高等数学"
    assert t1.status == "doing"  # 进行中 → doing

    t2 = tasks[1]
    assert t2.course_name is None
    assert t2.status == "done"  # 已完成 → done
    # 调用参数包含 database_id 与 page_size
    _, params = transport.calls[-1]
    assert params["name"] == "query_database"
    assert params["arguments"]["database_id"] == "db1"


def test_fetch_tasks_status_normalization():
    rows = [_page("p1", "任务A", status="已取消"), _page("p2", "任务B", status="随便写")]
    adapter, _ = _make_adapter({"query_database": {"structuredContent": {"results": rows}}})
    tasks = adapter.fetch_tasks()
    assert tasks[0].status == "cancelled"
    assert tasks[1].status == "todo"  # 未知状态 → 兜底 todo（tasks.status CHECK 约束）


def test_fetch_tasks_parses_text_json_fallback():
    """服务器只返回 content 文本 JSON（无 structuredContent）时也能解析。"""
    rows = [_page("p1", "任务A", deadline="2026-08-20")]
    adapter, _ = _make_adapter(
        {"query_database": {"content": [{"type": "text", "text": json.dumps({"results": rows})}]}}
    )
    tasks = adapter.fetch_tasks()
    assert tasks[0].title == "任务A"
    assert tasks[0].deadline == "2026-08-20"


def test_fetch_tasks_missing_database_id():
    adapter, _ = _make_adapter({}, config={})
    with pytest.raises(ValueError, match="database_id"):
        adapter.fetch_tasks()


def test_search_and_fetch_page():
    rows = [_page("p1", "高数笔记")]
    adapter, transport = _make_adapter(
        {
            "search": {"structuredContent": {"results": rows}},
            "retrieve_page": {"structuredContent": rows[0]},
        }
    )
    pages = adapter.search("高数")
    assert pages[0]["id"] == "p1"
    page = adapter.fetch_page("p1")
    assert page["structuredContent"]["id"] == "p1"  # 返回 MCP 原始结果信封


def test_custom_property_names():
    """config.props 可覆盖默认属性名（适配个人化 Notion 数据库）。"""
    page = {
        "id": "p1",
        "properties": {
            "任务内容": {"rich_text": [{"plain_text": "自定义标题"}]},
            "交作业时间": {"date": {"start": "2026-09-01"}},
            "所属科目": {"select": {"name": "线代"}},
        },
    }
    config = {
        "database_id": "db1",
        "props": {
            "title": ["任务内容"],
            "deadline": ["交作业时间"],
            "course": ["所属科目"],
        },
    }
    adapter, _ = _make_adapter({"query_database": {"structuredContent": {"results": [page]}}}, config)
    task = adapter.fetch_tasks()[0]
    assert task.title == "自定义标题"
    assert task.deadline == "2026-09-01"
    assert task.course_name == "线代"
