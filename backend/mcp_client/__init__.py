"""MCP 数据接入层。

统一通过 MCP 协议接入外部数据（docs/architecture.md 2.2）：
- Notion（官方远程 MCP Server，mcp.notion.com/mcp，OAuth）
- Obsidian（obsidian-mcp-server，stdio JSON-RPC）
- 课表（教务系统导出 iCal，或手动维护兜底）

新增数据源 = 新增 adapter，不改核心逻辑。
adapter 产出纯数据结构（见 ``models.py``），落库由 ``service.py`` 负责。
"""
from backend.mcp_client.models import CourseSessionItem, NoteItem, SyncResult, TaskItem
from backend.mcp_client.ical import IcalAdapter
from backend.mcp_client.notion import NotionAdapter
from backend.mcp_client.obsidian import ObsidianAdapter
from backend.mcp_client.service import (
    SyncAuthError,
    SyncError,
    build_adapter,
    build_oauth_client,
    sync_data_source,
)

__all__ = [
    "TaskItem",
    "NoteItem",
    "CourseSessionItem",
    "SyncResult",
    "IcalAdapter",
    "NotionAdapter",
    "ObsidianAdapter",
    "SyncError",
    "SyncAuthError",
    "build_adapter",
    "build_oauth_client",
    "sync_data_source",
]
