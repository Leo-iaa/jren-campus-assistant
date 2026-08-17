"""初始化 SQLite 数据库（幂等）。

用法（仓库根目录下）：
    python -m backend.scripts.init_db

或（backend/ 目录下，脚本自动处理导入路径）：
    python scripts/init_db.py

效果：
1. 确保 backend/data/ 目录存在
2. 按 models 元数据创建全部 11 张表（已存在则跳过）
3. 写入默认全局配置（仅当键不存在时，可重复执行）
"""
import sys
from pathlib import Path

# 允许直接以 `python scripts/init_db.py` 运行：
# 把仓库根目录（backend/ 的上级）加入 sys.path，使 `import backend` 可用
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend import models  # noqa: F401  确保全部模型注册到 metadata
from backend.config import BASE_DIR
from backend.database import SessionLocal, init_db as create_tables

# 文档中明确的默认配置（docs/vision.md）：复习上限 8；前一晚 21:00 预生成计划
DEFAULT_SETTINGS: dict[str, str] = {
    "review_daily_cap": "8",
    "plan_generate_time": "21:00",
}


def seed_default_settings() -> None:
    """写入默认设置（幂等：仅当 key 不存在时插入）。"""
    with SessionLocal() as session:
        inserted = 0
        for key, value in DEFAULT_SETTINGS.items():
            exists = session.query(models.Setting).filter(models.Setting.key == key).first()
            if exists is None:
                session.add(models.Setting(key=key, value=value))
                inserted += 1
        session.commit()
        print(f"✅ 默认设置：新增 {inserted} 条（现有 {len(DEFAULT_SETTINGS) - inserted} 条已存在）")


def main() -> None:
    data_dir = BASE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 数据目录：{data_dir}")

    create_tables()
    print("✅ 数据表创建完成（11 张表）")

    seed_default_settings()


if __name__ == "__main__":
    main()
