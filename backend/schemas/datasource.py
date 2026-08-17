"""数据源绑定的请求/响应模型。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DataSourceType = Literal["notion", "obsidian", "ical", "caldav"]


class DataSourceBase(BaseModel):
    source_type: DataSourceType
    name: str | None = Field(default=None, max_length=100)
    config: str | None = Field(default=None, description="JSON 字符串：OAuth token / vault 路径 / URL")
    enabled: bool = True
    last_sync_at: str | None = None


class DataSourceCreate(DataSourceBase):
    pass


class DataSourceUpdate(BaseModel):
    source_type: DataSourceType | None = None
    name: str | None = Field(default=None, max_length=100)
    config: str | None = None
    enabled: bool | None = None
    last_sync_at: str | None = None


class DataSourceRead(DataSourceBase):
    id: int
    created_at: str

    model_config = ConfigDict(from_attributes=True)
