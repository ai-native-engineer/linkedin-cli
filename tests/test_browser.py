from __future__ import annotations

from pathlib import Path

from linkedin_cli.browser import _browser_state_path
from linkedin_cli.browser import _chrome_launch_candidates
from linkedin_cli.browser import _load_login_credentials
from linkedin_cli.browser import _looks_auto_login_page
from linkedin_cli.browser import _looks_logged_out
from linkedin_cli.browser import _menu_contains_any
from linkedin_cli.browser import _save_action_labels
from linkedin_cli.browser import _save_action_selectors


def test_chrome_launch_candidates_prefer_installed_chrome_channel() -> None:
    candidates = _chrome_launch_candidates(headless=True)

    assert candidates[0] == {"channel": "chrome", "headless": True}
    assert candidates[-1] == {"headless": True}


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
