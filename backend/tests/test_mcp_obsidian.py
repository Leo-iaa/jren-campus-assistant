"""Obsidian adapter 测试：fake MCP 传输层 + vault_path 直读兜底。"""
from __future__ import annotations

import json

import pytest

from backend.mcp_client.obsidian import ObsidianAdapter
from backend.mcp_client.transport import McpClient
from tests.fakes import FakeJsonRpcTransport


def _make_mcp_adapter(call_results: dict, config: dict | None = None) -> ObsidianAdapter:
    client = McpClient(FakeJsonRpcTransport(call_results=call_results))
    return ObsidianAdapter(config or {}, client=client)


def test_search_via_mcp():
    notes = [{"path": "数学/高数.md", "content": "极限的定义：当 n 趋于无穷…"}]
    adapter = _make_mcp_adapter(
        {"search_note": {"content": [{"type": "text", "text": json.dumps(notes)}]}}
    )
    items = adapter.search("极限")
    assert len(items) == 1
    assert items[0].path == "数学/高数.md"
    assert items[0].title == "高数"
    assert "极限" in items[0].excerpt


def test_read_note_via_mcp():
    notes = [{"path": "数学/高数.md", "content": "全文内容"}]
    adapter = _make_mcp_adapter(
        {"read_note": {"content": [{"type": "text", "text": json.dumps(notes)}]}}
    )
    item = adapter.read_note("数学/高数.md")
    assert item.content == "全文内容"


def test_list_notes_via_mcp():
    notes = [{"path": "a.md", "content": "1"}, {"path": "b.md", "content": "2"}]
    adapter = _make_mcp_adapter(
        {"list_all_notes": {"structuredContent": notes}}
    )
    items = adapter.list_notes()
    assert [item.path for item in items] == ["a.md", "b.md"]


# ---------- vault_path 直读兜底 ----------


def _make_vault(tmp_path) -> str:
    vault = tmp_path / "vault"
    (vault / "数学").mkdir(parents=True)
    (vault / "数学" / "高数.md").write_text("# 高数笔记\n极限的定义\n洛必达法则\n", encoding="utf-8")
    (vault / "英语.md").write_text("# 英语\n单词背诵\nAppendix A\n", encoding="utf-8")
    return str(vault)


def test_search_vault_fallback(tmp_path):
    adapter = ObsidianAdapter({"vault_path": _make_vault(tmp_path)})
    items = adapter.search_vault("极限")
    assert len(items) == 1
    assert items[0].title == "高数"
    assert "极限的定义" in items[0].excerpt
    # 不区分大小写
    assert len(adapter.search_vault("appendix")) == 1
    assert len(adapter.search_vault("单词")) == 1


def test_mcp_failure_falls_back_to_vault(tmp_path):
    """MCP 调用失败（如服务器未启动）→ 配置了 vault_path 时直读兜底。"""
    adapter = _make_mcp_adapter({}, config={"vault_path": _make_vault(tmp_path)})
    items = adapter.search("极限")
    assert len(items) == 1
    assert items[0].path == "数学/高数.md"


def test_list_vault_notes(tmp_path):
    adapter = ObsidianAdapter({"vault_path": _make_vault(tmp_path)})
    items = adapter.list_vault_notes()
    assert {item.title for item in items} == {"高数", "英语"}


def test_read_vault_note_and_traversal_guard(tmp_path):
    vault = _make_vault(tmp_path)
    adapter = ObsidianAdapter({"vault_path": vault})
    item = adapter._read_vault_note("数学/高数.md")
    assert item.content == "# 高数笔记\n极限的定义\n洛必达法则\n"
    # 越出 vault 目录 → 拒绝
    with pytest.raises(FileNotFoundError):
        adapter._read_vault_note("../secret.md")


def test_vault_required():
    adapter = ObsidianAdapter({})
    with pytest.raises(ValueError, match="vault_path"):
        adapter.search_vault("x")
