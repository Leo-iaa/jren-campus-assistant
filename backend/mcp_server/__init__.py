"""MCP Server 暴露层（WorkBuddy 接入）：server / service / notion_calendar。

- ``service``：计划编排业务（生成 / 预览 / 确认 / 调整 / 完成 / 查询）
- ``notion_calendar``：plan_items 幂等写入 Notion 日程数据库（时段块事件；08:00 提醒由微信推送承担）
- ``server``：MCP 工具定义（Streamable HTTP，挂载 /mcp）

注：v3 起后端不再含定时任务，APScheduler 的 ``scheduler_jobs`` 模块已删除；
21:00 生成 / 09:00 推送均由 WorkBuddy 自动化侧触发。
"""
