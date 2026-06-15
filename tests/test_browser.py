from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from linkedin_cli.browser import _SAVED_POSTS_SCRIPT
from linkedin_cli.browser import _activity_url
from linkedin_cli.browser import _browser_state_path
from linkedin_cli.browser import _chrome_launch_candidates
from linkedin_cli.browser import _load_login_credentials
from linkedin_cli.browser import _looks_auto_login_page
from linkedin_cli.browser import _looks_logged_out
from linkedin_cli.browser import _launch_browser_for
from linkedin_cli.browser import _menu_contains_any
from linkedin_cli.browser import _parse_feed_graphql_payload
from linkedin_cli.browser import _poll_until_logged_in
from linkedin_cli.browser import _save_action_labels
from linkedin_cli.browser import _save_action_selectors
from linkedin_cli.browser import BrowserActionError
from linkedin_cli.browser import LinkedInBrowserFallback


def test_chrome_launch_candidates_prefer_installed_chrome_channel() -> None:
    candidates = _chrome_launch_candidates(headless=True)

    assert candidates[0] == {"channel": "chrome", "headless": True}
    assert candidates[-1] == {"headless": True}


def test_launch_browser_for_wraps_missing_firefox_with_install_hint() -> None:
    class FakeFirefox:
        def launch(self, **_kwargs):
            raise RuntimeError("Executable doesn't exist at /tmp/firefox\nmore detail")

    playwright = SimpleNamespace(firefox=FakeFirefox())
    config = SimpleNamespace(browser=SimpleNamespace(preferred="firefox"))

    with pytest.raises(BrowserActionError) as exc_info:
        _launch_browser_for(playwright, config, headless=True)

    message = str(exc_info.value)
    assert "Unable to launch Firefox" in message
    assert "playwright install firefox" in message
    assert "Executable doesn't exist" in message


def test_unsave_selectors_include_english_and_korean_labels() -> None:
    selectors = _save_action_selectors(False)

    assert any("Unsave" in selector for selector in selectors)
    assert any("저장 취소" in selector for selector in selectors)
    assert any("저장 해제" in selector for selector in selectors)
    assert "저장 취소" in _save_action_labels(False)


def test_save_selectors_include_english_and_korean_labels() -> None:
    selectors = _save_action_selectors(True)

    assert any("Save" in selector for selector in selectors)
    assert any("저장" in selector for selector in selectors)
    assert "저장" in _save_action_labels(True)


def test_looks_logged_out_detects_linkedin_login_wall() -> None:
    assert _looks_logged_out(
        "https://www.linkedin.com/feed/update/urn:li:activity:1/",
        "댓글을 보거나 남기려면 로그인",
    )
    assert _looks_logged_out("https://www.linkedin.com/login/", "")
    assert not _looks_logged_out(
        "https://www.linkedin.com/feed/update/urn:li:activity:1/",
        "Sangjin Lim님의 업데이트 추천 댓글 공유",
    )


def test_looks_auto_login_page_detects_linkedin_countdown() -> None:
    assert _looks_auto_login_page("로그인중 이 페이지에 남아 있을 경우 로그인됩니다.")
    assert _looks_auto_login_page("You will be signed in if you stay on this page.")
    assert not _looks_auto_login_page("이메일 또는 전화 비밀번호 로그인")


def test_browser_state_path_honors_env(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("LINKEDIN_BROWSER_STATE", str(state_path))

    assert _browser_state_path() == state_path


def test_load_login_credentials_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("LINKEDIN_USERNAME", "user@example.com")
    monkeypatch.setenv("LINKEDIN_PASSWORD", "secret")

    credentials = _load_login_credentials("firefox")

    assert credentials is not None
    assert credentials.username == "user@example.com"
    assert credentials.password == "secret"
    assert credentials.source == "LINKEDIN_USERNAME/LINKEDIN_PASSWORD"


def test_type_first_uses_keyboard_insert_text() -> None:
    events = []

    class FakeTarget:
        def wait_for(self, **kwargs):
            events.append(("wait_for", kwargs["state"]))

        def click(self, **_kwargs):
            events.append(("click",))

    class FakeLocator:
        def count(self):
            return 1

        def nth(self, index):
            assert index == 0
            return FakeTarget()

    class FakeKeyboard:
        def press(self, key):
            events.append(("press", key))

        def insert_text(self, value):
            events.append(("insert_text", value))

    class FakePage:
        keyboard = FakeKeyboard()

        def locator(self, selector):
            assert selector == "input[name='session_password']"
            return FakeLocator()

    subject = SimpleNamespace(config=SimpleNamespace(rate_limit=SimpleNamespace(timeout=20)))

    LinkedInBrowserFallback._type_first(
        subject,
        FakePage(),
        ["input[name='session_password']"],
        "secret",
    )

    assert events == [
        ("wait_for", "visible"),
        ("click",),
        ("press", "ControlOrMeta+A"),
        ("press", "Backspace"),
        ("insert_text", "secret"),
    ]


def test_activity_url_handles_compound_and_bare_identifiers() -> None:
    assert (
        _activity_url("urn:li:fsd_update:(urn:li:activity:55,FEED)")
        == "https://www.linkedin.com/feed/update/urn:li:activity:55/"
    )
    assert (
        _activity_url("urn:li:activity:99")
        == "https://www.linkedin.com/feed/update/urn:li:activity:99/"
    )
    assert _activity_url("https://www.linkedin.com/feed/update/urn:li:activity:7/") == (
        "https://www.linkedin.com/feed/update/urn:li:activity:7/"
    )


def test_saved_posts_script_anchors_on_activity_href_not_main_li() -> None:
    # The scrape must anchor on the durable activity permalink and walk up via
    # closest(), not pin the brittle `main li` DOM path.
    assert 'a[href*="/feed/update/urn:li:activity:"]' in _SAVED_POSTS_SCRIPT
    assert ".closest(" in _SAVED_POSTS_SCRIPT
    assert "main li" not in _SAVED_POSTS_SCRIPT


class _FakePollPage:
    def __init__(self, url: str, body: str) -> None:
        self.url = url
        self._body = body
        self.waits: list[int] = []

    def locator(self, selector: str):
        assert selector == "body"
        return SimpleNamespace(inner_text=lambda timeout=3000: self._body)

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)


def test_poll_until_logged_in_returns_immediately_when_authed() -> None:
    page = _FakePollPage("https://www.linkedin.com/feed/", "내 네트워크 피드")

    assert _poll_until_logged_in(page, timeout=5.0) is True
    assert page.waits == []  # no polling delay once the session is recognized


def test_poll_until_logged_in_times_out_while_logged_out(monkeypatch) -> None:
    ticks = iter([0.0, 0.0, 100.0, 100.0])
    monkeypatch.setattr("linkedin_cli.browser.time.monotonic", lambda: next(ticks))
    page = _FakePollPage("https://www.linkedin.com/login/", "")

    assert _poll_until_logged_in(page, timeout=5.0) is False
    assert page.waits == [2000]  # polled once before the deadline elapsed


def test_complete_remember_me_profile_selection_saves_state(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("LINKEDIN_BROWSER_STATE", str(state_path))
    events = []

    class FakeProfileButton:
        def wait_for(self, **kwargs):
            events.append(("wait_for", kwargs["state"]))

        def click(self, **_kwargs):
            events.append(("click",))

    class FakeLocator:
        first = FakeProfileButton()

    class FakePage:
        url = "https://www.linkedin.com/uas/login"

        def locator(self, selector):
            assert selector in {"button.member-profile__details", "body"}
            if selector == "body":
                return SimpleNamespace(inner_text=lambda timeout=3000: "Feed")
            return FakeLocator()

        def wait_for_url(self, pattern, **_kwargs):
            assert pattern == "**/feed/**"
            self.url = "https://www.linkedin.com/feed/"

        def wait_for_timeout(self, ms):
            events.append(("wait", ms))

    class FakeContext:
        def storage_state(self, *, path):
            Path(path).write_text('{"cookies": []}', encoding="utf-8")

    subject = SimpleNamespace(config=SimpleNamespace(rate_limit=SimpleNamespace(timeout=20)))

    assert LinkedInBrowserFallback._complete_remember_me_if_available(
        subject,
        FakePage(),
        target_url="https://www.linkedin.com/feed/",
        context=FakeContext(),
    )
    assert ("click",) in events
    assert state_path.exists()
    assert (state_path.stat().st_mode & 0o777) == 0o600


def test_parse_feed_graphql_payload_returns_normalizable_posts() -> None:
    payload = {
        "included": [
            {
                "entityUrn": "urn:li:activity:7441619761081294848",
                "commentary": {"text": {"text": "LinkedIn browser-context feed post"}},
                "createdAt": 1710000000000,
                "actor": {
                    "entityUrn": "urn:li:fsd_profile:1",
                    "name": {"text": "Jane Doe"},
                    "subDescription": {"text": "AI Engineer"},
                },
                "*socialDetail": "urn:li:fsd_socialDetail:1",
            },
            {
                "entityUrn": "urn:li:fsd_socialDetail:1",
                "*totalSocialActivityCounts": "urn:li:fsd_counts:1",
            },
            {
                "entityUrn": "urn:li:fsd_counts:1",
                "numLikes": 7,
                "numComments": 2,
                "numShares": 1,
            },
        ]
    }

    posts = _parse_feed_graphql_payload(payload)

    assert posts == [
        {
            "entityUrn": "urn:li:activity:7441619761081294848",
            "url": "https://www.linkedin.com/feed/update/urn:li:activity:7441619761081294848/",
            "commentary": {"text": "LinkedIn browser-context feed post"},
            "author_name": "Jane Doe",
            "headline": "AI Engineer",
            "actor": payload["included"][0]["actor"],
            "createdAt": "2024-03-09T16:00:00+00:00",
            "reactionCount": 7,
            "commentCount": 2,
            "shareCount": 1,
        }
    ]


def test_browser_feed_posts_uses_graphql_fetch(monkeypatch) -> None:
    payload = {
        "included": [
            {
                "entityUrn": "urn:li:activity:7441619761081294848",
                "commentary": {"text": {"text": "LinkedIn browser-context feed post"}},
                "actor": {"name": {"text": "Jane Doe"}},
            }
        ]
    }
    seen = []

    class FakeOpenPage:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    subject = object.__new__(LinkedInBrowserFallback)
    subject._open_page = lambda url: seen.append(url) or FakeOpenPage()
    monkeypatch.setattr("linkedin_cli.browser._fetch_feed_graphql", lambda *_args, **_kwargs: payload)

    posts = subject.get_feed_posts(1)

    assert seen == ["https://www.linkedin.com/feed/"]
    assert posts[0]["commentary"] == {"text": "LinkedIn browser-context feed post"}


def test_menu_contains_any_uses_exact_visible_menu_labels() -> None:
    class FakeLocator:
        def evaluate_all(self, _script):
            return ["저장", "링크 복사"]

    class FakePage:
        def locator(self, selector):
            assert selector == "[role='menuitem']"
            return FakeLocator()

    assert _menu_contains_any(FakePage(), ["저장"])
    assert not _menu_contains_any(FakePage(), ["저장 취소"])
