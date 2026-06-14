from __future__ import annotations

import json
import stat
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from linkedin_cli.oauth_flow import AUTHORIZATION_URL
from linkedin_cli.oauth_flow import TOKEN_URL
from linkedin_cli.oauth_flow import USERINFO_URL
from linkedin_cli.oauth_flow import OAuthFlowError
from linkedin_cli.oauth_flow import author_urn_from_userinfo
from linkedin_cli.oauth_flow import build_authorization_url
from linkedin_cli.oauth_flow import exchange_authorization_code
from linkedin_cli.oauth_flow import fetch_userinfo
from linkedin_cli.oauth_flow import save_oauth_token


class FakeHTTPClient:
    def __init__(self, *, post_response=None, get_response=None) -> None:
        self.post_response = post_response or httpx.Response(200, json={})
        self.get_response = get_response or httpx.Response(200, json={})
        self.post_calls = []
        self.get_calls = []

    def post(self, url, *, data, headers):
        self.post_calls.append({"url": url, "data": data, "headers": headers})
        return self.post_response

    def get(self, url, *, headers):
        self.get_calls.append({"url": url, "headers": headers})
        return self.get_response


def test_build_authorization_url_includes_state_and_scopes() -> None:
    url = build_authorization_url(
        client_id="client-123",
        redirect_uri="http://localhost:8787/callback",
        scopes=("openid", "profile", "w_member_social"),
        state="state-123",
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZATION_URL
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["client-123"]
    assert query["redirect_uri"] == ["http://localhost:8787/callback"]
    assert query["scope"] == ["openid profile w_member_social"]
    assert query["state"] == ["state-123"]


def test_exchange_authorization_code_success() -> None:
    client = FakeHTTPClient(
        post_response=httpx.Response(
            200,
            json={"access_token": "token-123", "expires_in": 5184000},
        )
    )

    payload = exchange_authorization_code(
        client_id="client-123",
        client_secret="secret-123",
        code="code-123",
        redirect_uri="http://localhost:8787/callback",
        client=client,
    )

    assert payload["access_token"] == "token-123"
    assert client.post_calls[0]["url"] == TOKEN_URL
    assert client.post_calls[0]["data"]["grant_type"] == "authorization_code"
    assert client.post_calls[0]["data"]["client_secret"] == "secret-123"


def test_exchange_authorization_code_error_is_sanitized() -> None:
    client = FakeHTTPClient(
        post_response=httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "bad code"},
        )
    )

    with pytest.raises(OAuthFlowError) as error:
        exchange_authorization_code(
            client_id="client-123",
            client_secret="secret-123",
            code="code-123",
            redirect_uri="http://localhost:8787/callback",
            client=client,
        )

    assert error.value.code == "invalid_request"
    assert error.value.details == {"status_code": 400, "error": "invalid_grant"}


def test_fetch_userinfo_and_author_urn() -> None:
    client = FakeHTTPClient(get_response=httpx.Response(200, json={"sub": "abc123"}))

    userinfo = fetch_userinfo(access_token="token-123", client=client)

    assert userinfo == {"sub": "abc123"}
    assert client.get_calls[0]["url"] == USERINFO_URL
    assert client.get_calls[0]["headers"]["Authorization"] == "Bearer token-123"
    assert author_urn_from_userinfo(userinfo) == "urn:li:person:abc123"


def test_save_oauth_token_writes_secret_file_and_safe_result(tmp_path) -> None:
    token_path = tmp_path / "linkedin" / "oauth.json"

    result = save_oauth_token(
        path=token_path,
        access_token="token-123",
        author_urn="urn:li:person:abc123",
        scopes=("openid", "w_member_social"),
        expires_in=5184000,
    )

    raw = json.loads(token_path.read_text(encoding="utf-8"))
    assert raw["access_token"] == "token-123"
    assert raw["author_urn"] == "urn:li:person:abc123"
    assert result.to_safe_dict()["token_saved"] is True
    assert "access_token" not in result.to_safe_dict()
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
