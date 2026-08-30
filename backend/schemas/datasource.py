"""数据源绑定的请求/响应模型。"""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DataSourceType = Literal["notion", "obsidian", "ical", "caldav", "coros"]


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


#: 响应中需要打码的敏感配置键（OAuth 令牌 / 密钥等，避免经 API 泄露）
REDACTED_CONFIG_KEYS = (
    "tokens",
    "access_token",
    "refresh_token",
    "client_secret",
    "oauth_state",
    "oauth_code_verifier",
    "oauth_session",
    "client_id",
)


class DataSourceRead(DataSourceBase):
    id: int
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @field_validator("config", mode="before")
    @classmethod
    def _redact_config(cls, v: str | None) -> str | None:
        """对外返回时打码敏感字段，避免 Notion 令牌 / 密钥经 API 泄露。

        写入（DataSourceCreate/Update）仍接收完整 config；只有读取响应走本校验器。
        """
        if not v:
            return v
        try:
            cfg = json.loads(v) if isinstance(v, str) else dict(v)
        except (TypeError, ValueError):
            return v
        if not isinstance(cfg, dict):
            return v
        for key in REDACTED_CONFIG_KEYS:
            if key in cfg:
                cfg[key] = "***"
        return json.dumps(cfg, ensure_ascii=False)


# ---------- 同步 ----------
class SyncRequest(BaseModel):
    """触发数据源同步的请求（字段按类型生效，均可选）。"""

    ics_content: str | None = Field(default=None, description="iCal：直接提交 .ics 文本（优先于 config.ics_path）")
    mode: Literal["merge", "overwrite"] = Field(
        default="merge", description="iCal：merge 只补空缺不覆盖手改；overwrite 全量覆盖 iCal 字段"
    )
    query: str | None = Field(default=None, description="Obsidian：全文搜索关键词（缺省为列出全部笔记）")
    database_id: str | None = Field(default=None, description="Notion：作业数据库 ID（缺省用 config.database_id）")


class SyncResultRead(BaseModel):
    """一次同步的汇总结果。"""

    source_id: int
    source_type: str
    synced_at: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    warnings: list[str] = []


# ---------- Notion OAuth ----------
class OAuthStartRequest(BaseModel):
    """发起 Notion OAuth 授权（缺省 source_id 时自动新建 notion 数据源）。"""

    source_id: int | None = None
    client_id: str | None = None
    redirect_uri: str | None = None


class OAuthStartRead(BaseModel):
    source_id: int
    authorization_url: str


class OAuthCallbackRequest(BaseModel):
    source_id: int
    code: str
    state: str


class OAuthCallbackRead(BaseModel):
    source_id: int
    ok: bool = True


# ---------- COROS OAuth（官方 CLI 登录会话流） ----------
class CorosOAuthStartRequest(BaseModel):
    """发起 COROS 授权（缺省 source_id 时自动新建 coros 数据源）。"""

    source_id: int | None = None


class CorosLoginStartRead(BaseModel):
    source_id: int
    login_url: str  # 用户在浏览器（手机/电脑均可）打开完成 COROS 登录


class CorosOAuthFinishRequest(BaseModel):
    source_id: int
    timeout: int | None = Field(default=30, description="轮询等待秒数（1-300，默认 30）")


class CorosOAuthFinishRead(BaseModel):
    source_id: int
    ok: bool = True
