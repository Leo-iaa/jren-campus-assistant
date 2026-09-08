# -*- coding: utf-8 -*-
"""用本地新代码重生成指定日期计划（后端 SYSTEM 进程仍跑旧代码时用本脚本）。"""
import sys
from datetime import date

from backend.database import SessionLocal
from backend.mcp_server.service import generate_plan

target = date.fromisoformat(sys.argv[1])

with SessionLocal() as db:
    result = generate_plan(db, target)
    print("date:", result.plan_date)
    print("placed:", result.placed_count)
    print("dropped:", result.dropped)
    print("skipped:", result.skipped)
