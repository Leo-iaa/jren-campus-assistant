"""FastAPI 应用入口。

启动方式（仓库根目录）：
    uvicorn backend.main:app --reload

或（backend/ 目录内）：
    uvicorn main:app --reload

MCP Server（Streamable HTTP）挂载在 /mcp 路径（QClaw 接入地址：
http://<局域网IP>:8000/mcp），其会话管理器生命周期由本应用 lifespan 接管；
APScheduler 21:00 定时任务同样在 lifespan 中按配置启停。
"""
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.routing import Route

from backend.api import api_router
from backend.api.health import router as health_router
from backend.config import settings
from backend.mcp_server.scheduler_jobs import start_scheduler_if_enabled, stop_scheduler
from backend.mcp_server.server import build_mcp_server


def create_app(db_factory: Callable[[], Session] | None = None) -> FastAPI:
    """应用工厂：集中组装中间件、路由、MCP Server 与生命周期。

    ``db_factory`` 仅供测试注入临时数据库（MCP 工具使用）；默认为全局 SessionLocal。
    """
    # MCP Server 先建：lifespan 需要引用其 session manager
    mcp_server = build_mcp_server(db_factory=db_factory)
    # Streamable HTTP ASGI 应用；host=0.0.0.0 关闭 localhost 专属的 DNS
    # rebinding 防护，允许 QClaw 通过局域网 IP 访问
    mcp_app = mcp_server.streamable_http_app(streamable_http_path="/mcp", host="0.0.0.0")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # MCP 会话管理器必须在请求前启动（内嵌 ASGI 应用无自己的 lifespan）
        async with mcp_server.session_manager.run():
            start_scheduler_if_enabled()
            yield
            stop_scheduler()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="J人校园助手后端 API：课程 / 知识点 / 复习计划 / 任务 / 杂项 / 数据源 / MCP 工具",
        lifespan=lifespan,
    )

    # MCP Server 暴露层：QClaw 连接 http://<局域网IP>:8000/mcp
    # 用 Route 直接挂 ASGI 端点（而非 Mount），避免 /mcp → /mcp/ 的 307 重定向
    app.router.routes.insert(0, Route("/mcp", endpoint=mcp_app, name="mcp"))

    # CORS：允许前端开发服务器跨域调用
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(api_router, prefix="/api")

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(_request: Request, _exc: IntegrityError) -> JSONResponse:
        """数据库约束冲突（唯一约束 / 外键 / CHECK）统一返回 409。"""
        return JSONResponse(
            status_code=409,
            content={"detail": "数据冲突：违反唯一约束或外键约束，请检查请求内容"},
        )

    return app


# uvicorn backend.main:app 直接使用的应用实例
app = create_app()
