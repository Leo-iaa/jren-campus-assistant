# -*- coding: utf-8 -*-
"""打印指定日期的画像约束（屏障 / 脑力截止 / 偏好时段），验证画像是否生效。"""
import sys
from datetime import date

from backend.database import SessionLocal
from backend.mcp_server import profile_store

target = date.fromisoformat(sys.argv[1])

with SessionLocal() as db:
    prefs = profile_store.load_planner_prefs(db, target)
    print("date:", target, "weekday:", target.weekday())
    print("no_brain_after:", prefs.no_brain_after)
    print("preferred_buckets:", prefs.preferred_buckets)
    print("barriers:")
    for b in prefs.barriers or []:
        print("   ", b)
