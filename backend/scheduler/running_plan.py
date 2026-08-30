"""跑步训练计划规则引擎（纯逻辑，无 FastAPI / 数据库 / MCP 依赖）。

设计依据 Issue #65：
- 输入 ``RunningSnapshot`` 形态的近端跑步数据（跑量 / 配速 / 恢复 / 负荷），
  输出一周可执行训练计划（轻松跑 / 间歇 / 长距离 / 休息），并给出中文理由
- 学生业余跑者定位：强度保守（单周增幅 ≤10%、强度课 ≤2 次/周），不是专业队
- 尊重恢复信号：负荷比过高 / 恢复等级差 → 降量或整周轻松化；
  强度课次日不排强度（连续高强度强制缓冲）
- 输出为纯 dataclass（Plan 由调用方以杂项 misc 身份排进日程），确定性：
  同输入必同输出（规则引擎，无随机、无 LLM）

周结构骨架（对齐常见业余中低跑量训练法，跑量越大频次越多）：
- 3 次/周：轻松 ×2 + 长距离 ×1（间歇隔周轮换，负荷低时不排）
- 4 次/周：轻松 ×2 + 间歇/节奏 ×1 + 长距离 ×1
- 5 次/周：轻松 ×3 + 间歇 + 长距离
- 2 次及以下或恢复差：轻松跑 + 休息为主（减量周）
"""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.mcp_client.coros import RunningActivity, RunningSnapshot

#: 训练类型（workout_kind）与中文标题模板
EASY = "easy"
TEMPO = "tempo"
INTERVAL = "interval"
LONG_RUN = "long_run"
REST = "rest"

_KIND_LABELS: dict[str, str] = {
    EASY: "轻松跑",
    TEMPO: "节奏跑",
    INTERVAL: "间歇跑",
    LONG_RUN: "长距离跑",
    REST: "休息",
}

#: 每周训练次数 → 周结构骨架（按周一→周日顺序占位；None=休息日）
_WEEK_SKELETONS: dict[int, list[str | None]] = {
    0: [None] * 7,
    1: [EASY, None, None, None, None, None, None],
    2: [EASY, None, None, EASY, None, None, None],
    3: [EASY, None, INTERVAL, None, None, LONG_RUN, None],
    4: [EASY, None, INTERVAL, None, EASY, None, LONG_RUN],
    5: [EASY, None, INTERVAL, None, EASY, LONG_RUN, None],
}

#: 强度课之间至少隔 1 天（骨架已满足，动态替换时再校验）
_KIND_MINUTES = {
    EASY: (30, 50),
    TEMPO: (35, 55),
    INTERVAL: (40, 60),
    LONG_RUN: (60, 100),
}

#: 单周跑量增幅上限（学生业余，保守）
MAX_WEEKLYIncrease_RATIO = 1.10


@dataclass(frozen=True)
class SessionPlan:
    """一周中某天的训练安排。"""

    day_offset: int  # 0=周一 … 6=周日
    kind: str  # easy / tempo / interval / long_run / rest
    minutes: int
    title: str
    detail: str = ""  # 强度说明（配速区间等）

    @property
    def kind_label(self) -> str:
        return _KIND_LABELS.get(self.kind, self.kind)


@dataclass(frozen=True)
class WeekPlan:
    """一周训练计划（含依据说明）。"""

    weekly_distance_km: float | None  # 目标周跑量（None=数据不足不估）
    sessions: list[SessionPlan]
    rationale: list[str] = field(default_factory=list)  # 中文理由（引用真实数据）
    warnings: list[str] = field(default_factory=list)


# ---------- 特征提取 ----------


def _parse_date_prefix(value: str | None) -> str | None:
    """从官方日期字段提取 YYYY-MM-DD 前缀（'2026-08-30T08:00:00' → 日期）。"""
    if not value:
        return None
    return value[:10]


def weekly_distance_km(activities: list[RunningActivity], *, end_date: str | None = None) -> float | None:
    """近 7 天总跑量（km）；按活动日期前缀聚合。无数据返回 None。"""
    from datetime import date, timedelta

    if not activities:
        return None
    end = date.fromisoformat(end_date) if end_date else date.today()
    start = end - timedelta(days=6)
    total = 0.0
    seen = False
    for a in activities:
        d = _parse_date_prefix(a.date)
        if d is None:
            continue
        try:
            day = date.fromisoformat(d)
        except ValueError:
            continue
        if start <= day <= end and a.distance_km:
            total += a.distance_km
            seen = True
    return round(total, 1) if seen else None


def _avg_pace_sec(activities: list[RunningActivity]) -> int | None:
    paces = [a.pace_sec_per_km for a in activities if a.pace_sec_per_km and 150 < a.pace_sec_per_km < 1200]
    return int(sum(paces) / len(paces)) if paces else None


def _hard_days(activities: list[RunningActivity]) -> list[str]:
    """近端判定为「高强度」的日期（workout_type 或配速明显快于均值）。"""
    dates: list[str] = []
    avg = _avg_pace_sec(activities)
    for a in activities:
        wt = (a.workout_type or "").lower()
        marked_hard = any(k in wt for k in ("interval", "tempo", "race", "track", "speed"))
        if marked_hard:
            dates.append(a.date or "")
            continue
        if avg and a.pace_sec_per_km and a.pace_sec_per_km < avg - 30:
            dates.append(a.date or "")
    return [d for d in dates if d]


def _recovery_level(snapshot: RunningSnapshot) -> str:
    """恢复等级（poor/moderate/good），容错提取；默认 moderate。"""
    rec = snapshot.recovery or {}
    for key in ("recoveryLevel", "recovery_level", "level"):
        v = rec.get(key)
        if isinstance(v, str) and v.strip():
            lv = v.strip().lower()
            for name in ("poor", "weak", "low"):
                if name in lv:
                    return "poor"
            for name in ("good", "excellent", "high"):
                if name in lv:
                    return "good"
            return "moderate"
        if isinstance(v, (int, float)):
            # 百分比形态：<40 差，>75 好
            return "poor" if v < 40 else ("good" if v > 75 else "moderate")
    return "moderate"


def _load_ratio(snapshot: RunningSnapshot) -> float | None:
    """短期/长期负荷比（>1.3 视为负荷偏高）。"""
    rec = snapshot.load or {}
    for key in ("loadRatio", "load_ratio", "ratio"):
        v = rec.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    short_term = rec.get("shortTermLoad") or rec.get("short_term_load")
    long_term = rec.get("longTermLoad") or rec.get("long_term_load")
    if isinstance(short_term, (int, float)) and isinstance(long_term, (int, float)) and long_term:
        return float(short_term) / float(long_term)
    return None


def _pace_str(pace_sec: int | None) -> str:
    if pace_sec is None:
        return ""
    return f"{pace_sec // 60}'{pace_sec % 60:02d}\"/km"


# ---------- 周计划生成 ----------


def generate_week_plan(
    snapshot: RunningSnapshot,
    *,
    today_iso: str | None = None,
    end_date: str | None = None,
) -> WeekPlan:
    """根据跑步数据生成未来一周训练计划（确定性规则引擎）。

    ``today_iso``：作为「今天」的日期（YYYY-MM-DD）；缺省真实今天。
    返回的 session.day_offset 相对计划起始（下周一）。
    """
    from datetime import date, timedelta

    today = date.fromisoformat(today_iso) if today_iso else date.today()
    activities = snapshot.activities
    week_km = weekly_distance_km(activities, end_date=end_date)
    avg_pace = _avg_pace_sec(activities)
    recovery = _recovery_level(snapshot)
    ratio = _load_ratio(snapshot)
    hard_recent = _hard_days(activities)
    rationale: list[str] = []
    warnings: list[str] = []

    # 1. 周跑量目标：近 7 天跑量 × 1.1（无数据 → 保守 15km 起步；恢复差 → 减量）
    if week_km is not None and week_km > 0:
        target_km = round(week_km * MAX_WEEKLYIncrease_RATIO, 1)
        if recovery == "poor" or (ratio is not None and ratio > 1.3):
            target_km = round(week_km * 0.7, 1)
            rationale.append(
                f"近 7 天跑量 {week_km}km，但"
                + (f"恢复状态偏差" if recovery == "poor" else f"短期/长期负荷比 {ratio:.2f} 偏高")
                + "，本周减量 30%（目标 " + str(target_km) + "km）"
            )
        else:
            rationale.append(f"近 7 天跑量 {week_km}km，按 ≤10% 增幅本周目标 {target_km}km")
    else:
        target_km = 15.0 if recovery != "poor" else 10.0
        warnings.append("COROS 近 7 天没有跑步记录，按新手保守目标 15km 起步（恢复差则 10km）")
        rationale.append(f"无近期跑量数据，保守目标 {target_km}km")

    # 2. 每周次数：跑量定档，恢复差再减
    if recovery == "poor" or (ratio is not None and ratio > 1.5):
        freq = 2
    elif target_km <= 15:
        freq = 3
    elif target_km <= 30:
        freq = 4
    else:
        freq = 5
    if recovery == "poor":
        rationale.append("恢复状态偏差，本周压缩到每周 2 次轻松跑，不给强度课")

    # 3. 骨架 + 轮换：负荷偏低且恢复好时把间歇换成节奏跑（隔周轮换语义）
    skeleton = [k for k in _WEEK_SKELETONS.get(freq, _WEEK_SKELETONS[3])]
    if freq >= 3 and recovery == "good" and (ratio is not None and ratio < 1.0):
        skeleton = [TEMPO if k == INTERVAL else k for k in skeleton]
        rationale.append("恢复良好且负荷比低于 1.0，本周间歇课换成节奏跑（强度课隔周轮换）")

    # 4. 每课时长与配速细节（目标跑量摊派；强度课不超上限）
    sessions: list[SessionPlan] = []
    run_days = [i for i, k in enumerate(skeleton) if k is not None]
    if run_days:
        per_run_km = target_km / len(run_days)
    for i, kind in enumerate(skeleton):
        if kind is None:
            continue
        lo, hi = _KIND_MINUTES[kind]
        if kind == LONG_RUN:
            minutes = min(hi, max(lo, int(per_run_km * 1.5 * 6)))  # 长距离配速慢、占比大
        elif kind == EASY:
            minutes = min(hi, max(lo, int(per_run_km * 6) + 5))
        else:
            minutes = min(hi, max(lo, int(per_run_km * 6)))
        detail = ""
        if kind == EASY and avg_pace:
            detail = f"配速 {_pace_str(avg_pace + 45)} 左右（比平均配速慢 45s）"
        elif kind == TEMPO and avg_pace:
            detail = f"配速 {_pace_str(avg_pace - 10)}（比平均配速快 10s 的节奏段）"
        elif kind == INTERVAL and avg_pace:
            detail = f"6×800m，间歇配速 {_pace_str(avg_pace - 30)}，组间慢跑 400m"
        elif kind == LONG_RUN and avg_pace:
            detail = f"配速 {_pace_str(avg_pace + 30)}，全程可对话配速"
        sessions.append(
            SessionPlan(
                day_offset=i,
                kind=kind,
                minutes=minutes,
                title=_KIND_LABELS[kind],
                detail=detail,
            )
        )

    # 5. 理由补充：强度缓冲（近期刚跑过强度课，周一不排间歇已在骨架保证）
    if hard_recent:
        rationale.append(f"近期有 {len(hard_recent)} 次高强度训练（最近 {hard_recent[-1]}），强度课已避开连续安排")
    if avg_pace:
        rationale.append(f"近期平均配速 {_pace_str(avg_pace)}，各课配速按此推算")
    if snapshot.fitness:
        vo2 = snapshot.fitness.get("vo2Max") or snapshot.fitness.get("vo2max")
        if isinstance(vo2, (int, float)):
            rationale.append(f"当前 VO2max {vo2}（COROS 体能评估），强度档位按业余可执行范围设定")

    # 6. 数据缺失警告
    if snapshot.recovery is None:
        warnings.append("未取到恢复状态数据，按中等恢复处理")
    if snapshot.load is None:
        warnings.append("未取到训练负荷数据，未做负荷比校验")

    return WeekPlan(
        weekly_distance_km=target_km,
        sessions=sessions,
        rationale=rationale,
        warnings=warnings,
    )
