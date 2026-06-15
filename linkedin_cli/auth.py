"""Authentication helpers for linkedin-cli."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
from typing import Any
from typing import Iterable

from linkedin_api import Linkedin
from requests.cookies import create_cookie
from requests.cookies import RequestsCookieJar

from .config import AppConfig
from .constants import COOKIE_REQUIRED_NAMES
from .constants import DEFAULT_COOKIE_FILE
from .constants import ENV_BROWSER
from .constants import ENV_COOKIE_FILE
from .constants import ENV_COOKIE_HEADER
from .constants import ENV_JSESSIONID
from .constants import ENV_LI_AT
from .constants import SUPPORTED_BROWSERS

_LINKEDIN_DOMAINS = {
    "linkedin.com",
    ".linkedin.com",
    "www.linkedin.com",
    ".www.linkedin.com",
}


class AuthenticationError(RuntimeError):
    """Raised when a usable LinkedIn session cannot be resolved."""


@dataclass
class AuthSession:
    """Resolved LinkedIn auth cookies and metadata."""

    cookie_jar: RequestsCookieJar
    source: str
    browser: str | None = None
    proxy: str | None = None

    @property
    def li_at(self) -> str:
        return _first_cookie_value(self.cookie_jar, "li_at")

    @property
    def jsessionid(self) -> str:
        return _first_cookie_value(self.cookie_jar, "JSESSIONID").strip('"')

    @property
    def cookie_string(self) -> str:
        pairs = []
        for cookie in self.cookie_jar:
            pairs.append(f"{cookie.name}={cookie.value}")
        return "; ".join(pairs)

    @property
    def cookie_count(self) -> int:
        return sum(1 for _ in self.cookie_jar)

    @property
    def cookie_names(self) -> list[str]:
        return sorted({cookie.name for cookie in self.cookie_jar})

    def has_required_cookies(self) -> bool:
        return _has_required_cookies(self.cookie_jar)

    def as_playwright_cookies(self) -> list[dict[str, object]]:
        cookies = []
        for cookie in self.cookie_jar:
            cookies.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain or ".linkedin.com",
                    "path": cookie.path or "/",
                    "httpOnly": bool(cookie._rest.get("HttpOnly")),
                    "secure": bool(cookie.secure),
                    "sameSite": "Lax",
                }
            )
        return cookies


def resolve_auth_session(config: AppConfig) -> AuthSession:
    """Load LinkedIn cookies from env or browser storage."""
    env_header_session = _load_from_cookie_header(config)
    if env_header_session is not None:
        return env_header_session

    env_session = _load_from_env(config)
    if env_session is not None:
        return env_session

    file_session = _load_from_cookie_file(config)
    if file_session is not None:
        return file_session

    browser_session = _load_from_browser(config)
    if browser_session is not None:
        return browser_session

    raise AuthenticationError(
        "No LinkedIn cookies found. Set LINKEDIN_COOKIE_HEADER, run `linkedin-cli auth "
        "cookie-file --from-stdin`, set LINKEDIN_LI_AT/LINKEDIN_JSESSIONID, or log into "
        "linkedin.com in a supported browser."
    )


def default_cookie_file_path() -> Path:
    """Return the default private cookie env-file path."""
    return Path(DEFAULT_COOKIE_FILE).expanduser()


def summarize_cookie_header(raw_header: str) -> dict[str, Any]:
    """Summarize a Cookie header without exposing cookie values."""
    parsed = _parse_cookie_header(raw_header.strip())
    names = sorted(parsed)
    missing = sorted(name for name in COOKIE_REQUIRED_NAMES if name not in parsed)
    return {
        "cookie_count": len(parsed),
        "cookie_names": names,
        "required_missing": missing,
    }


def write_cookie_header_file(path: Path, raw_header: str) -> dict[str, Any]:
    """Write a full Cookie header to a private env file and return a sanitized summary."""
    normalized = raw_header.strip()
    summary = summarize_cookie_header(normalized)
    if summary["required_missing"]:
        missing = ", ".join(summary["required_missing"])
        raise AuthenticationError(f"Cookie header is missing required cookies: {missing}.")

    resolved = path.expanduser()
    parent = resolved.parent
    parent_existed = parent.exists()
    parent.mkdir(parents=True, exist_ok=True)
    if not parent_existed:
        # Tighten only a directory we just created; never re-permission a pre-existing
        # (possibly system-owned) directory such as /tmp, which would raise PermissionError.
        try:
            parent.chmod(0o700)
        except OSError:
            pass
    rendered = (
        "# linkedin-cli read-session cookies. Keep this file private.\n"
        f"{ENV_COOKIE_HEADER}={shlex.quote(normalized)}\n"
    )
    resolved.write_text(rendered, encoding="utf-8")
    resolved.chmod(0o600)
    return {
        **summary,
        "path": str(resolved),
    }


def build_api_client(session: AuthSession, config: AppConfig):
    """Create the unofficial LinkedIn Voyager client from resolved cookies."""
    proxies = {}
    if config.runtime.proxy:
        proxies = {
            "http": config.runtime.proxy,
            "https": config.runtime.proxy,
        }
    return Linkedin(
        "",
        "",
        authenticate=True,
        cookies=session.cookie_jar,
        proxies=proxies,
    )


def validate_auth_session(session: AuthSession, config: AppConfig) -> dict[str, Any]:
    """Perform a lightweight profile request using the resolved cookies."""
    from .transport import LinkedInTransport

    try:
        payload = LinkedInTransport(session, config).get_me()
    except Exception as exc:  # pragma: no cover - depends on live cookies/network
        raise AuthenticationError(f"LinkedIn auth validation failed: {exc}") from exc
    if not isinstance(payload, dict) or not payload:
        raise AuthenticationError("LinkedIn auth validation failed: empty profile payload.")
    return payload


def inspect_auth_session(session: AuthSession, config: AppConfig) -> dict[str, Any]:
    """Run the basic auth read without collapsing diagnostics into a generic error."""
    from .transport import LinkedInRedirectError
    from .transport import LinkedInTransport
    from .transport import LinkedInTransportError

    try:
        payload = LinkedInTransport(session, config).get_me()
    except LinkedInRedirectError as exc:
        return {
            "ok": False,
            "kind": exc.details.reason,
            "error": _sanitize_error(exc),
            "status_code": exc.details.status_code,
            "location": exc.details.location,
            "url": exc.details.url,
        }
    except LinkedInTransportError as exc:
        return {
            "ok": False,
            "kind": "transport-error",
            "error": _sanitize_error(exc),
        }
    except Exception as exc:  # pragma: no cover - depends on live cookies/network
        return {
            "ok": False,
            "kind": exc.__class__.__name__.replace("_", "-").lower(),
            "error": _sanitize_error(exc),
        }
    if not isinstance(payload, dict) or not payload:
        return {
            "ok": False,
            "kind": "invalid-payload",
            "error": "LinkedIn returned an empty profile payload.",
        }
    return {
        "ok": True,
        "kind": "profile-read",
        "payload": payload,
    }


def probe_read_access(
    session: AuthSession,
    config: AppConfig,
    *,
    public_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Run non-following probes against Voyager endpoints for diagnostics."""
    from .transport import LinkedInTransport

    transport = LinkedInTransport(session, config)
    checks = {
        "voyager_me": ("/me", {}),
        "voyager_feed": (
            "/feed/updatesV2",
            {
                "params": {"count": "1", "q": "chronFeed"},
                "headers": {"accept": "application/vnd.linkedin.normalized+json+2.1"},
            },
        ),
    }

    results: dict[str, dict[str, Any]] = {}
    for name, (uri, kwargs) in checks.items():
        try:
            results[name] = transport.probe(
                uri,
                params=kwargs.get("params"),
                headers=kwargs.get("headers"),
            )
            if "headers" in kwargs:
                results[name]["headers_used"] = list(kwargs["headers"].keys())
        except Exception as exc:  # pragma: no cover - live network behavior
            results[name] = {
                "ok": False,
                "kind": exc.__class__.__name__.replace("_", "-").lower(),
                "error": _sanitize_error(exc),
            }
    if public_id:
        try:
            results["voyager_profile"] = transport.probe_profile(public_id)
        except Exception as exc:  # pragma: no cover - live network behavior
            results["voyager_profile"] = {
                "ok": False,
                "kind": exc.__class__.__name__.replace("_", "-").lower(),
                "error": _sanitize_error(exc),
            }
    return results


def collect_auth_diagnostics(config: AppConfig) -> dict[str, Any]:
    """Resolve the current auth session and return diagnostic details."""
    session = resolve_auth_session(config)
    if not session.has_required_cookies():
        raise AuthenticationError("LinkedIn session is missing required cookies.")

    validation = inspect_auth_session(session, config)
    payload = validation.get("payload", {}) if validation.get("ok") else {}
    public_id, full_name = _extract_identity(payload)
    probes = probe_read_access(session, config, public_id=public_id or None)
    probes_ok = all(result.get("ok") for result in probes.values())
    return {
        "ok": bool(validation.get("ok")) and probes_ok,
        "source": session.source,
        "browser": session.browser,
        "cookie_count": session.cookie_count,
        "cookie_names": session.cookie_names,
        "public_id": public_id,
        "full_name": full_name,
        "validation": {
            "ok": bool(validation.get("ok")),
            "kind": validation.get("kind", ""),
            "error": validation.get("error", ""),
            "status_code": validation.get("status_code"),
            "location": validation.get("location"),
        },
        "probes": probes,
        "hint": _build_auth_hint(session, validation, probes),
    }


def _extract_identity(payload: dict[str, Any]) -> tuple[str, str]:
    mini_profile = payload.get("miniProfile", {}) if isinstance(payload, dict) else {}
    public_id = (
        mini_profile.get("publicIdentifier")
        or payload.get("plainId")
        or payload.get("publicIdentifier")
        or ""
    )
    full_name = " ".join(
        part for part in [payload.get("firstName", ""), payload.get("lastName", "")] if part
    ).strip()
    return public_id, full_name


def _build_auth_hint(
    session: AuthSession,
    validation: dict[str, Any],
    probes: dict[str, dict[str, Any]],
) -> str:
    redirect_reasons = {
        "redirect",
        "self-redirect-loop",
        "login",
        "checkpoint",
        "authwall",
        "challenge",
    }
    saw_redirects = validation.get("kind") in redirect_reasons or any(
        result.get("reason") in redirect_reasons for result in probes.values()
    )
    if not saw_redirects:
        if validation.get("ok") and all(result.get("ok") for result in probes.values()):
            return ""
        return "Basic auth did not complete cleanly. Review the probe details above."
    if session.cookie_count <= len(COOKIE_REQUIRED_NAMES):
        return (
            "Only the minimum cookies are loaded. LinkedIn often requires a fuller linkedin.com "
            "cookie jar. Try LINKEDIN_COOKIE_HEADER with the full Cookie header or browser extraction."
        )
    return (
        "LinkedIn is redirecting authenticated reads even with the current cookie jar. "
        "This usually means authwall/checkpoint behavior or missing browser-like request context."
    )


def _sanitize_error(exc: Exception) -> str:
    """Stringify an exception without leaking cookie values into diagnostics or logs."""
    text = str(exc)
    lowered = text.lower()
    if "li_at=" in lowered or "jsessionid=" in lowered or "linkedin_cookie_header" in lowered:
        return f"{exc.__class__.__name__}: request failed (cookie header redacted)"
    return text


def _load_from_cookie_header(config: AppConfig) -> AuthSession | None:
    raw_header = os.getenv(ENV_COOKIE_HEADER, "").strip()
    if not raw_header:
        return None
    return _auth_session_from_cookie_header(raw_header, source="env-cookie-header", config=config)


def _load_from_cookie_file(config: AppConfig) -> AuthSession | None:
    path, explicit = _resolve_cookie_file_path()
    if not path.exists():
        if explicit:
            raise AuthenticationError(f"{ENV_COOKIE_FILE} points to a missing file: {path}")
        return None
    try:
        raw_header = _read_cookie_header_file(path)
    except OSError as exc:
        raise AuthenticationError(f"Could not read {ENV_COOKIE_FILE} file: {path}") from exc
    if not raw_header:
        raise AuthenticationError(
            f"Cookie file does not contain {ENV_COOKIE_HEADER} or a raw Cookie header: {path}"
        )
    return _auth_session_from_cookie_header(raw_header, source="cookie-file", config=config)


def _auth_session_from_cookie_header(
    raw_header: str,
    *,
    source: str,
    config: AppConfig,
) -> AuthSession:
    jar = RequestsCookieJar()
    for name, value in _parse_cookie_header(raw_header).items():
        jar.set(
            name,
            value,
            domain=".linkedin.com",
            path="/",
        )
    if not _has_required_cookies(jar):
        raise AuthenticationError(
            f"{ENV_COOKIE_HEADER} was provided but does not include li_at and JSESSIONID."
        )
    return AuthSession(cookie_jar=jar, source=source, proxy=config.runtime.proxy)


def _resolve_cookie_file_path() -> tuple[Path, bool]:
    raw_path = os.getenv(ENV_COOKIE_FILE, "").strip()
    if raw_path:
        return Path(raw_path).expanduser(), True
    return default_cookie_file_path(), False


def _read_cookie_header_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return ""
    # Prefer an explicit LINKEDIN_COOKIE_HEADER= assignment (the format write_cookie_header_file
    # produces). Checking this before the raw-text branch avoids returning the whole file —
    # comment line + assignment wrapper — which would become an invalid multi-line Cookie header.
    for line in text.splitlines():
        value = _extract_cookie_header_assignment(line)
        if value and not summarize_cookie_header(value)["required_missing"]:
            return value
    # Fall back to a single-line raw Cookie header (no comments or assignment wrapping).
    if "\n" not in text and not summarize_cookie_header(text)["required_missing"]:
        return text
    return ""


def _extract_cookie_header_assignment(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    try:
        tokens = shlex.split(stripped, comments=False, posix=True)
    except ValueError:
        return None
    if tokens and tokens[0] == "export":
        tokens = tokens[1:]
    prefix = f"{ENV_COOKIE_HEADER}="
    for token in tokens:
        if token.startswith(prefix):
            return token.split("=", 1)[1].strip()
    return None


def _load_from_env(config: AppConfig) -> AuthSession | None:
    li_at = os.getenv(ENV_LI_AT, "").strip()
    jsessionid = os.getenv(ENV_JSESSIONID, "").strip()
    if not li_at or not jsessionid:
        return None

    jar = RequestsCookieJar()
    jar.set("li_at", li_at, domain=".linkedin.com", path="/")
    jar.set("JSESSIONID", _normalize_jsessionid(jsessionid), domain=".linkedin.com", path="/")
    return AuthSession(cookie_jar=jar, source="env", proxy=config.runtime.proxy)


def _normalize_jsessionid(value: str) -> str:
    """Keep the quotes LinkedIn issues around JSESSIONID, whether or not the user typed them.

    LinkedIn serves JSESSIONID as `"ajax:..."` (quoted) and the cookie value must match, while
    the csrf-token header uses the unquoted form (see AuthSession.jsessionid). Accepting an
    unquoted env value and re-adding the quotes prevents a silent redirect-reject.
    """
    value = value.strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value
    return f'"{value}"'


def _browser_cookie_loaders() -> dict[str, Any]:
    import browser_cookie3

    return {
        "chrome": browser_cookie3.chrome,
        "chromium": browser_cookie3.chromium,
        "brave": browser_cookie3.brave,
        "edge": browser_cookie3.edge,
        "firefox": browser_cookie3.firefox,
    }


def _run_browser_logins(
    loaders: dict[str, Any], config: AppConfig
) -> tuple[AuthSession | None, list[dict[str, str]]]:
    """Try each browser in preference order; return the first session and any attempt errors."""
    browser_preference = os.getenv(ENV_BROWSER, "").strip().lower() or config.browser.preferred
    attempts: list[dict[str, str]] = []
    for browser in _ordered_browser_names(browser_preference):
        loader = loaders.get(browser)
        if loader is None:
            continue
        try:
            jar = loader()
        except Exception as exc:  # pragma: no cover - depends on local browser state
            attempts.append({"browser": browser, "error": _describe_browser_error(browser, exc)})
            continue
        session = _session_from_cookie_jar(
            jar,
            source="browser",
            browser=browser,
            proxy=config.runtime.proxy,
        )
        if session is not None:
            return session, attempts
        attempts.append(
            {
                "browser": browser,
                "error": "logged into this browser, but no linkedin.com session (li_at + JSESSIONID) found",
            }
        )
    return None, attempts


def _load_from_browser(config: AppConfig) -> AuthSession | None:
    try:
        loaders = _browser_cookie_loaders()
    except ImportError as exc:  # pragma: no cover - dependency guarded by packaging
        raise AuthenticationError(
            "browser-cookie3 is required for browser cookie extraction."
        ) from exc
    session, _ = _run_browser_logins(loaders, config)
    return session


def try_browser_login(config: AppConfig) -> tuple[AuthSession | None, list[dict[str, str]]]:
    """Extract a LinkedIn session from a logged-in browser, surfacing per-browser failures.

    Unlike _load_from_browser (which swallows errors for the resolve chain), this reports
    why each browser failed so `auth login` can give actionable guidance. Never returns or
    logs cookie values.
    """
    try:
        loaders = _browser_cookie_loaders()
    except ImportError:
        return None, [
            {
                "browser": "-",
                "error": "browser-cookie3 is not installed; reinstall agent-linkedin or use manual cookie capture",
            }
        ]
    return _run_browser_logins(loaders, config)


def _describe_browser_error(browser: str, exc: Exception) -> str:
    """Map a browser_cookie3 failure to an actionable hint. Never includes cookie values."""
    text = str(exc).lower()
    if "keychain" in text or "safe storage" in text or "securityerror" in text:
        return (
            f"{browser}: macOS Keychain access was denied or unavailable. "
            "Re-run and click Allow on the Keychain prompt, or try --browser firefox."
        )
    if "lock" in text or "operationalerror" in text:
        return f"{browser}: cookie database is locked. Quit {browser} and retry."
    if "decrypt" in text or "encrypt" in text:
        return (
            f"{browser}: cookie decryption failed (newer browser encryption). "
            "Try --browser firefox or capture cookies manually."
        )
    return f"{browser}: extraction failed ({exc.__class__.__name__})."


def _ordered_browser_names(preferred: str) -> Iterable[str]:
    if preferred and preferred in SUPPORTED_BROWSERS:
        yield preferred
    for browser in SUPPORTED_BROWSERS:
        if browser != preferred:
            yield browser


def _session_from_cookie_jar(
    jar: RequestsCookieJar,
    *,
    source: str,
    browser: str | None,
    proxy: str | None,
) -> AuthSession | None:
    linkedin_jar = RequestsCookieJar()
    for cookie in jar:
        if not _is_linkedin_domain(cookie.domain or ""):
            continue
        _copy_cookie(linkedin_jar, cookie)
    if _has_required_cookies(linkedin_jar):
        return AuthSession(
            cookie_jar=linkedin_jar,
            source=source,
            browser=browser,
            proxy=proxy,
        )
    return None


def _copy_cookie(target: RequestsCookieJar, cookie) -> None:
    target.set_cookie(
        create_cookie(
            name=cookie.name,
            value=cookie.value,
            domain=cookie.domain or ".linkedin.com",
            path=cookie.path or "/",
            secure=bool(cookie.secure),
            expires=getattr(cookie, "expires", None),
            rest=dict(getattr(cookie, "_rest", {})),
        )
    )


def _has_required_cookies(jar: RequestsCookieJar) -> bool:
    names = {cookie.name for cookie in jar}
    return all(name in names for name in COOKIE_REQUIRED_NAMES)


def _first_cookie_value(jar: RequestsCookieJar, name: str) -> str:
    for cookie in jar:
        if cookie.name == name:
            return str(cookie.value or "")
    return ""


def _is_linkedin_domain(domain: str) -> bool:
    if domain in _LINKEDIN_DOMAINS:
        return True
    return domain.endswith(".linkedin.com")


def _parse_cookie_header(raw_header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for segment in raw_header.split(";"):
        item = segment.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        cookies[name] = value
    return cookies
