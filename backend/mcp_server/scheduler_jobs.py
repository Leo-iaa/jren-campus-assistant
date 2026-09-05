"""APScheduler 定时任务：每天 21:00 自动生成次日计划并直达日历（后端兜底）。

设计依据 docs/vision.md「提醒链路（方案 A）」：WorkBuddy 的 21:00 定时任务是
主通道；本模块保证即使 WorkBuddy 未触发 / 未配置，只要后端进程在运行，
次日计划也会在每晚定时生成 **并自动确认写入 Notion 日历**（auto_confirm，
2026-08-31 起：原草案模式连续两晚因确认环节断链导致日历无写入）。

- 触发时间：``JREN_MCP_PLAN_GENERATE_TIME``（默认 21:00，HH:MM，Asia/Shanghai）
- 开关：``JREN_MCP_SCHEDULER_ENABLED``（默认 true；测试 / 开发可关闭）
- 任务体：generate_plan → confirm_plan（含 Notion 日历写入），结果记日志
- 幂等：generate_plan 对已有 confirmed 项的日期自动跳过重排（has_confirmed 保护），
  confirm_plan 写日历按 (日期, 时段) 幂等去重（created/updated/unchanged）
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

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


def _build_writer_safe(db):
    """构造 Notion 日历 writer；未绑定/配置异常返回 (None, error)。可被测试替换。"""
    from backend.mcp_server.notion_calendar import NotionCalendarError, build_writer

    try:
        return build_writer(db), None
    except NotionCalendarError as exc:
        return None, str(exc)


def generate_tomorrow_plan_job() -> None:
    """定时任务体：生成次日计划并自动确认写入 Notion 日历（异常仅记日志，不中断调度器）。"""
    from backend.database import SessionLocal
    from backend.mcp_server.service import confirm_plan, generate_plan, tomorrow

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
            # auto_confirm：生成后立即确认并写入 Notion 日历（与 MCP 工具
            # generate_tomorrow_plan(auto_confirm=true) 完全同路径）
            writer, notion_error = _build_writer_safe(db)
            confirmed = confirm_plan(db, plan_date, calendar_writer=writer)
            sync = confirmed.notion_sync
            if notion_error and sync is None:
                sync = {"error": notion_error}
            logger.info(
                "定时确认次日计划完成：date=%s confirmed=%d version=%s notion_sync=%s",
                plan_date.isoformat(),
                confirmed.confirmed_count,
                # confirm_plan 无可确认项时 version 为 None，%d 会触发 Logging error
                # （空计划必现，#78）；%s 原样输出 None
                confirmed.version,
                json.dumps(sync, ensure_ascii=False) if sync else "null",
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


# ---------- 启动补偿 ----------

#: 当天晚于此时刻不再补生成今日计划（临近午夜补一份当日计划没有意义）
CATCHUP_TODAY_CUTOFF_HOUR = 20


def run_startup_catchup(now: datetime | None = None) -> None:
    """后端启动补偿：电脑关机/休眠错过定时点时，开机后补齐计划缺口。

    与定时 job 共用同一套 service 层，幂等保证：
    - generate_plan 对已有 confirmed 项的日期自动跳过重排（has_confirmed 保护）
    - confirm_plan 写日历按 (日期, 时段) 幂等去重（created/updated/unchanged）

    补偿规则：
    - 今天无任何计划项且早于 ``CATCHUP_TODAY_CUTOFF_HOUR`` 点
      → 生成并确认今日计划（auto_confirm 路径，与定时 job 完全同款）
    - 已过生成时间（``JREN_MCP_PLAN_GENERATE_TIME``，默认 21:00）
      且明天尚无已确认计划 → 补跑一次 ``generate_tomorrow_plan_job``

    异常仅记日志，不阻断后端启动；本函数只执行一次，不注册任何调度任务。
    ``now`` 参数仅供测试注入时钟。
    """
    from backend.database import SessionLocal
    from backend.models import PlanItem
    from backend.mcp_server.service import (
        confirm_plan,
        generate_plan,
        tomorrow as service_tomorrow,
    )

    now = now or datetime.now(_SHANGHAI)
    today = now.date()
    try:
        with SessionLocal() as db:
            # a) 今日计划缺口：空计划 + 未过截断时刻 → 生成并确认今天
            today_iso = today.isoformat()
            has_today = db.query(PlanItem.id).filter(PlanItem.date == today_iso).first()
            if has_today is None and now.hour < CATCHUP_TODAY_CUTOFF_HOUR:
                result = generate_plan(db, today)
                writer, notion_error = _build_writer_safe(db)
                confirmed = confirm_plan(db, today, calendar_writer=writer)
                sync = confirmed.notion_sync
                if notion_error and sync is None:
                    sync = {"error": notion_error}
                logger.info(
                    "启动补偿：已补生成并确认今日计划 date=%s placed=%d confirmed=%d version=%s",
                    today_iso,
                    result.placed_count,
                    confirmed.confirmed_count,
                    confirmed.version,
                )
                if result.dropped or result.skipped:
                    logger.warning(
                        "启动补偿（今日）有未放置/跳过项：dropped=%s skipped=%s",
                        result.dropped,
                        result.skipped,
                    )
            elif has_today is None:
                logger.info(
                    "启动补偿：今天无计划但已过 %02d:00，跳过今日补生成",
                    CATCHUP_TODAY_CUTOFF_HOUR,
                )

            # b) 次日计划缺口：已过生成时刻 + 明天无已确认项 → 补跑定时 job
            gen_hour, gen_minute = _parse_generate_time(settings.mcp_plan_generate_time)
            if (now.hour, now.minute) >= (gen_hour, gen_minute):
                tomorrow_date = service_tomorrow()
                has_tomorrow_confirmed = (
                    db.query(PlanItem.id)
                    .filter(
                        PlanItem.date == tomorrow_date.isoformat(),
                        PlanItem.status == "confirmed",
                    )
                    .first()
                )
                if has_tomorrow_confirmed is None:
                    logger.info(
                        "启动补偿：已过 %02d:%02d 且次日计划未确认，补跑次日生成任务",
                        gen_hour,
                        gen_minute,
                    )
                    generate_tomorrow_plan_job()
                else:
                    logger.info("启动补偿：次日计划已确认（%s），无需补跑", tomorrow_date.isoformat())
    except Exception:  # noqa: BLE001 —— 启动补偿失败不阻断后端启动
        logger.exception("启动补偿执行失败（today=%s）", today.isoformat())
