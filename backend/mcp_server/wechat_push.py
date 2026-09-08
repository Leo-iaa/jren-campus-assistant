"""微信推送（后端兜底通道）：今日计划 / 次日计划 → clawbot CLI → 微信。

背景（2026-09-06）：WorkBuddy 应用内调度器在「开机后很快到触发点」场景下
定时器未挂上（09:30 触发器整点未响、无任何日志），21:00 这类应用已运行
数小时的触发点则一直正常。推送改由后端自己承担：只要后端进程在运行
（看门狗 + 开机自启保证），触发点必有推送；后端重启时 misfire 补跑
（1 小时宽限）进一步兜底。

幂等：settings 表记「当日已推送」标记（``morning_push_done`` /
``evening_push_done`` = 推送日 ISO 字符串），重启补跑 / 双通道不会重复推。
"""
from __future__ import annotations

import logging
from datetime import datetime

from backend.config import settings

logger = logging.getLogger("uvicorn.error")

#: settings 表里「当日已推送」标记的 key（value = 推送日期 ISO 字符串）
MORNING_PUSH_MARK_KEY = "morning_push_done"
EVENING_PUSH_MARK_KEY = "evening_push_done"

#: token 失效的输出特征（CLI 发送失败时退出码也是 0，只能按输出判断）
_TOKEN_EXPIRED_MARKS = ("失效", "尚未获取 token", "TOKEN_EXPIRED", "ret -2", "errcode -14")
_TOKEN_HINT = (
    "（token 失效：在 WorkBuddy 会话调用 acquire_token 并用手机给 bot "
    "发一条消息即可刷新；注意刷新后约 1 分钟内推送可能仍报 prepare failed，"
    "稍等再推；本任务不自动重试）"
)


def push_text_via_cli(text: str) -> tuple[bool, str]:
    """调用 wechat-clawbot-push CLI 推送文本（--test 模式即发送）。

    与 WorkBuddy 的 wechat-clawbot-push 连接器共用同一份 token 缓存
    （~/.workbuddy/wechat-clawbot-push/push_cache.json）。
    返回 (是否成功, 详情)。可被测试替换。

    注意：后端以 SYSTEM 运行时必须给子进程注入 ``mcp_wechat_push_home``
    作为 USERPROFILE/HOME，否则 CLI 的 expanduser("~") 解析到
    systemprofile 目录，报「找不到 settings.json」（2026-09-07 实测）。
    """
    import os
    import subprocess

    cmd = settings.mcp_wechat_push_cmd
    if not cmd:
        return False, "未配置 JREN_MCP_WECHAT_PUSH_CMD，推送关闭"
    env = None
    if settings.mcp_wechat_push_home:
        env = {
            **os.environ,
            "USERPROFILE": settings.mcp_wechat_push_home,
            "HOME": settings.mcp_wechat_push_home,
        }
    try:
        proc = subprocess.run(
            [cmd, "--test", text],
            capture_output=True,
            timeout=90,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"推送 CLI 调用失败：{exc}"
    # 成功输出："HTTP 200 | 发送成功" + "[OK] 已主动推送"
    out = proc.stdout or ""
    if "发送成功" in out or "[OK]" in out:
        return True, out.strip()
    detail = out.strip() or (proc.stderr or "").strip() or f"returncode={proc.returncode}"
    if any(mark in detail for mark in _TOKEN_EXPIRED_MARKS):
        detail += _TOKEN_HINT
    return False, detail


def _already_pushed(mark_key: str, today_iso: str) -> bool:
    """当天是否已推送过（settings 表标记）。"""
    from backend.database import SessionLocal
    from backend.models import Setting

    with SessionLocal() as db:
        mark = db.query(Setting).filter(Setting.key == mark_key).first()
        return mark is not None and mark.value == today_iso


def _mark_pushed(mark_key: str, today_iso: str) -> None:
    """写「当日已推送」标记。"""
    from backend.database import SessionLocal
    from backend.models import Setting

    with SessionLocal() as db:
        mark = db.query(Setting).filter(Setting.key == mark_key).first()
        if mark is None:
            mark = Setting(key=mark_key, value="")
            db.add(mark)
        mark.value = today_iso
        db.commit()


def _push_plan_text(text: str, mark_key: str, today_iso: str, label: str, log_date: str) -> None:
    """推送 + 成功后写标记（三个 job 共用的尾部流程）。"""
    ok, detail = push_text_via_cli(text)
    if not ok:
        logger.warning("%s失败（date=%s）：%s", label, log_date, detail)
        return
    _mark_pushed(mark_key, today_iso)
    logger.info("%s完成：date=%s detail=%s", label, log_date, detail)


def morning_push_job(now: datetime | None = None, *, _skip_catchup: bool = False) -> None:
    """每天晨间把今日计划推送到微信（幂等，异常仅记日志）。

    1) settings 表防重：当天已推送直接返回
    2) 复用 run_startup_catchup 确保今日计划存在（``_skip_catchup=True``
       仅供 run_startup_catchup 的晨间补偿分支使用，防止互相递归）
    3) preview_plan_text 取推送文本（本地无计划自动回退 Notion 日历）
    4) clawbot CLI 推送，成功后才写当日标记
    """
    from backend.database import SessionLocal
    from backend.mcp_server.plan_preview import preview_plan_text
    from backend.mcp_server.scheduler_jobs import run_startup_catchup
    from backend.mcp_server._common import shanghai_today

    now = now or datetime.now(_SHANGHAI)
    today = shanghai_today()
    today_iso = today.isoformat()
    try:
        if _already_pushed(MORNING_PUSH_MARK_KEY, today_iso):
            logger.info("晨间推送：今天（%s）已推送过，跳过", today_iso)
            return
        # 确保今日计划存在（空计划 + 早于 20:00 会补生成并确认；已有计划则无操作）。
        # _skip_morning_push=True：本任务自己就是晨间推送，补偿链路不应再触发
        # 晨间补偿（否则会与本任务重复推送 / 失败时重复尝试）
        if not _skip_catchup:
            run_startup_catchup(now, _skip_morning_push=True)
        with SessionLocal() as db:
            text = preview_plan_text(db, today)
        _push_plan_text(text, MORNING_PUSH_MARK_KEY, today_iso, "晨间推送", today_iso)
    except Exception:  # noqa: BLE001 —— 定时任务不允许崩溃
        logger.exception("晨间推送任务失败（date=%s）", today_iso)


def evening_push_job(now: datetime | None = None) -> None:
    """每天晚间把次日计划 preview 推送到微信（幂等，异常仅记日志）。

    21:00 生成任务之后几分钟运行。与晨间推送同构：
    1) settings 表防重
    2) 调 generate_tomorrow_plan_job 确保次日计划已生成（has_confirmed 保护，
       已确认的日期不会重排，幂等）
    3) preview_plan_text(db, tomorrow) 取推送文本
    4) clawbot CLI 推送，成功后才写当日标记
    """
    from backend.mcp_server._common import shanghai_today, tomorrow
    from backend.mcp_server.plan_preview import preview_plan_text
    from backend.mcp_server.scheduler_jobs import generate_tomorrow_plan_job

    now = now or datetime.now(_SHANGHAI)
    today = shanghai_today()
    today_iso = today.isoformat()
    try:
        if _already_pushed(EVENING_PUSH_MARK_KEY, today_iso):
            logger.info("晚间推送：今天（%s）已推送过，跳过", today_iso)
            return
        # 确保次日计划已生成并确认（幂等；今晚 21:00 job 通常已完成）
        generate_tomorrow_plan_job()
        plan_date = tomorrow()
        from backend.database import SessionLocal

        with SessionLocal() as db:
            text = preview_plan_text(db, plan_date)
        _push_plan_text(text, EVENING_PUSH_MARK_KEY, today_iso, "晚间推送", plan_date.isoformat())
    except Exception:  # noqa: BLE001 —— 定时任务不允许崩溃
        logger.exception("晚间推送任务失败（date=%s）", today_iso)
