"""API 路由聚合：所有业务路由统一挂到 /api 前缀下。"""
from fastapi import APIRouter

from backend.api import (
    course_sessions,
    courses,
    data_sources,
    knowledge_points,
    misc_items,
    review_schedules,
    tasks,
)

api_router = APIRouter()
api_router.include_router(courses.router)
api_router.include_router(course_sessions.router)
api_router.include_router(knowledge_points.router)
api_router.include_router(review_schedules.router)
api_router.include_router(tasks.router)
api_router.include_router(misc_items.router)
api_router.include_router(data_sources.router)
