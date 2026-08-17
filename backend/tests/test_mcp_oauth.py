"""OAuth 2.0 授权码 + PKCE 客户端测试（httpx.MockTransport，无真实网络）。"""
from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend.mcp_client.oauth import (
    OAuthClient,
    OAuthConfig,
    OAuthToken,
    generate_code_challenge,
    generate_code_verifier,
    generate_state,
)


def _mock_http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_authorization_url_contains_pkce_and_state():
    oauth = OAuthClient(
        OAuthConfig(client_id="cid", redirect_uri="http://localhost:5173/oauth/notion/callback"),
        http=_mock_http(lambda request: httpx.Response(200, json={})),
    )
    state = generate_state()
    verifier = generate_code_verifier()
    url = oauth.authorization_url(state, verifier)
    assert url.startswith("https://api.notion.com/v1/oauth/authorize")
    params = parse_qs(urlparse(url).query)
    assert params["client_id"] == ["cid"]
    assert params["response_type"] == ["code"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == [generate_code_challenge(verifier)]
    assert params["state"] == [state]
    assert params["redirect_uri"] == ["http://localhost:5173/oauth/notion/callback"]


def test_exchange_code_posts_form_and_parses_token():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers["content-type"]
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600},
        )

    oauth = OAuthClient(
        OAuthConfig(client_id="cid", client_secret="sec", redirect_uri="http://x/cb"),
        http=_mock_http(handler),
    )
    token = oauth.exchange_code("code-1", "verifier-1")

    assert token.access_token == "at-1"
    assert token.refresh_token == "rt-1"
    assert token.expires_at is not None and token.expires_at > time.time()
    assert "application/x-www-form-urlencoded" in captured["content_type"]
    body = dict(item.split("=", 1) for item in captured["body"].split("&"))
    assert body["grant_type"] == "authorization_code"
    assert body["code"] == "code-1"
    assert body["code_verifier"] == "verifier-1"
    assert body["client_secret"] == "sec"
    assert body["client_id"] == "cid"
    assert captured["url"] == "https://api.notion.com/v1/oauth/token"


def test_refresh_uses_refresh_token():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3600})

    oauth = OAuthClient(OAuthConfig(client_id="cid"), http=_mock_http(handler))
    token = oauth.refresh("rt-old")
    assert token.access_token == "at-2"
    body = dict(item.split("=", 1) for item in captured["body"].split("&"))
    assert body["grant_type"] == "refresh_token"
    assert body["refresh_token"] == "rt-old"


def test_exchange_failure_raises_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    oauth = OAuthClient(OAuthConfig(client_id="cid"), http=_mock_http(handler))
    with pytest.raises(httpx.HTTPStatusError):
        oauth.exchange_code("bad", "verifier")


def test_token_expiry_logic():
    assert not OAuthToken(access_token="a", expires_at=time.time() + 3600).is_expired
    assert OAuthToken(access_token="a", expires_at=time.time() - 10).is_expired
    assert not OAuthToken(access_token="a").is_expired  # 无过期时间 → 永不过期


def test_generators_produce_distinct_values():
    assert generate_state() != generate_state()
    assert generate_code_verifier() != generate_code_verifier()
    # PKCE 校验：challenge 可由 verifier 复现且为 URL 安全 base64
    verifier = generate_code_verifier()
    assert generate_code_challenge(verifier) == generate_code_challenge(verifier)
    assert "=" not in generate_code_challenge(verifier)
