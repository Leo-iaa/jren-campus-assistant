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
#: 晨间推送任务 id
MORNING_PUSH_JOB_ID = "morning_plan_push"

_scheduler: BackgroundScheduler | None = None


def _parse_hhmm(value: str, *, default: tuple[int, int], label: str) -> tuple[int, int]:
    """解析 'HH:MM' → (hour, minute)；非法回退默认并告警。"""
    hour_s, _sep, minute_s = value.partition(":")
    try:
        hour, minute = int(hour_s), int(minute_s or "0")
    except ValueError:
        hour, minute = default
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        logger.warning(
            "%s 非法（应为 HH:MM）：%r，使用默认 %02d:%02d", label, value, *default
        )
        return default
    return hour, minute


def _parse_generate_time(value: str) -> tuple[int, int]:
    """计划生成时间（默认 21:00）。"""
    return _parse_hhmm(value, default=(21, 0), label="mcp_plan_generate_time")


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
    push_hour, push_minute = _parse_hhmm(
        settings.mcp_morning_push_time,
        default=(9, 35),
        label="mcp_morning_push_time",
    )
    evening_hour, evening_minute = _parse_hhmm(
        settings.mcp_evening_push_time,
        default=(21, 5),
        label="mcp_evening_push_time",
    )
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(
        generate_tomorrow_plan_job,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Shanghai"),
        id=JOB_ID,
        replace_existing=True,
        # 电脑休眠错过触发点后 1 小时内补跑（兜底更稳）
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        morning_push_job,
        CronTrigger(hour=push_hour, minute=push_minute, timezone="Asia/Shanghai"),
        id=MORNING_PUSH_JOB_ID,
        replace_existing=True,
        # 开机晚于 09:35 时（重启后端即触发补跑）也能补上当日推送
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        evening_push_job,
        CronTrigger(
            hour=evening_hour, minute=evening_minute, timezone="Asia/Shanghai"
        ),
        id=EVENING_PUSH_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info(
        "MCP 定时任务已启动：每天 %02d:%02d 生成次日计划、%02d:%02d 晨间推送、"
        "%02d:%02d 晚间推送（Asia/Shanghai）",
        hour,
        minute,
        push_hour,
        push_minute,
        evening_hour,
        evening_minute,
    )
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
        # 晚间推送补偿：已到晚间推送点且当天未推过 → 补推（evening_push_job 幂等，
        # 已推过 / 未到时间都会安全返回；morning_push_job 09:35 调进来时不会触发）
        evening_due = _parse_hhmm(
            settings.mcp_evening_push_time,
            default=(21, 5),
            label="mcp_evening_push_time",
        )
        if (now.hour, now.minute) >= evening_due:
            evening_push_job(now)
    except Exception:  # noqa: BLE001 —— 启动补偿失败不阻断后端启动
        logger.exception("启动补偿执行失败（today=%s）", today.isoformat())


# ---------- 晨间推送（后端兜底通道） ----------
#
# 背景（2026-09-06）：WorkBuddy 应用内调度器在「开机后很快到触发点」场景下
# 定时器未挂上（09:30 触发器整点未响、无任何日志），21:00 这类应用已运行
# 数小时的触发点则一直正常。晨间推送改由后端自己承担：只要后端进程在运行
# （看门狗 + 开机自启保证），当天 09:35 必有推送；后端重启时 misfire 补跑
# （1 小时宽限）进一步兜底。

#: settings 表里「当日已推送」标记的 key（value = 推送日期 ISO 字符串）
MORNING_PUSH_MARK_KEY = "morning_push_done"
#: 晚间推送（次日计划 preview）的 job id 与防重标记
EVENING_PUSH_JOB_ID = "evening_plan_push"
EVENING_PUSH_MARK_KEY = "evening_push_done"


def _push_text_via_cli(text: str) -> tuple[bool, str]:
    """调用 wechat-clawbot-push CLI 推送文本（--test 模式即发送）。

    与 WorkBuddy 的 wechat-clawbot-push 连接器共用同一份 token 缓存
    （~/.workbuddy/wechat-clawbot-push/push_cache.json）。
    返回 (是否成功, 详情)。可被测试替换。
    """
    import subprocess

    cmd = settings.mcp_wechat_push_cmd
    if not cmd:
        return False, "未配置 JREN_MCP_WECHAT_PUSH_CMD，推送关闭"
    try:
        proc = subprocess.run(
            [cmd, "--test", text],
            capture_output=True,
            timeout=90,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"推送 CLI 调用失败：{exc}"
    # 注意：CLI 发送失败时退出码也是 0（cmd_test 只 print 不设 exit code），
    # 只能按输出内容判断：成功会打 "HTTP 200 | 发送成功" + "[OK] 已主动推送"
    out = (proc.stdout or "")
    if "发送成功" in out or "[OK]" in out:
        return True, out.strip()
    detail = out.strip() or (proc.stderr or "").strip() or f"returncode={proc.returncode}"
    if "失效" in detail or "尚未获取 token" in detail or "TOKEN_EXPIRED" in detail:
        detail += (
            "（token 失效：在 WorkBuddy 会话调用 acquire_token 并用手机给 bot "
            "发一条消息即可刷新；本任务不自动重试）"
        )
    return False, detail


def morning_push_job(now: datetime | None = None) -> None:
    """每天晨间把今日计划推送到微信（幂等，异常仅记日志）。

    1) settings 表防重：当天已推送直接返回（后端重启 misfire 补跑 / 与其他
       通道双发时不会重复推）
    2) 复用 run_startup_catchup 确保今日计划存在（21:00 前补生成 + 幂等确认）
    3) preview_plan_text 取推送文本（本地无计划自动回退 Notion 日历）
    4) clawbot CLI 推送，成功后才写当日标记
    """
    from backend.database import SessionLocal
    from backend.models import Setting
    from backend.mcp_server.service import preview_plan_text, shanghai_today

    now = now or datetime.now(_SHANGHAI)
    today = shanghai_today()
    try:
        with SessionLocal() as db:
            mark = (
                db.query(Setting)
                .filter(Setting.key == MORNING_PUSH_MARK_KEY)
                .first()
            )
            if mark is not None and mark.value == today.isoformat():
                logger.info("晨间推送：今天（%s）已推送过，跳过", today.isoformat())
                return
        # 确保今日计划存在（空计划 + 早于 20:00 会补生成并确认；已有计划则无操作）
        run_startup_catchup(now)
        with SessionLocal() as db:
            text = preview_plan_text(db, today)
        ok, detail = _push_text_via_cli(text)
        if not ok:
            logger.warning("晨间推送失败（date=%s）：%s", today.isoformat(), detail)
            return
        with SessionLocal() as db:
            mark = (
                db.query(Setting)
                .filter(Setting.key == MORNING_PUSH_MARK_KEY)
                .first()
            )
            if mark is None:
                mark = Setting(key=MORNING_PUSH_MARK_KEY, value="")
                db.add(mark)
            mark.value = today.isoformat()
            db.commit()
        logger.info("晨间推送完成：date=%s detail=%s", today.isoformat(), detail)
    except Exception:  # noqa: BLE001 —— 定时任务不允许崩溃
        logger.exception("晨间推送任务失败（date=%s）", today.isoformat())


def evening_push_job(now: datetime | None = None) -> None:
    """每天晚间把次日计划 preview 推送到微信（幂等，异常仅记日志）。

    21:00 生成任务之后几分钟运行。与晨间推送同构：
    1) settings 表防重（evening_push_done = 推送日 ISO 字符串）
    2) 调 generate_tomorrow_plan_job 确保次日计划已生成（has_confirmed 保护，
       已确认的日期不会重排，幂等）
    3) preview_plan_text(db, tomorrow) 取推送文本
    4) clawbot CLI 推送，成功后才写当日标记
    """
    from backend.database import SessionLocal
    from backend.models import Setting
    from backend.mcp_server.service import (
        preview_plan_text,
        shanghai_today,
        tomorrow,
    )

    now = now or datetime.now(_SHANGHAI)
    today = shanghai_today()
    try:
        with SessionLocal() as db:
            mark = (
                db.query(Setting)
                .filter(Setting.key == EVENING_PUSH_MARK_KEY)
                .first()
            )
            if mark is not None and mark.value == today.isoformat():
                logger.info("晚间推送：今天（%s）已推送过，跳过", today.isoformat())
                return
        # 确保次日计划已生成并确认（幂等；Tonight 21:00 job 通常已完成）
        generate_tomorrow_plan_job()
        plan_date = tomorrow()
        with SessionLocal() as db:
            text = preview_plan_text(db, plan_date)
        ok, detail = _push_text_via_cli(text)
        if not ok:
            logger.warning(
                "晚间推送失败（date=%s）：%s", plan_date.isoformat(), detail
            )
            return
        with SessionLocal() as db:
            mark = (
                db.query(Setting)
                .filter(Setting.key == EVENING_PUSH_MARK_KEY)
                .first()
            )
            if mark is None:
                mark = Setting(key=EVENING_PUSH_MARK_KEY, value="")
                db.add(mark)
            mark.value = today.isoformat()
            db.commit()
        logger.info(
            "晚间推送完成：plan_date=%s detail=%s", plan_date.isoformat(), detail
        )
    except Exception:  # noqa: BLE001 —— 定时任务不允许崩溃
        logger.exception("晚间推送任务失败（date=%s）", today.isoformat())
