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

    # MCP Server 暴露层（WorkBuddy 接入）
    # 每天定时生成次日计划（后端兜底；测试/开发可置 false 关闭）
    mcp_scheduler_enabled: bool = True
    # 计划生成时间（HH:MM，Asia/Shanghai）
    mcp_plan_generate_time: str = "21:00"
    # Notion 日程数据库 ID（或写入数据源 config.calendar_database_id）
    mcp_notion_calendar_db: str | None = None


# 全局单例，供各模块直接导入使用
settings = Settings()
