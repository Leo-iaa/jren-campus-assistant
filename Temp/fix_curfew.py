# -*- coding: utf-8 -*-
"""把晚间脑力截止从 21:15 改为 23:00（洗澡后到洗漱前仍是可用时间）。"""
from backend.database import SessionLocal
from backend.mcp_server.profile_store import save_manual_prefs

with SessionLocal() as db:
    profile = save_manual_prefs(db, no_brain_after="23:00")
    print("no_brain_after:", profile["no_brain_after"])
