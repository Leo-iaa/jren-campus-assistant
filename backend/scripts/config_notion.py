"""Notion 一键配置脚本：只需粘贴「集成令牌」和「日程数据库 ID」两串码。

自动完成：
1. 检查后端服务是否在运行
2. 把令牌绑定为 Notion 数据源（已有则更新配置）
3. 写入日程数据库 ID（确认计划时写入日历用）

用法：双击 config_notion.bat，或命令行执行：
    py -3 backend\\scripts\\config_notion.py
"""
import json
import re
import sys
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8000"


def extract_db_id(raw: str) -> str | None:
    """从用户粘贴的内容里提取 32 位日程数据库 ID。

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


def main() -> None:
    print("=" * 52)
    print("  Jren Campus Assistant - Notion 一键配置")
    print("  只需要两串码：集成令牌 + 日程数据库 ID")
    print("=" * 52)

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

    # 2. 输入两串码
    token = input("\n① 请粘贴 Notion 集成令牌（ntn_ 开头的一长串）：\n   > ").strip()
    db_raw = input(
        "② 请粘贴日程数据库 ID（32 位字符），或直接粘贴日程页面链接：\n   > "
    ).strip()
    db_id = extract_db_id(db_raw)
    if not token or not db_id:
        print("\n[×] 两串码都不能为空，请重试。")
        print("    【②怎么找】打开 Notion 日程页面，复制浏览器地址栏整条链接，")
        print("    粘贴到上面即可（自动提取 32 位 ID）。")
        input("\n按回车退出...")
        sys.exit(1)
    if not token.startswith(("ntn_", "secret_")):
        print("\n[!] 提醒：令牌一般以 ntn_ 或 secret_ 开头，请确认复制的是「集成令牌」。")
    if db_raw != db_id:
        print(f"[✓] 已自动识别数据库 ID：{db_id}")

    # 3. 组装配置
    config = json.dumps(
        {"tokens": {"access_token": token}, "calendar_database_id": db_id}
    )

    # 4. 查找已有 Notion 数据源（有则更新，无则新建）
    code, items = _api("/api/data-sources?source_type=notion")
    existing = (items or [])[0] if isinstance(items, list) and items else None

    if existing:
        print("\n[.] 检测到已有 Notion 数据源，正在更新配置...")
        code, result = _api(
            f"/api/data-sources/{existing['id']}",
            method="PATCH",
            payload={"config": config},
        )
    else:
        print("\n[.] 正在创建 Notion 数据源...")
        code, result = _api(
            "/api/data-sources",
            method="POST",
            payload={"source_type": "notion", "name": "Notion", "config": config},
        )

    if code in (200, 201):
        sid = result.get("id") if isinstance(result, dict) else "?"
        print(f"[✓] 绑定成功！数据源 ID = {sid}")
        print("    以后确认计划时会自动写入你的 Notion 日历。")
        print("    令牌是否有效会在同步数据时自动校验（无效会提示）。")
    else:
        print(f"[×] 绑定失败（HTTP {code}）：{result}")
        print("    常见原因：后端未运行 / 服务异常。")

    input("\n按回车退出...")


if __name__ == "__main__":
    main()
