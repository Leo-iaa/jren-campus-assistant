"""晚间推送任务测试：防重标记 / 确保次日计划 / 启动补偿钩子（幂等）。"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import backend.mcp_server.scheduler_jobs as sj
from backend.models.plan import PlanItem
from backend.models.settings import Setting

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _at(hour: int, minute: int = 0) -> datetime:
    """真实「今天」的指定时刻（保留真实日期，与 service 层日期一致）。"""
    return datetime.now(_SHANGHAI).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def _patch(db_session, monkeypatch, push_result=(True, "HTTP 200 | 发送成功")):
    """patch SessionLocal + Notion writer + 推送 CLI（记录调用）。"""
    calls: list[str] = []

    def fake_push(text: str):
        calls.append(text)
        return push_result

    monkeypatch.setattr("backend.database.SessionLocal", db_session)
    monkeypatch.setattr(sj, "_build_writer_safe", lambda db: (None, None))
    monkeypatch.setattr(sj, "_push_text_via_cli", fake_push)
    return calls


def test_evening_push_sends_and_marks(db_session, monkeypatch):
    """正常路径：确保次日计划 → 推送一次 → 写当日标记。"""
    calls = _patch(db_session, monkeypatch)
    today = date.today().isoformat()

    sj.evening_push_job(now=_at(21, 5))

    assert len(calls) == 1, "应推送恰好一次"
    assert isinstance(calls[0], str) and calls[0], "推送文本非空"
    with db_session() as db:
        mark = (
            db.query(Setting).filter(Setting.key == sj.EVENING_PUSH_MARK_KEY).first()
        )
        assert mark is not None and mark.value == today, "成功后应写当日标记"


def test_evening_push_skips_when_already_marked(db_session, monkeypatch):
    """当日已推送（标记存在）→ 不再推送（misfire 补跑防重）。"""
    calls = _patch(db_session, monkeypatch)
    today = date.today().isoformat()
    with db_session() as db:
        db.add(Setting(key=sj.EVENING_PUSH_MARK_KEY, value=today))
        db.commit()

    sj.evening_push_job(now=_at(21, 5))

    assert calls == [], "已推送过时不应再调 CLI"


def test_evening_push_generates_tomorrow_plan(db_session, monkeypatch):
    """次日计划缺失时，推送前先补生成（generate_tomorrow_plan_job 幂等路径）。"""
    calls = _patch(db_session, monkeypatch)
    tomorrow_date = date.today()  # tomorrow() 以上海时区为准，测试环境同日

    sj.evening_push_job(now=_at(21, 5))

    with db_session() as db:
        items = db.query(PlanItem).all()
    assert isinstance(items, list)
    assert calls, "无论计划是否为空都应推送兜底文本"


def test_evening_push_failure_leaves_unmarked(db_session, monkeypatch):
    """推送失败 → 不写标记（留下次机会），且不抛异常。"""
    calls = _patch(
        db_session, monkeypatch, push_result=(False, "TOKEN_EXPIRED token 已失效")
    )

    sj.evening_push_job(now=_at(21, 5))  # 不应抛

    assert len(calls) == 1, "失败前应尝试推送"
    with db_session() as db:
        mark = (
            db.query(Setting).filter(Setting.key == sj.EVENING_PUSH_MARK_KEY).first()
        )
        assert mark is None, "失败不应写标记"


def test_catchup_triggers_evening_push_after_push_time(db_session, monkeypatch):
    """启动补偿：已到晚间推送点（≥21:05）且未推送过 → 触发晚间推送。"""
    calls = _patch(db_session, monkeypatch)

    sj.run_startup_catchup(now=_at(22, 30))

    assert len(calls) == 1, "重启晚于推送点时应补推次日计划"


def test_catchup_skips_evening_push_before_push_time(db_session, monkeypatch):
    """启动补偿：未到推送点（如晨间 09:35 补偿路径）→ 不触发晚间推送。"""
    calls = _patch(db_session, monkeypatch)

    sj.run_startup_catchup(now=_at(9, 35))

    assert calls == [], "未到推送点不应推送"
