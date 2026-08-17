"""声明式基类：所有 ORM 模型继承自此。"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """项目统一的 ORM 基类。"""
