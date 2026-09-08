# -*- coding: utf-8 -*-
"""查看指定日期计划项（调试用）。"""
import sys

from backend.database import SessionLocal
from backend.models import PlanItem

target = sys.argv[1]

with SessionLocal() as db:
    items = (
        db.query(PlanItem)
        .filter(PlanItem.date == target)
        .order_by(PlanItem.start_time, PlanItem.id)
        .all()
    )
    for it in items:
        print(it.start_time, it.end_time, it.item_type, it.status, it.title)
