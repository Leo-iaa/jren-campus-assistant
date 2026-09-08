# -*- coding: utf-8 -*-
"""一次性写入 LEO 的作息画像（MCP 工具入参无法传 JSON 字符串，故直连存储层）。"""
import json

from backend.database import SessionLocal
from backend.mcp_server.profile_store import save_manual_prefs

ITEMS = [
    {"title": "早饭", "days": "每天", "start": "08:00", "end": "08:15"},
    {"title": "午饭", "days": "每天", "start": "12:10", "end": "12:40"},
    {"title": "午觉", "days": "每天", "start": "13:00", "end": "13:45"},
    {"title": "晚饭", "days": "每天", "start": "17:40", "end": "18:10"},
    {"title": "洗澡", "days": "每天", "start": "21:00", "end": "21:15"},
    {"title": "洗漱准备睡觉", "days": "每天", "start": "23:00", "end": "23:15"},
    {"title": "打扫宿舍卫生", "days": "一", "start": "18:10", "end": "18:20"},
    {"title": "剪指甲", "days": "日", "start": "21:15", "end": "21:25"},
    {"title": "跑步", "days": "二四", "start": "16:00", "end": "17:00"},
    {"title": "LSD长距离慢跑", "days": "六", "start": "15:00", "end": "16:30"},
]

with SessionLocal() as db:
    profile = save_manual_prefs(
        db,
        rhythm="普通",
        no_brain_after="21:15",
        fixed_activities=json.dumps(ITEMS, ensure_ascii=False),
    )

print("rhythm:", profile["rhythm"])
print("no_brain_after:", profile["no_brain_after"])
for item in profile["fixed_activities"]:
    print(item)
