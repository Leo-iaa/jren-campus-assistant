"""造演示数据：课程 / 时间块 / 知识点 / 复习计划 / 任务 / 杂项（通过后端 API）。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(method, path, payload=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        print(f"  !! {method} {path} -> {e.code} {e.read().decode()[:200]}")
        return None


# 已有高数(id=1, S)。补充课程
courses = {}
for name, tier in [("线性代数", "A"), ("大学英语", "B"), ("体育", "C")]:
    c = call("POST", "/api/courses", {"name": name, "tier": tier})
    if c:
        courses[name] = c["id"]
        print(f"course: {name} id={c['id']} tier={tier}")

# 时间块：day_of_week 0=周一
sessions = [
    (1, 0, "08:00", "09:40", "教一 101", 0),
    (1, 2, "08:00", "09:40", "教一 101", 0),
    (courses.get("线性代数"), 0, "10:00", "11:40", "教二 203", 0),
    (courses.get("线性代数"), 4, "10:00", "11:40", "教二 203", 0),
    (courses.get("大学英语"), 1, "14:00", "15:40", "外语楼 302", 0),
    (courses.get("体育"), 3, "16:00", "17:40", "操场", 1),  # C 档释放
]
for course_id, dow, start, end, loc, release in sessions:
    if course_id is None:
        continue
    s = call(
        "POST",
        f"/api/courses/{course_id}/sessions",
        {
            "day_of_week": dow,
            "start_time": start,
            "end_time": end,
            "location": loc,
            "release_slot": release,
        },
    )
    if s:
        print(f"session: course={course_id} dow={dow} {start}-{end}")

# 知识点（挂在高数 id=1）
kps = {}
for title, diff in [("极限的定义", 4), ("导数四则运算", 2)]:
    k = call(
        "POST",
        "/api/knowledge-points",
        {"course_id": 1, "title": title, "difficulty": diff, "content_snapshot": "课堂笔记片段"},
    )
    if k:
        kps[title] = k["id"]
        print(f"kp: {title} id={k['id']} diff={diff}")

# 复习计划
reviews = [
    (kps.get("极限的定义"), 2, "2026-08-17", "pending"),  # 今天 第2次
    (kps.get("极限的定义"), 3, "2026-08-20", "pending"),
    (kps.get("导数四则运算"), 1, "2026-08-18", "pending"),  # 明天
]
for kp_id, seq, due, status in reviews:
    if kp_id is None:
        continue
    r = call(
        "POST",
        "/api/review-schedules",
        {"knowledge_point_id": kp_id, "seq": seq, "due_date": due, "status": status},
    )
    if r:
        print(f"review: kp={kp_id} seq={seq} due={due}")

# 任务
tasks = [
    ("高数作业：导数练习", 1, "2026-08-17", 60, "todo"),
    ("线代作业：矩阵运算", courses.get("线性代数"), "2026-08-18", 90, "todo"),
]
for title, cid, deadline, mins, status in tasks:
    t = call(
        "POST",
        "/api/tasks",
        {"course_id": cid, "title": title, "deadline": deadline, "estimated_minutes": mins, "status": status},
    )
    if t:
        print(f"task: {title} deadline={deadline}")

# 杂项
for title, dur, pref in [("取快递", 30, None), ("社团例会", 60, "19:00")]:
    m = call(
        "POST",
        "/api/misc-items",
        {"title": title, "duration_minutes": dur, "preferred_time": pref},
    )
    if m:
        print(f"misc: {title} dur={dur} pref={pref}")

print("DONE")
