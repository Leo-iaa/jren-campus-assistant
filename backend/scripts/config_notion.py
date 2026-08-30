"""Notion 一键配置脚本：粘贴「集成令牌」+「日程库」+「任务库」三串码。

自动完成：
1. 检查后端服务是否在运行
2. 把令牌绑定为 Notion 数据源（已有则更新配置，令牌可回车沿用）
3. 写入日程数据库 ID（确认计划时写入日历用）
4. 写入任务数据库 ID（微信添加任务时写入任务库用，可跳过/沿用）

新能力：**直接粘贴「页面链接」也能解析**——如果链接指向的是页面
（如 Notion 新版「任务管理」页面内嵌数据库），脚本会自动列出页面里的
数据库让你选择，不用手动找 32 位数据库 ID。

用法：双击 config_notion.bat，或命令行执行：
    py -3 backend\\scripts\\config_notion.py
"""
import json
import re
import sys
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:28070"
NOTION_API = "https://api.notion.com"
NOTION_VERSION = "2022-06-28"
#: 页面里递归查找内嵌数据库的最大深度（防异常深嵌套页面拖慢脚本）
DEEP_LIMIT = 3


def extract_db_id(raw: str) -> str | None:
    """从用户粘贴的内容里提取 32 位数据库/页面 ID。

    支持三种格式：
    1. 直接 32 位 ID：3c011544057d80fba090e3c1a0de7ad1
    2. 新版链接：https://app.notion.com/p/3c011544057d80fba090e3c1a0de7ad1?v=...
    3. 旧版链接：https://www.notion.so/workspace/3c011544057d80fba090e3c1a0de7ad1?v=...

    链接里可能有两串 32 位字符（页面 ID 和视图 ID），取第一串（页面 ID）。
    """
    matches = re.findall(r"[0-9a-f]{32}", raw.strip().lower())
    return matches[0] if matches else None


def _api(path: str, method: str = "GET", payload: dict | None = None, timeout: int = 10):
    """调用后端 API，返回 (状态码, JSON 或原始文本)。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def _notion_get(token: str, path: str):
    """直接调 Notion API（探测数据库用），返回 (状态码, JSON)。"""
    req = urllib.request.Request(
        NOTION_API + path,
        headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", errors="replace"))
        except Exception:
            return e.code, {}


def _collect_child_databases(token: str, block_id: str, depth: int = 0, out=None, seen=None) -> list[tuple[str, str]]:
    """递归收集页面内嵌数据库：[(标题, id), ...]（深度受限，去重防环）。"""
    out = out if out is not None else []
    seen = seen if seen is not None else set()
    if depth > DEEP_LIMIT or block_id in seen:
        return out
    seen.add(block_id)
    status, data = _notion_get(token, f"/v1/blocks/{block_id}/children?page_size=100")
    if status != 200:
        return out
    for block in data.get("results", []):
        if block["type"] == "child_database":
            title = (block.get("child_database") or {}).get("title") or "(未命名)"
            out.append((title, block["id"]))
        elif block.get("has_children"):
            _collect_child_databases(token, block["id"], depth + 1, out, seen)
    return out


def resolve_database_id(token: str, raw: str) -> tuple[str, str]:
    """从用户粘贴内容解析出**可写**的数据库 ID（支持页面链接）。

    1. ID/链接直接是数据库 → 返回 (id, 说明)
    2. 是页面 → 递归找页面内嵌数据库，列出让用户选
    失败抛 RuntimeError（中文原因）。
    """
    raw_id = extract_db_id(raw)
    if not raw_id:
        raise RuntimeError("未能识别数据库 ID：请粘贴 32 位 ID 或页面链接")

    # 先试数据库
    status, data = _notion_get(token, f"/v1/databases/{raw_id}")
    if status == 200:
        title = "".join(t.get("plain_text", "") for t in (data.get("title") or [])) or "未命名"
        return raw_id, f"数据库「{title}」"

    # 再试页面（找内嵌数据库）
    status, _ = _notion_get(token, f"/v1/pages/{raw_id}")
    if status == 200:
        dbs = _collect_child_databases(token, raw_id)
        if not dbs:
            raise RuntimeError("这个页面里没有找到数据库，请确认链接指向数据库页面。")
        print("\n[.] 该链接指向页面，页面内找到以下数据库：")
        for i, (title, _db_id) in enumerate(dbs, 1):
            print(f"    {i}. {title}")
        while True:
            choice = input(f"    输入序号选择（1-{len(dbs)}）：").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(dbs):
                title, db_id = dbs[int(choice) - 1]
                return db_id, f"页面内数据库「{title}」"
            print("    序号无效，请重试。")

    raise RuntimeError("无法解析：该 ID 既不是数据库也不是页面（请确认集成已连接该库）")


def main() -> None:
    print("=" * 56)
    print("  Jren Campus Assistant - Notion 一键配置")
    print("  集成令牌 + 日程库 + 任务库（任务库可跳过）")
    print("=" * 56)

    # 1. 检查后端服务
    try:
        code, _ = _api("/health", timeout=3)
        if code != 200:
            raise RuntimeError(f"health={code}")
    except Exception:
        print("\n[×] 后端服务没在运行！")
        print("    请先双击 backend\\scripts\\start_backend.bat 启动，再重试本脚本。")
        input("\n按回车退出...")
        sys.exit(1)
    print("[✓] 后端服务运行中")

    # 2. 读取已有 Notion 数据源配置（有则更新、令牌可沿用）
    existing: dict = {}
    code, items = _api("/api/data-sources?source_type=notion")
    if isinstance(items, list) and items:
        try:
            existing = json.loads(items[0].get("config") or "{}")
        except json.JSONDecodeError:
            existing = {}
        sid = items[0].get("id")
    else:
        sid = None

    if existing:
        print("[.] 检测到已有 Notion 数据源，以下内容可直接回车沿用。")

    # 3. 输入三串码
    token = input("\n① 请粘贴 Notion 集成令牌（ntn_ 开头；已配置可回车沿用）：\n   > ").strip()
    if not token:
        token = ((existing.get("tokens") or {}).get("access_token") or "").strip()
        if not token:
            print("\n[×] 没有可沿用的令牌，必须粘贴集成令牌。")
            input("\n按回车退出...")
            sys.exit(1)
        print("    [.] 沿用已有令牌")
    elif not token.startswith(("ntn_", "secret_")):
        print("\n[!] 提醒：令牌一般以 ntn_ 或 secret_ 开头，请确认复制的是「集成令牌」。")

    old_cal = existing.get("calendar_database_id")
    print(f"\n② 日程数据库（确认计划写入日历用；当前：{old_cal or '未配置'}）")
    cal_raw = input("   粘贴 ID 或页面链接（回车沿用）：\n   > ").strip()
    if cal_raw:
        try:
            cal_id, cal_desc = resolve_database_id(token, cal_raw)
        except RuntimeError as exc:
            print(f"\n[×] 日程库解析失败：{exc}")
            input("\n按回车退出...")
            sys.exit(1)
        print(f"    [✓] {cal_desc}（{cal_id}）")
    elif old_cal:
        cal_id, cal_desc = old_cal, "沿用现有"
    else:
        print("\n[×] 日程库是必填项（确认计划时写日历用），请粘贴 ID 或链接。")
        input("\n按回车退出...")
        sys.exit(1)

    old_task = existing.get("task_database_id")
    print(f"\n③ 任务数据库（微信添加任务时写入；当前：{old_task or '未配置'}，可回车跳过/沿用）")
    task_raw = input("   粘贴 ID 或页面链接（回车跳过/沿用）：\n   > ").strip()
    if task_raw:
        try:
            task_id, task_desc = resolve_database_id(token, task_raw)
        except RuntimeError as exc:
            print(f"\n[×] 任务库解析失败：{exc}")
            input("\n按回车退出...")
            sys.exit(1)
        print(f"    [✓] {task_desc}（{task_id}）")
    elif old_task:
        task_id, task_desc = old_task, "沿用现有"
    else:
        task_id, task_desc = None, "跳过（之后可重跑本脚本补上）"

    # 4. 组装配置（保留既有 props 等字段，只更新令牌与库 ID）
    config = dict(existing)
    tokens = dict(config.get("tokens") or {})
    tokens["access_token"] = token
    config["tokens"] = tokens
    config["calendar_database_id"] = cal_id
    if task_id:
        config["task_database_id"] = task_id
    else:
        config.pop("task_database_id", None)

    # 5. 更新或创建数据源
    if sid is not None:
        print("\n[.] 正在更新 Notion 数据源配置...")
        code, result = _api(f"/api/data-sources/{sid}", method="PATCH", payload={"config": json.dumps(config, ensure_ascii=False)})
    else:
        print("\n[.] 正在创建 Notion 数据源...")
        code, result = _api(
            "/api/data-sources",
            method="POST",
            payload={"source_type": "notion", "name": "Notion", "config": json.dumps(config, ensure_ascii=False)},
        )

    if code in (200, 201):
        final_sid = result.get("id") if isinstance(result, dict) else sid
        print(f"\n[✓] 绑定成功！数据源 ID = {final_sid}")
        print(f"    · 日程库：{cal_desc}")
        print(f"    · 任务库：{task_desc}")
        print("    以后在微信里说「有新任务：XXX，ddl 是 YYY」就会自动写入任务库。")
        print("    令牌是否有效会在写入时自动校验（无效会提示）。")
    else:
        print(f"\n[×] 绑定失败（HTTP {code}）：{result}")
        print("    常见原因：后端未运行 / 服务异常。")

    input("\n按回车退出...")


if __name__ == "__main__":
    main()
