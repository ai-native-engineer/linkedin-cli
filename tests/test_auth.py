from __future__ import annotations

import json
from types import SimpleNamespace

from linkedin_cli.auth import _auth_session_from_playwright_cookies
from linkedin_cli.auth import _load_from_browser_state
from linkedin_cli.auth import write_browser_state_file


def _fake_config(*, preferred: str = "chrome", proxy: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        browser=SimpleNamespace(preferred=preferred),
        runtime=SimpleNamespace(proxy=proxy),
    )


def test_playwright_cookies_build_full_linkedin_session() -> None:
    cookies = [
        {"name": "li_at", "value": "AAA", "domain": ".linkedin.com", "path": "/"},
        {"name": "JSESSIONID", "value": '"ajax:123"', "domain": ".linkedin.com", "path": "/"},
        {"name": "bcookie", "value": "v=2&xyz", "domain": ".linkedin.com", "path": "/"},
        {"name": "lidc", "value": "b=db", "domain": ".linkedin.com", "path": "/"},
    ]

    session = _auth_session_from_playwright_cookies(cookies, config=_fake_config())

    assert session is not None
    assert session.source == "browser-login"
    assert session.browser == "chrome"
    assert session.has_required_cookies()
    # Keeps the full jar (not just the two required cookies) — Voyager needs it.
    assert set(session.cookie_names) >= {"li_at", "JSESSIONID", "bcookie", "lidc"}
    assert session.li_at == "AAA"
    assert session.jsessionid == "ajax:123"  # property strips quotes for the csrf-token header


def test_playwright_cookies_requote_unquoted_jsessionid() -> None:
    cookies = [
        {"name": "li_at", "value": "AAA", "domain": ".linkedin.com"},
        {"name": "JSESSIONID", "value": "ajax:123", "domain": ".linkedin.com"},
    ]

    session = _auth_session_from_playwright_cookies(cookies, config=_fake_config())

    assert session is not None
    # The Cookie header must carry the quoted ajax token Voyager issues.
    assert 'JSESSIONID="ajax:123"' in session.cookie_string


def test_playwright_cookies_drop_non_linkedin_domain() -> None:
    cookies = [
        {"name": "li_at", "value": "AAA", "domain": ".linkedin.com"},
        {"name": "JSESSIONID", "value": '"ajax:123"', "domain": ".linkedin.com"},
        {"name": "sid", "value": "evil", "domain": ".example.com"},
    ]

    session = _auth_session_from_playwright_cookies(cookies, config=_fake_config())

    assert session is not None
    assert "sid" not in session.cookie_names


def test_playwright_cookies_missing_required_returns_none() -> None:
    cookies = [
        {"name": "bcookie", "value": "v=2", "domain": ".linkedin.com"},
        {"name": "lidc", "value": "b=db", "domain": ".linkedin.com"},
    ]

    assert _auth_session_from_playwright_cookies(cookies, config=_fake_config()) is None


def test_browser_state_file_builds_session(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "browser-state.json"
    state_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "li_at", "value": "AAA", "domain": ".linkedin.com", "path": "/"},
                    {"name": "JSESSIONID", "value": "ajax:123", "domain": ".linkedin.com", "path": "/"},
                    {"name": "bcookie", "value": "v=2&xyz", "domain": ".linkedin.com", "path": "/"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LINKEDIN_BROWSER_STATE", str(state_path))

    session = _load_from_browser_state(config=_fake_config(preferred="chrome"))

    assert session is not None
    assert session.source == "browser-state"
    assert session.cookie_count == 3
    assert session.cookie_jar.get("JSESSIONID") == '"ajax:123"'


def test_write_browser_state_file_preserves_cookie_metadata(tmp_path) -> None:
    cookies = [
        {
            "name": "li_at",
            "value": "AAA",
            "domain": ".www.linkedin.com",
            "path": "/feed",
            "expires": 1_900_000_000,
        },
        {"name": "JSESSIONID", "value": "ajax:123", "domain": ".linkedin.com", "path": "/"},
    ]
    session = _auth_session_from_playwright_cookies(cookies, config=_fake_config())
    assert session is not None

    state_path = tmp_path / "browser-state.json"
    summary = write_browser_state_file(state_path, session)

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert summary["path"] == str(state_path)
    assert (state_path.stat().st_mode & 0o777) == 0o600
    assert payload["origins"] == []
    assert payload["cookies"][0]["domain"] == ".www.linkedin.com"
    assert payload["cookies"][0]["path"] == "/feed"
    assert payload["cookies"][0]["expires"] == 1_900_000_000
    assert payload["cookies"][1]["value"] == '"ajax:123"'
