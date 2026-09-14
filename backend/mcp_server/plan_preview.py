"""计划预览：plan_items（或 Notion 日历回退）→ 微信友好文本。

格式：按时间顺序一整天时间轴，计划项与画像固定作息混排（作息行加 ☀️），
不再按「课程/任务/复习/杂项」分组。

晚间小结（`evening_digest=True`，Issue #91）：21:00 的**次日**计划推送里，
额外附带「明天有没有 DDL」与「今天安排的任务是否完成」的回顾询问。
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend.models import CourseSession, PlanItem, PlanVersion, Task
from backend.mcp_server import profile_store
from backend.mcp_server._common import shanghai_today
from backend.mcp_server.plan_lifecycle import _latest_version

_WEEKDAY_CN = "一二三四五六日"

# 晚间回顾只关心「今天该做但没做完」的安排；课程是去上课，不算待办
_DIGEST_ITEM_TYPES = ("task", "review", "misc")
# 已了结的状态：done 已完成、skipped 已主动跳过（都不该再追问）
_CLOSED_STATUSES = ("done", "skipped")
# DDL 只提醒还没了结的任务
_OPEN_TASK_STATUSES = ("todo", "doing")


def _latest_version_safe(db: Session, iso: str) -> int | None:
    return _latest_version(db, iso)


def _preview_from_notion(db: Session, plan_date: date) -> list[str]:
    """本地无计划时，回退读取 Notion 日历当天事件（与用户日历所见一致）。

    未绑定 Notion / 未配置日历库 / 查询失败 → 返回空列表（预览回落"无安排"文案）。
    """
    try:
        from backend.mcp_server.notion_calendar import build_writer

        writer = build_writer(db)
        if writer is None:
            return []
        events = writer.list_events_on(plan_date.isoformat())
        if not events:
            return []
        lines: list[str] = []
        for ev in events:
            start = ev["start"]
            hm = start[11:16] if len(start) >= 16 and start[10] == "T" else start
            lines.append(f"{hm} {ev['title']}")
        return lines
    except Exception:
        # 回退路径任何异常都不应影响预览（宁可显示"无安排"）
        return []


def _routine_rows(db: Session, plan_date: date) -> list[tuple[str, str, bool]]:
    """当日生效的固定作息（画像 fixed_activities）→ (start, end title, is_routine) 行。

    与计划项混排进同一条时间轴；is_routine=True 时行首加 ☀️。
    任何异常都不影响预览。
    """
    try:
        profile = profile_store.get_profile(db)
        weekday_cn = _WEEKDAY_CN[plan_date.weekday()]
        acts = [
            a
            for a in profile.get("fixed_activities") or []
            if a.get("days") == "每天" or weekday_cn in (a.get("days") or "")
        ]
        return [
            (a["start"], f"☀️ {a['start']}-{a['end']} {a['title']}", True)
            for a in acts
        ]
    except Exception:  # noqa: BLE001 —— 预览宁可少一行，也不能崩
        return []


def _date_label(plan_date: date) -> str:
    """计划标题：当天→今日计划，次日→明日计划。

    21:00 推的是**次日**计划，此前一律写成「今日计划」，这里按日期纠正。
    其余日期沿用「今日计划」，以免影响既有的手动查询输出格式。
    """
    today = shanghai_today()
    if plan_date == today + timedelta(days=1):
        return "明日计划"
    return "今日计划"


def _closing_hint(plan_date: date) -> str:
    """结尾操作提示：次日计划通常已自动确认，措辞与当天不同。"""
    if plan_date == shanghai_today() + timedelta(days=1):
        return "💬 想调整明天的安排，可说「把 XXX 挪到 HH:MM」。"
    return "💬 回复「确认今天的计划」；调整可说「把 XXX 挪到 HH:MM」。"


def _pending_items_today(db: Session, today: date) -> list[str]:
    """当天尚未了结的 task / review / misc 计划项 → 「HH:MM 标题」列表。"""
    rows = (
        db.query(PlanItem)
        .filter(
            PlanItem.date == today.isoformat(),
            PlanItem.item_type.in_(_DIGEST_ITEM_TYPES),
            PlanItem.status.notin_(_CLOSED_STATUSES),
        )
        .order_by(PlanItem.start_time)
        .all()
    )
    return [f"{it.start_time} {it.title}" for it in rows]


def _evening_digest_lines(db: Session, target_date: date) -> list[str]:
    """晚间小结：次日 DDL 提醒 + 当天任务完成情况回顾（Issue #91）。

    ``target_date`` 是被预览的那一天（晚间推送里 = 明天）。
    """
    lines = ["", "———— 晚间小结 ————"]

    ddl = (
        db.query(Task)
        .filter(
            Task.deadline == target_date.isoformat(),
            Task.status.in_(_OPEN_TASK_STATUSES),
        )
        .order_by(Task.id)
        .all()
    )
    if ddl:
        lines.append(f"📌 明天有 {len(ddl)} 个 DDL：" + "、".join(t.title for t in ddl))
    else:
        lines.append("📌 明天没有 DDL。")

    pending = _pending_items_today(db, shanghai_today())
    if pending:
        lines.append("❓ 今天安排的任务都完成了吗？还没完成的有：")
        lines.extend(f"　· {p}" for p in pending)
        lines.append("　回复「都完成了」，或告诉我哪项没做完。")
    else:
        lines.append("❓ 今天安排的任务都完成了吗？")
    return lines


def preview_plan_text(db: Session, plan_date: date, *, evening_digest: bool = False) -> str:
    """今日/某日计划 → 微信友好文本（供晨间 / 晚间推送）。

    ``evening_digest=True`` 时在末尾追加「晚间小结」（次日 DDL + 当天任务回顾），
    供 21:00 的次日计划推送使用；09:00 晨间推送传默认值，输出保持原样。
    """
    text = _preview_body(db, plan_date)
    if not evening_digest:
        return text
    return "\n".join([text, *_evening_digest_lines(db, plan_date)])


def _preview_body(db: Session, plan_date: date) -> str:
    """计划正文：时间轴 + 状态行 + 操作提示（不含晚间小结）。

    时间轴格式：计划项与固定作息按开始时间混排，一整天一目了然。
    """
    iso = plan_date.isoformat()
    items = (
        db.query(PlanItem)
        .filter(PlanItem.date == iso)
        .order_by(PlanItem.start_time, PlanItem.item_type)
        .all()
    )
    weekday_cn = _WEEKDAY_CN[plan_date.weekday()]

    lines = [f"📅 {_date_label(plan_date)} · {iso} 周{weekday_cn}"]

    if not items:
        lines.append("")
        notion_events = _preview_from_notion(db, plan_date)
        if notion_events:
            lines.append("（本地暂无计划，以下为 Notion 日历中的安排）")
            lines.extend(notion_events)
            lines.append("")
            lines.append("💬 想重新规划这一天？回复「生成明天的计划」。")
            return "\n".join(lines)
        lines.append("今天还没有安排。可以回复「生成明天的计划」，或去网页端手动添加。")
        return "\n".join(lines)

    # 状态行：全部 confirmed/done → 已确认；存在 draft/adjusted → 待确认
    open_items = [it for it in items if it.status in ("draft", "adjusted")]
    if open_items:
        lines.append("⏳ 待确认")
    else:
        version = _latest_version_safe(db, iso)
        lines.append("✅ 已确认" + (f" v{version}" if version else ""))

    lines.append("")

    # 计划项行（课程附教室）+ 作息行，按开始时间混排成一条时间轴
    rows: list[tuple[str, str]] = []
    for it in items:
        location = ""
        if it.item_type == "course" and it.ref_id:
            session = db.get(CourseSession, it.ref_id)
            if session and session.location:
                location = f" · {session.location}"
        rows.append((it.start_time, f"{it.start_time}-{it.end_time} {it.title}{location}"))
    for start, text, _is_routine in _routine_rows(db, plan_date):
        rows.append((start, text))
    rows.sort(key=lambda r: r[0])

    lines.extend(text for _start, text in rows)

    lines.append("")
    lines.append(_closing_hint(plan_date))
    return "\n".join(lines)
