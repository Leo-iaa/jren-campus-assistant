"""MCP 接入层测试的 fake 组件（传输层 / 桩）。

约定：adapter 的传输层可注入（Issue #11），因此测试不需要真实账号，
只需一个按工具名返回预设结果的假 JSON-RPC 传输。
"""
from __future__ import annotations


class FakeJsonRpcTransport:
    """按工具名返回预设结果的假 MCP 传输层，同时记录全部调用。"""

    def __init__(self, call_results: dict[str, dict] | None = None, tools: list[dict] | None = None) -> None:
        self.call_results = call_results or {}
        self.tools = tools or [{"name": "echo", "description": "测试工具"}]
        self.calls: list[tuple[str, dict | None]] = []

    def _post(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        self.calls.append((method, params))
        if method == "initialize":
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "fake-mcp", "version": "1.0"},
            }
        if method == "tools/list":
            return {"tools": self.tools}
        if method == "tools/call":
            name = (params or {}).get("name")
            if name in self.call_results:
                return self.call_results[name]
            raise AssertionError(f"未配置 tools/call 响应：{name}")
        raise AssertionError(f"未实现的方法：{method}")

    def _notify(self, method: str, params: dict | None = None) -> None:
        self.calls.append((method, params))

    def close(self) -> None:
        pass


class FakeNotionRest:
    """按方法返回预设结果的假 Notion REST 客户端，同时记录全部调用。

    与 NotionRestClient 的方法签名一致（query_database / create_page /
    update_page / search / retrieve_page），测试无需真实账号。
    """

    def __init__(
        self,
        query_results: list[dict] | None = None,
        create_result: dict | None = None,
        update_result: dict | None = None,
        database_schema: dict | None = None,
    ) -> None:
        self.query_results = query_results or []
        self.create_result = create_result or {"id": "new-page"}
        self.update_result = update_result or {"id": "updated-page"}
        self.database_schema = database_schema or {"properties": {}}
        self.calls: list[tuple[str, dict]] = []

    def _record(self, method: str, **kwargs) -> None:
        self.calls.append((method, kwargs))

    def query_database(self, database_id: str, filter: dict | None = None, page_size: int = 100) -> list[dict]:
        self._record("query_database", database_id=database_id, filter=filter, page_size=page_size)
        return self.query_results

    def retrieve_database(self, database_id: str) -> dict:
        self._record("retrieve_database", database_id=database_id)
        return self.database_schema

    def create_page(self, parent_database_id: str, properties: dict) -> dict:
        self._record("create_page", parent_database_id=parent_database_id, properties=properties)
        return self.create_result

    def update_page(self, page_id: str, properties: dict) -> dict:
        self._record("update_page", page_id=page_id, properties=properties)
        return self.update_result

    def search(self, query: str = "", filter: dict | None = None, page_size: int = 10) -> list[dict]:
        self._record("search", query=query, filter=filter, page_size=page_size)
        return self.query_results

    def retrieve_page(self, page_id: str) -> dict:
        self._record("retrieve_page", page_id=page_id)
        return {"id": page_id, "properties": {}}

    def close(self) -> None:
        pass


# 模拟教务系统导出课表（WakeUpSchedule 风格，见 Issue #11 用户附件样例）：
# - TZID=Asia/Shanghai + RRULE:FREQ=WEEKLY;UNTIL=...
# - 同一课程拆多个 VEVENT（教师/教室更换）→ 需去重合并
# - 无 LOCATION 时从 DESCRIPTION 兜底取 教室/教师
# - 非每周（DAILY）与无 RRULE 事件应被跳过
SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//YZune//WakeUpSchedule//EN
BEGIN:VTIMEZONE
TZID:Asia/Shanghai
BEGIN:STANDARD
TZNAME:CST
TZOFFSETFROM:+0800
TZOFFSETTO:+0800
DTSTART:19700101T000000
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
DTSTAMP:20260817T143834Z
UID:test-1
SUMMARY:高等数学
DTSTART;TZID=Asia/Shanghai:20260302T080000
DTEND;TZID=Asia/Shanghai:20260302T094000
RRULE:FREQ=WEEKLY;UNTIL=20260621T160000Z;INTERVAL=1
LOCATION:教西A1-101 张三
DESCRIPTION:第1 - 2节\\n教西A1-101\\n张三
END:VEVENT
BEGIN:VEVENT
DTSTAMP:20260817T143834Z
UID:test-2
SUMMARY:高等数学
DTSTART;TZID=Asia/Shanghai:20260504T080000
DTEND;TZID=Asia/Shanghai:20260504T094000
RRULE:FREQ=WEEKLY;UNTIL=20260621T160000Z;INTERVAL=1
LOCATION:教西A1-201 李四
DESCRIPTION:第1 - 2节\\n教西A1-201\\n李四
END:VEVENT
BEGIN:VEVENT
DTSTAMP:20260817T143834Z
UID:test-3
SUMMARY:大学英语
DTSTART;TZID=Asia/Shanghai:20260303T140000
DTEND;TZID=Asia/Shanghai:20260303T154000
RRULE:FREQ=WEEKLY;UNTIL=20260620T160000Z;INTERVAL=1
DESCRIPTION:第7 - 8节\\n教西C2-301\\n王五
END:VEVENT
BEGIN:VEVENT
DTSTAMP:20260817T143834Z
UID:test-4
SUMMARY:临时讲座
DTSTART;TZID=Asia/Shanghai:20260410T140000
DTEND;TZID=Asia/Shanghai:20260410T154000
RRULE:FREQ=DAILY;INTERVAL=1
LOCATION:报告厅
END:VEVENT
BEGIN:VEVENT
DTSTAMP:20260817T143834Z
UID:test-5
SUMMARY:调课单次
DTSTART;TZID=Asia/Shanghai:20260415T140000
DTEND;TZID=Asia/Shanghai:20260415T154000
LOCATION:教东A-101
END:VEVENT
END:VCALENDAR
"""
