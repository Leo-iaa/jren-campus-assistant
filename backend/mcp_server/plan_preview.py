"""计划预览：plan_items（或 Notion 日历回退）→ 微信友好文本。"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from backend.models import CourseSession, PlanItem, PlanVersion
from backend.mcp_server import profile_store
from backend.mcp_server._common import ITEM_TYPE_LABELS
from backend.mcp_server.plan_lifecycle import _latest_version

_WEEKDAY_CN = "一二三四五六日"


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
        emoji = {"course": "📚", "task": "📝", "review": "🔁", "misc": "🧘"}
        lines: list[str] = []
        for ev in events:
            start = ev["start"]
            hm = start[11:16] if len(start) >= 16 and start[10] == "T" else start
            icon = emoji.get(ev["type"], "📌")
            lines.append(f"🕗 {hm} {icon} {ev['title']}")
        return lines
    except Exception:
        # 回退路径任何异常都不应影响预览（宁可显示"无安排"）
        return []


def _routine_lines(db: Session, plan_date: date) -> list[str]:
    """当日生效的固定作息（画像 fixed_activities）→ 预览提示行。

    只展示、不占排程（排程侧由 planner 的 extra_barriers 处理），
    让用户一眼看出计划确实按自己的作息来排。任何异常都不影响预览。
    """
    try:
        profile = profile_store.get_profile(db)
        weekday_cn = _WEEKDAY_CN[plan_date.weekday()]
        acts = [
            a
            for a in profile.get("fixed_activities") or []
            if a.get("days") == "每天" or weekday_cn in (a.get("days") or "")
        ]
        if not acts:
            return []
        acts.sort(key=lambda a: a["start"])
        body = " · ".join(f"{a['start']}-{a['end']} {a['title']}" for a in acts)
        return ["", "🧩 今日作息（固定安排，不占排程）", f"🕗 {body}"]
    except Exception:  # noqa: BLE001 —— 预览宁可少一行，也不能崩
        return []


def preview_plan_text(db: Session, plan_date: date) -> str:
    """今日/某日计划 → 微信友好文本（供晨间 / 晚间推送）。"""
    iso = plan_date.isoformat()
    items = (
        db.query(PlanItem)
        .filter(PlanItem.date == iso)
        .order_by(PlanItem.start_time, PlanItem.item_type)
        .all()
    )
    weekday_cn = _WEEKDAY_CN[plan_date.weekday()]

    lines = [f"📅 今日计划 · {iso} 周{weekday_cn}"]

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

    for item_type in ("course", "task", "review", "misc"):
        group = [it for it in items if it.item_type == item_type]
        if not group:
            continue
        emoji, label = ITEM_TYPE_LABELS[item_type]
        lines.append("")
        lines.append(f"{emoji} {label}（{len(group)}）")
        for it in group:
            location = ""
            if item_type == "course" and it.ref_id:
                session = db.get(CourseSession, it.ref_id)
                if session and session.location:
                    location = f" · {session.location}"
            lines.append(f"🕗 {it.start_time}-{it.end_time} {it.title}{location}")

    lines.extend(_routine_lines(db, plan_date))

    lines.append("")
    lines.append("💬 回复「确认今天的计划」；调整可说「把 XXX 挪到 HH:MM」。")
    return "\n".join(lines)
