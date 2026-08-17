"""APScheduler 定时任务：每天 21:00 自动生成次日计划（后端兜底）。

设计依据 docs/vision.md「提醒链路（方案 A）」：QClaw 的 21:00 定时任务是
主通道；本模块保证即使 QClaw 未触发 / 未配置，只要后端进程在运行，
次日计划也会在每晚定时生成（草案，等待用户确认）。

- 触发时间：``JREN_MCP_PLAN_GENERATE_TIME``（默认 21:00，HH:MM，Asia/Shanghai）
- 开关：``JREN_MCP_SCHEDULER_ENABLED``（默认 true；测试 / 开发可关闭）
- 任务体只生成草案并记日志；确认与 Notion 日历写入由 confirm_plan 负责
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from backend.config import settings

# 走 uvicorn.error logger：uvicorn 启动时在终端可见（默认不会接管根 logger），
# 便于用户确认「21:00 兜底任务」是否随服务启动
logger = logging.getLogger("uvicorn.error")

_SHANGHAI = ZoneInfo("Asia/Shanghai")

#: 任务 id（幂等注册，replace_existing 防重复）
JOB_ID = "generate_tomorrow_plan"

_scheduler: BackgroundScheduler | None = None


def _parse_generate_time(value: str) -> tuple[int, int]:
    """解析 'HH:MM' → (hour, minute)；非法回退默认 21:00。"""
    hour_s, sep, minute_s = value.partition(":")
    try:
        hour, minute = int(hour_s), int(minute_s or "0")
    except ValueError:
        hour, minute = 21, 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        logger.warning("mcp_plan_generate_time 非法（应为 HH:MM）：%r，使用默认 21:00", value)
        return 21, 0
    return hour, minute


def generate_tomorrow_plan_job() -> None:
    """定时任务体：生成次日计划草案（异常仅记日志，不中断调度器）。"""
    from backend.database import SessionLocal
    from backend.mcp_server.service import generate_plan, tomorrow

    plan_date = tomorrow()
    try:
        with SessionLocal() as db:
            result = generate_plan(db, plan_date)
        logger.info(
            "定时生成次日计划完成：date=%s placed=%d dropped=%d skipped=%d",
            plan_date.isoformat(),
            result.placed_count,
            len(result.dropped),
            len(result.skipped),
        )
        if result.dropped or result.skipped:
            logger.warning(
                "次日计划有未放置/跳过项：dropped=%s skipped=%s",
                result.dropped,
                result.skipped,
            )
    except Exception:  # noqa: BLE001 —— 定时任务不允许崩溃
        logger.exception("定时生成次日计划失败（date=%s）", plan_date.isoformat())


def start_scheduler_if_enabled() -> BackgroundScheduler | None:
    """按配置启动调度器（幂等）。未启用或已启动返回当前实例 / None。"""
    global _scheduler
    if not settings.mcp_scheduler_enabled:
        logger.info("MCP 定时任务未启用（JREN_MCP_SCHEDULER_ENABLED=false）")
        return None
    if _scheduler is not None:
        return _scheduler

    hour, minute = _parse_generate_time(settings.mcp_plan_generate_time)
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(
        generate_tomorrow_plan_job,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Shanghai"),
        id=JOB_ID,
        replace_existing=True,
        # 电脑休眠错过触发点后 1 小时内补跑（兜底更稳）
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info("MCP 定时任务已启动：每天 %02d:%02d 生成次日计划（Asia/Shanghai）", hour, minute)
    return _scheduler


def stop_scheduler() -> None:
    """停止调度器（幂等）。"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("MCP 定时任务已停止")
