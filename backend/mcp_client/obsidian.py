"""Obsidian MCP adapter：对接 obsidian-mcp-server（stdio JSON-RPC）。

- 传输：本地子进程（默认 ``npx obsidian-mcp-server``），JSON-RPC over stdin/stdout
- 工具名可配置（obsidian-mcp-server 常用工具：search_note / read_note / list_all_notes）
- 另提供 ``vault_path`` 直读兜底：不依赖 MCP 服务器时，直接用 pathlib 在本地
  vault 全文搜索 .md 笔记（与 MCP 路径共用同一查询接口）

只做接入与查询接口；知识点提取算法归知识提取模块（本层不落库）。
"""
from __future__ import annotations

from pathlib import Path

from backend.mcp_client.models import NoteItem
from backend.mcp_client.transport import McpClient, StdioTransport, extract_result_items

DEFAULT_COMMAND = ["npx", "obsidian-mcp-server"]
DEFAULT_TOOL_SEARCH = "search_note"
DEFAULT_TOOL_READ = "read_note"
DEFAULT_TOOL_LIST = "list_all_notes"


class ObsidianAdapter:
    """Obsidian 数据接入：vault 全文搜索 / 读笔记 → NoteItem。"""

    def __init__(self, config: dict, client: McpClient | None = None) -> None:
        self.config = config
        self.vault_path = config.get("vault_path")
        self.tool_search = config.get("tool_search", DEFAULT_TOOL_SEARCH)
        self.tool_read = config.get("tool_read", DEFAULT_TOOL_READ)
        self.tool_list = config.get("tool_list", DEFAULT_TOOL_LIST)

        # 惰性创建 stdio 子进程：纯 vault 兜底场景不 spawn
        self._client = client
        self._command = config.get("command") or DEFAULT_COMMAND
        self._cwd = config.get("cwd")

    def _get_client(self) -> McpClient:
        if self._client is None:
            self._client = McpClient(StdioTransport(self._command, cwd=self._cwd))
        return self._client

    # ---------- 查询接口 ----------

    def search(self, query: str, limit: int = 20) -> list[NoteItem]:
        """全文搜索笔记（MCP 优先；配置了 vault_path 且 MCP 不可用时直读兜底）。"""
        if self._client is not None:
            try:
                result = self._get_client().call_tool(self.tool_search, {"query": query})
                items = [self._note_from_dict(d) for d in extract_result_items(result)]
                return items[:limit]
            except Exception:
                if not self.vault_path:
                    raise
        elif self.vault_path:
            pass  # 未注入 client 且配置了 vault_path → 直接走直读
        else:
            raise ValueError("缺少 vault_path：请在数据源 config 中配置 Obsidian vault 路径")
        return self.search_vault(query, limit)

    def read_note(self, path: str) -> NoteItem:
        """读取笔记全文。"""
        if self._client is not None:
            try:
                result = self._get_client().call_tool(self.tool_read, {"path": path})
                items = extract_result_items(result)
                if items:
                    return self._note_from_dict(items[0])
            except Exception:
                if not self.vault_path:
                    raise
        elif self.vault_path:
            pass
        else:
            raise ValueError("缺少 vault_path：请在数据源 config 中配置 Obsidian vault 路径")
        return self._read_vault_note(path)

    def list_notes(self, limit: int = 100) -> list[NoteItem]:
        """列出 vault 全部笔记。"""
        if self._client is not None:
            try:
                result = self._get_client().call_tool(self.tool_list, {})
                items = [self._note_from_dict(d) for d in extract_result_items(result)]
                return items[:limit]
            except Exception:
                if not self.vault_path:
                    raise
        elif self.vault_path:
            pass
        else:
            raise ValueError("缺少 vault_path：请在数据源 config 中配置 Obsidian vault 路径")
        return self.list_vault_notes(limit)

    # ---------- vault_path 直读兜底 ----------

    def search_vault(self, query: str, limit: int = 20) -> list[NoteItem]:
        """本地 vault 全文搜索（不区分大小写，返回命中行片段）。"""
        vault = self._require_vault()
        hits: list[NoteItem] = []
        for path in sorted(vault.rglob("*.md")):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            excerpt = next(
                (line.strip() for line in text.splitlines() if query.lower() in line.lower()),
                "",
            )
            if excerpt:
                hits.append(self._note(vault, path, excerpt=excerpt[:200]))
                if len(hits) >= limit:
                    break
        return hits

    def list_vault_notes(self, limit: int = 100) -> list[NoteItem]:
        vault = self._require_vault()
        notes = []
        for path in sorted(vault.rglob("*.md"))[:limit]:
            notes.append(self._note(vault, path))
        return notes

    def _read_vault_note(self, relative_path: str) -> NoteItem:
        vault = self._require_vault()
        path = (vault / relative_path).resolve()
        if not path.is_file() or vault.resolve() not in path.parents:
            raise FileNotFoundError(f"笔记不存在或越出 vault：{relative_path}")
        return NoteItem(
            path=relative_path.replace("\\", "/"),
            title=path.stem,
            content=path.read_text(encoding="utf-8", errors="replace"),
        )

    def _require_vault(self) -> Path:
        vault = self.vault_path
        if not vault:
            raise ValueError("缺少 vault_path：请在数据源 config 中配置 Obsidian vault 路径")
        path = Path(vault)
        if not path.is_dir():
            raise ValueError(f"vault 路径不存在：{vault}")
        return path

    @staticmethod
    def _note(vault: Path, path: Path, excerpt: str = "") -> NoteItem:
        rel = path.relative_to(vault).as_posix()
        return NoteItem(path=rel, title=path.stem, excerpt=excerpt)

    @staticmethod
    def _note_from_dict(d: dict) -> NoteItem:
        path = str(d.get("path") or d.get("file_name") or d.get("name") or "")
        content = d.get("content")
        if content:
            excerpt = str(content)[:200]
        else:
            excerpt = str(d.get("excerpt") or d.get("snippet") or "")
        title = str(d.get("name") or Path(path).stem or path)
        return NoteItem(path=path, title=title, excerpt=excerpt, content=str(content) if content else None)
