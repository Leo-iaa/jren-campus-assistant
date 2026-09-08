"""晨间推送任务测试：防重标记 / 确保今日计划 / CLI 结果处理（幂等）。"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import backend.mcp_server.scheduler_jobs as sj
import backend.mcp_server.wechat_push as wp
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
    monkeypatch.setattr(wp, "push_text_via_cli", fake_push)
    return calls


def test_morning_push_sends_and_marks(db_session, monkeypatch):
    """正常路径：取到今日计划文本 → 推送一次 → 写当日标记。"""
    calls = _patch(db_session, monkeypatch)
    today = date.today().isoformat()

    sj.morning_push_job(now=_at(9, 35))

    assert len(calls) == 1, "应推送恰好一次"
    assert "今日计划" in calls[0], "推送内容应为计划预览文本"
    with db_session() as db:
        mark = (
            db.query(Setting).filter(Setting.key == sj.MORNING_PUSH_MARK_KEY).first()
        )
        assert mark is not None and mark.value == today, "成功后应写当日标记"


def test_morning_push_skips_when_already_marked(db_session, monkeypatch):
    """当日已推送（标记存在）→ 不再推送（重启 misfire 补跑防重）。"""
    calls = _patch(db_session, monkeypatch)
    today = date.today().isoformat()
    with db_session() as db:
        db.add(Setting(key=sj.MORNING_PUSH_MARK_KEY, value=today))
        db.commit()

    sj.morning_push_job(now=_at(9, 35))

    assert calls == [], "已推送过时不应再调 CLI"


def test_morning_push_ensures_today_plan(db_session, monkeypatch):
    """今日计划为空时，推送前先补生成（复用启动补偿路径）。"""
    calls = _patch(db_session, monkeypatch)

    sj.morning_push_job(now=_at(9, 35))

    with db_session() as db:
        items = (
            db.query(PlanItem).filter(PlanItem.date == date.today().isoformat()).all()
        )
    # 空 DB（无课程/任务）生成空计划是合法结果，关键是不再走「无计划」兜底分支：
    # preview 文本要么含真实安排，要么含 Notion 回退说明，而不是崩溃
    assert isinstance(items, list)
    assert calls and calls[0].startswith("📅 今日计划")


def test_morning_push_failure_leaves_unmarked(db_session, monkeypatch):
    """推送失败 → 不写标记（留下次机会），且不抛异常。"""
    calls = _patch(
        db_session, monkeypatch, push_result=(False, "TOKEN_EXPIRED token 已失效")
    )

    sj.morning_push_job(now=_at(9, 35))  # 不应抛

    assert len(calls) == 1, "失败前应尝试推送"
    with db_session() as db:
        mark = (
            db.query(Setting).filter(Setting.key == sj.MORNING_PUSH_MARK_KEY).first()
        )
        assert mark is None, "失败不应写标记"


def test_catchup_triggers_morning_push_after_push_time(db_session, monkeypatch):
    """启动补偿：已过晨间推送点（如 10:00 重启）且未推送过 → 立即补推今日计划。"""
    calls = _patch(db_session, monkeypatch)

    sj.run_startup_catchup(now=_at(10, 0))

    assert len(calls) == 1, "重启晚于 09:35 且未推送时应补推今日计划"
    assert "今日计划" in calls[0]
    with db_session() as db:
        mark = (
            db.query(Setting).filter(Setting.key == sj.MORNING_PUSH_MARK_KEY).first()
        )
        assert mark is not None and mark.value == date.today().isoformat()


def test_catchup_morning_skipped_when_already_marked(db_session, monkeypatch):
    """启动补偿：当天晨间已推送过 → 过了推送点也不重推（幂等防重）。"""
    calls = _patch(db_session, monkeypatch)
    with db_session() as db:
        db.add(Setting(key=sj.MORNING_PUSH_MARK_KEY, value=date.today().isoformat()))
        db.commit()

    sj.run_startup_catchup(now=_at(10, 0))

    assert calls == [], "晨间已推送过时不应补推"


def test_catchup_morning_skipped_after_evening_time(db_session, monkeypatch):
    """启动补偿：已到晚间推送点之后（如 21:30 重启）→ 晨间不补推，
    避免与晚间推送连发两条；此时只应触发晚间推送。"""
    calls = _patch(db_session, monkeypatch)

    sj.run_startup_catchup(now=_at(21, 30))

    assert len(calls) == 1, "只应触发晚间推送一条"
    with db_session() as db:
        morning_mark = (
            db.query(Setting).filter(Setting.key == sj.MORNING_PUSH_MARK_KEY).first()
        )
        evening_mark = (
            db.query(Setting).filter(Setting.key == sj.EVENING_PUSH_MARK_KEY).first()
        )
    assert morning_mark is None, "晚间时段不应写晨间标记"
    assert evening_mark is not None and evening_mark.value == date.today().isoformat()


def test_push_cli_injects_user_home(monkeypatch):
    """_push_text_via_cli：给 CLI 子进程注入 USERPROFILE/HOME。

    后端以 SYSTEM 运行时 expanduser("~") 会解析到 systemprofile，
    CLI 报「找不到 settings.json」（2026-09-07 实测）——必须指向真实用户目录。
    """
    import subprocess

    captured: dict = {}

    class P:
        returncode = 0
        stdout = "HTTP 200 | 发送成功"
        stderr = ""

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return P()

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, _ = wp.push_text_via_cli("x")
    assert ok
    env = captured.get("env")
    assert env is not None, "应给子进程显式传 env"
    home = sj.settings.mcp_wechat_push_home
    assert env["USERPROFILE"] == home and env["HOME"] == home
    assert "PATH" in env, "应继承原环境（只覆盖 home 变量）"


def test_push_cli_parses_subprocess_result(monkeypatch):
    """_push_text_via_cli：按输出判断成败（CLI 失败时退出码也是 0）。"""
    import subprocess

    class P:
        def __init__(self, code, out, err=""):
            self.returncode = code
            self.stdout = out
            self.stderr = err

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: P(0, "HTTP 200 | 发送成功\n[OK] 已主动推送")
    )
    ok, detail = wp.push_text_via_cli("x")
    assert ok and "发送成功" in detail

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: P(0, "HTTP 200 | errcode None |  | ret -2")
    )
    ok, detail = wp.push_text_via_cli("x")
    assert not ok and "ret -2" in detail, "无成功标志即视为失败"
    assert "acquire_token" in detail, "ret -2 也应附 token 刷新指引"

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: P(0, "token 已失效(errcode -14)：请重新调用 acquire_token 获取。"),
    )
    ok, detail = wp.push_text_via_cli("x")
    assert not ok and "acquire_token" in detail, "token 失效应附刷新指引"

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("cmd", 90)),
    )
    ok, detail = wp.push_text_via_cli("x")
    assert not ok and detail, "超时不抛异常、返回失败详情"
