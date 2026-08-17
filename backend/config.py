"""应用配置管理（pydantic-settings）。

配置来源优先级：环境变量 > .env 文件 > 默认值。
所有环境变量统一使用 ``JREN_`` 前缀，例如 ``JREN_DATABASE_URL``。
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录的绝对路径（以此定位 data/ 等相对资源）
BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """全局应用配置。"""

    model_config = SettingsConfigDict(
        env_prefix="JREN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用基本信息
    app_name: str = "jren-campus-assistant"
    app_version: str = "0.1.0"
    debug: bool = False

    # 数据库连接（默认指向 backend/data/jren.db）
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'jren.db').as_posix()}"

    # CORS 允许的来源（前端开发服务器）
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


# 全局单例，供各模块直接导入使用
settings = Settings()
