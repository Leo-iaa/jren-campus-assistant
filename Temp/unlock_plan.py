# -*- coding: utf-8 -*-
"""把 2026-09-08 已确认的计划项回退为草稿，便于按新作息重新生成。"""
from backend.database import SessionLocal
from backend.models import PlanItem

TARGET = "2026-09-08"

with SessionLocal() as db:
    items = (
        db.query(PlanItem)
        .filter(PlanItem.date == TARGET, PlanItem.status == "confirmed")
        .all()
    )
    for it in items:
        it.status = "draft"
    db.commit()
    print(f"reverted {len(items)} confirmed items to draft for {TARGET}")
