"""课表（iCal）一键导入脚本：把 .ics 文件拖进窗口（或粘贴路径）即可。

自动完成：
1. 检查后端服务是否在运行
2. 绑定 iCal 数据源（已有则更新配置）
3. 触发同步 → 导入课程与上课时间（courses + course_sessions）

用法：双击 config_ical.bat，或命令行执行：
    py -3 backend\\scripts\\config_ical.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:28070"
DEFAULT_ICS = "C:/Users/LEO/Desktop/2026春夏.ics"


def _api(path: str, method: str = "GET", payload: dict | None = None, timeout: int = 30):
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
    print("  Jren Campus Assistant - 课表一键导入")
    print("  把教务系统导出的 .ics 文件拖进窗口即可")
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

    # 2. 获取 .ics 文件路径（拖拽或粘贴，直接回车用默认文件）
    default_hint = ""
    if os.path.exists(DEFAULT_ICS):
        default_hint = f"（直接回车用桌面默认课表 {os.path.basename(DEFAULT_ICS)}）"
    raw = input(f"\n① 把课表文件 (.ics) 拖进窗口后回车{default_hint}：\n   > ").strip()
    path = raw.strip('"').strip("'")
    if not path:
        path = DEFAULT_ICS
    if not os.path.exists(path):
        print(f"\n[×] 找不到文件：{path}")
        print("    请确认拖入的是 .ics 课表文件（教务系统导出）。")
        input("\n按回车退出...")
        sys.exit(1)
    print(f"[✓] 找到课表文件：{os.path.basename(path)}")

    # 3. 绑定 iCal 数据源（已有则更新）
    config = json.dumps({"ics_path": path.replace("\\", "/")})
    code, items = _api("/api/data-sources?source_type=ical")
    existing = (items or [])[0] if isinstance(items, list) and items else None
    if existing:
        print("\n[.] 检测到已有课表数据源，正在更新配置...")
        code, result = _api(
            f"/api/data-sources/{existing['id']}",
            method="PATCH",
            payload={"config": config},
        )
        ds_id = existing["id"]
    else:
        print("\n[.] 正在创建课表数据源...")
        code, result = _api(
            "/api/data-sources",
            method="POST",
            payload={"source_type": "ical", "name": "课表", "config": config},
        )
        ds_id = result.get("id") if isinstance(result, dict) else None

    if code not in (200, 201):
        print(f"\n[×] 绑定失败（HTTP {code}）：{result}")
        input("\n按回车退出...")
        sys.exit(1)
    print(f"[✓] 数据源已绑定（ID = {ds_id}）")

    # 4. 触发同步（导入课程与上课时间）
    print("\n[.] 正在导入课表（同步课程与上课时间）...")
    code, result = _api(f"/api/data-sources/{ds_id}/sync", method="POST")
    if code in (200, 201):
        print(f"[✓] 同步完成！结果：{result}")
        print("    课程和上课时间已写入系统，接下来可以给课程设置档位（S/A/B/C）。")
    else:
        print(f"\n[×] 同步失败（HTTP {code}）：{result}")

    input("\n按回车退出...")


if __name__ == "__main__":
    main()
