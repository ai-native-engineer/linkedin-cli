"""OAuth authorization-code flow helpers for LinkedIn."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
from typing import Any, Callable, Optional, Sequence
from urllib.parse import parse_qs, urlencode, urlparse
import webbrowser

import httpx

from .oauth import DEFAULT_LINKEDIN_VERSION

AUTHORIZATION_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
DEFAULT_REDIRECT_URI = "http://localhost:8787/callback"
DEFAULT_SCOPES = ("openid", "profile", "email", "w_member_social")
ENV_CLIENT_ID = "LINKEDIN_CLIENT_ID"
ENV_CLIENT_SECRET = "LINKEDIN_CLIENT_SECRET"
ENV_REDIRECT_URI = "LINKEDIN_REDIRECT_URI"


class OAuthFlowError(RuntimeError):
    """Raised when LinkedIn OAuth login cannot complete."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_request",
        retryable: bool = False,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = details or {}


@dataclass(frozen=True)
class OAuthCallback:
    """Callback result captured by the local OAuth server."""

    code: Optional[str]
    state: Optional[str]
    error: Optional[str] = None
    error_description: Optional[str] = None


@dataclass(frozen=True)
class OAuthLoginResult:
    """Safe metadata for a completed OAuth login."""

    token_path: str
    author_urn: str
    scopes: tuple[str, ...]
    expires_in: Optional[int]
    created_at: str

    def to_safe_dict(self) -> dict[str, Any]:
        """Return JSON-safe metadata without secrets."""
        return {
            "token_saved": True,
            "token_path": self.token_path,
            "author_urn": self.author_urn,
            "scopes": list(self.scopes),
            "expires_in": self.expires_in,
            "created_at": self.created_at,
        }


def generate_state() -> str:
    """Generate an OAuth state value for CSRF protection."""
    return secrets.token_urlsafe(32)


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: Sequence[str],
    state: str,
) -> str:
    """Build a LinkedIn OAuth authorization URL."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": " ".join(scopes),
    }
    return f"{AUTHORIZATION_URL}?{urlencode(params)}"


def wait_for_oauth_callback(*, redirect_uri: str, timeout: int) -> OAuthCallback:
    """Run a one-shot local HTTP server and return the OAuth callback."""
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "localhost"
    port = parsed.port
    path = parsed.path or "/callback"
    if host not in {"localhost", "127.0.0.1"} or port is None:
        raise OAuthFlowError(
            "OAuth redirect URI must be a localhost URL with an explicit port.",
            code="invalid_request",
            details={"redirect_uri": _safe_redirect_uri(redirect_uri)},
        )

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            request_url = urlparse(self.path)
            if request_url.path != path:
                self.send_response(404)
                self.end_headers()
                return
            query = parse_qs(request_url.query)
            self.server.callback = OAuthCallback(  # type: ignore[attr-defined]
                code=_first_query_value(query, "code"),
                state=_first_query_value(query, "state"),
                error=_first_query_value(query, "error"),
                error_description=_first_query_value(query, "error_description"),
            )
            status = 400 if self.server.callback.error else 200  # type: ignore[attr-defined]
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>LinkedIn OAuth complete.</h1>"
                b"<p>You can close this tab and return to the terminal.</p></body></html>"
            )

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = HTTPServer((host, port), CallbackHandler)
    server.callback = None  # type: ignore[attr-defined]
    server.timeout = timeout
    server.handle_request()
    callback = server.callback  # type: ignore[attr-defined]
    server.server_close()
    if callback is None:
        raise OAuthFlowError(
            "Timed out waiting for LinkedIn OAuth callback.",
            code="auth_missing",
            retryable=True,
            details={"timeout_seconds": timeout},
        )
    return callback


def exchange_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    client: Optional[httpx.Client] = None,
) -> dict[str, Any]:
    """Exchange an authorization code for an access token."""
    http = client or httpx.Client(timeout=20.0)
    response = http.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    payload = _json_response(response)
    if response.status_code != 200:
        raise OAuthFlowError(
            _oauth_error_message(payload, fallback="LinkedIn OAuth token exchange failed."),
            code="auth_expired" if response.status_code == 401 else "invalid_request",
            details={"status_code": response.status_code, "error": payload.get("error")},
        )
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise OAuthFlowError(
            "LinkedIn OAuth token response did not include access_token.",
            code="contract_error",
            details={"status_code": response.status_code},
        )
    return payload


def fetch_userinfo(*, access_token: str, client: Optional[httpx.Client] = None) -> dict[str, Any]:
    """Fetch OpenID Connect userinfo for the access token."""
    http = client or httpx.Client(timeout=20.0)
    response = http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    payload = _json_response(response)
    if response.status_code != 200:
        raise OAuthFlowError(
            _oauth_error_message(payload, fallback="LinkedIn userinfo request failed."),
            code="permission_denied" if response.status_code == 403 else "auth_expired",
            details={"status_code": response.status_code, "error": payload.get("error")},
        )
    return payload


def author_urn_from_userinfo(userinfo: dict[str, Any]) -> str:
    """Build a LinkedIn person URN from OpenID Connect userinfo."""
    subject = userinfo.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise OAuthFlowError(
            "LinkedIn userinfo response did not include sub.",
            code="contract_error",
        )
    return f"urn:li:person:{subject.strip()}"


def save_oauth_token(
    *,
    path: Path,
    access_token: str,
    author_urn: str,
    scopes: Sequence[str],
    expires_in: Optional[int],
    linkedin_version: str = DEFAULT_LINKEDIN_VERSION,
) -> OAuthLoginResult:
    """Save LinkedIn OAuth token config without printing the token."""
    token_path = path.expanduser()
    token_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        token_path.parent.chmod(0o700)
    except OSError:
        pass
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {
        "access_token": access_token,
        "author_urn": author_urn,
        "linkedin_version": linkedin_version,
        "scopes": list(scopes),
        "expires_in": expires_in,
        "created_at": created_at,
    }
    token_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    token_path.chmod(0o600)
    return OAuthLoginResult(
        token_path=str(token_path),
        author_urn=author_urn,
        scopes=tuple(scopes),
        expires_in=expires_in,
        created_at=created_at,
    )


def run_oauth_login(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    scopes: Sequence[str],
    token_path: Path,
    linkedin_version: str = DEFAULT_LINKEDIN_VERSION,
    open_browser: bool = True,
    timeout: int = 180,
    announce_url: Optional[Callable[[str], None]] = None,
) -> OAuthLoginResult:
    """Run browser OAuth login, exchange the code, and save the token file."""
    state = generate_state()
    authorization_url = build_authorization_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
        state=state,
    )
    if announce_url:
        announce_url(authorization_url)
    if open_browser:
        webbrowser.open(authorization_url)
    callback = wait_for_oauth_callback(redirect_uri=redirect_uri, timeout=timeout)
    if callback.error:
        raise OAuthFlowError(
            callback.error_description or callback.error,
            code="permission_denied" if callback.error == "access_denied" else "invalid_request",
            details={"error": callback.error},
        )
    if callback.state != state:
        raise OAuthFlowError(
            "LinkedIn OAuth state mismatch. Restart the OAuth login flow.",
            code="auth_expired",
            details={"reason": "state_mismatch"},
        )
    if not callback.code:
        raise OAuthFlowError(
            "LinkedIn OAuth callback did not include an authorization code.",
            code="auth_missing",
        )
    token_payload = exchange_authorization_code(
        client_id=client_id,
        client_secret=client_secret,
        code=callback.code,
        redirect_uri=redirect_uri,
    )
    access_token = str(token_payload["access_token"])
    userinfo = fetch_userinfo(access_token=access_token)
    author_urn = author_urn_from_userinfo(userinfo)
    expires_in = token_payload.get("expires_in")
    return save_oauth_token(
        path=token_path,
        access_token=access_token,
        author_urn=author_urn,
        scopes=scopes,
        expires_in=expires_in if isinstance(expires_in, int) else None,
        linkedin_version=linkedin_version,
    )


def _first_query_value(query: dict[str, list[str]], key: str) -> Optional[str]:
    values = query.get(key)
    if not values:
        return None
    return values[0]


def _json_response(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text[:300]}
    if isinstance(payload, dict):
        return payload
    return {"message": str(payload)[:300]}


def _oauth_error_message(payload: dict[str, Any], *, fallback: str) -> str:
    for key in ("error_description", "message", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _safe_redirect_uri(redirect_uri: str) -> str:
    parsed = urlparse(redirect_uri)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
