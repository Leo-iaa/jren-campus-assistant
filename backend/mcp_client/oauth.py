"""OAuth 2.0 授权码 + PKCE（S256）客户端。

用途：Notion 官方远程 MCP Server（mcp.notion.com/mcp）的授权。

设计约束（见 Issue #11）：
- 所有端点可配置，默认指向 Notion 官方 OAuth 端点
- httpx 客户端可注入 → 测试全部走 mock，无需真实密钥/token
- 凭据来源：数据源 config JSON 或 ``JREN_NOTION_*`` 环境变量，不向用户索要
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

DEFAULT_AUTH_URL = "https://api.notion.com/v1/oauth/authorize"
DEFAULT_TOKEN_URL = "https://api.notion.com/v1/oauth/token"


@dataclass(frozen=True)
class OAuthConfig:
    """OAuth 客户端配置（client_secret 可选：公开客户端走 PKCE）。"""

    client_id: str
    client_secret: str | None = None
    redirect_uri: str = ""
    auth_url: str = DEFAULT_AUTH_URL
    token_url: str = DEFAULT_TOKEN_URL
    scopes: str = ""  # 以空格分隔的 scope 列表（Notion 默认空）


@dataclass(frozen=True)
class OAuthToken:
    """OAuth token（expires_at 为过期时间点，unix 秒）。"""

    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None

    @property
    def is_expired(self, margin: float = 60.0) -> bool:
        """是否已过期（预留 margin 秒余量，避免边界竞态）。"""
        return self.expires_at is not None and time.time() > self.expires_at - margin


def generate_state() -> str:
    """CSRF state：授权请求与回调绑定。"""
    return secrets.token_urlsafe(16)


def generate_code_verifier() -> str:
    """PKCE code_verifier（RFC 7636：43-128 位 URL 安全字符）。"""
    return secrets.token_urlsafe(64)


def generate_code_challenge(verifier: str) -> str:
    """PKCE S256 code_challenge。"""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OAuthClient:
    """OAuth 授权码 + PKCE 客户端（同步实现，httpx 可注入 mock）。"""

    def __init__(self, config: OAuthConfig, http: httpx.Client | None = None) -> None:
        self.config = config
        self.http = http or httpx.Client(timeout=30.0)

    def authorization_url(self, state: str, code_verifier: str) -> str:
        """构造授权 URL（含 PKCE 参数）。"""
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "state": state,
            "code_challenge": generate_code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        if self.config.scopes:
            params["scope"] = self.config.scopes
        return f"{self.config.auth_url}?{urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str) -> OAuthToken:
        """用授权码兑换 token（grant_type=authorization_code）。"""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "client_id": self.config.client_id,
            "code_verifier": code_verifier,
        }
        if self.config.client_secret:
            data["client_secret"] = self.config.client_secret
        resp = self.http.post(
            self.config.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return self._parse_token(resp.json())

    def refresh(self, refresh_token: str) -> OAuthToken:
        """用 refresh_token 续期（grant_type=refresh_token）。"""
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.config.client_id,
        }
        if self.config.client_secret:
            data["client_secret"] = self.config.client_secret
        resp = self.http.post(
            self.config.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return self._parse_token(resp.json())

    @staticmethod
    def _parse_token(body: dict) -> OAuthToken:
        expires_in = body.get("expires_in")
        return OAuthToken(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_at=time.time() + float(expires_in) if expires_in else None,
        )

    def close(self) -> None:
        self.http.close()
