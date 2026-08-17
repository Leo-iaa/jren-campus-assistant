"""FastAPI 应用入口。

启动方式（仓库根目录）：
    uvicorn backend.main:app --reload

或（backend/ 目录内）：
    uvicorn main:app --reload
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from backend.api import api_router
from backend.api.health import router as health_router
from backend.config import settings


def create_app() -> FastAPI:
    """应用工厂：集中组装中间件、路由与异常处理。"""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="J人校园助手后端 API：课程 / 知识点 / 复习计划 / 任务 / 杂项 / 数据源",
    )

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
