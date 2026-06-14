"""Playwright-based fallback automation for fragile LinkedIn write flows."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Iterable

from .auth import AuthSession
from .config import AppConfig
from .constants import ENV_BROWSER_STATE
from .constants import ENV_PASSWORD
from .constants import ENV_USERNAME


class BrowserActionError(RuntimeError):
    """Raised when browser fallback cannot complete an action."""


@dataclass(frozen=True)
class BrowserActionResult:
    """Simple browser mutation outcome."""

    success: bool
    detail: str


@dataclass(frozen=True)
class BrowserLoginCredentials:
    """Credentials used only in-memory to recover an expired browser session."""

    username: str
    password: str
    source: str


class LinkedInBrowserFallback:
    """Execute LinkedIn mutations through the browser when HTTP flows are unavailable."""

    def __init__(self, auth_session: AuthSession, config: AppConfig) -> None:
        self.auth_session = auth_session
        self.config = config

    def create_post(self, text: str, visibility: str) -> BrowserActionResult:
        with self._open_page("https://www.linkedin.com/feed/") as page:
            self._click_first(
                page,
                [
                    "button:has-text('Start a post')",
                    "[aria-label*='Start a post']",
                    "button.share-box-feed-entry__trigger",
                ],
            )
            composer = self._locator_for(
                page,
                ["[role='dialog'] [contenteditable='true']", "div[contenteditable='true']"],
            )
            composer.click()
            page.keyboard.type(text)
            if visibility and visibility != "connections":
                self._set_visibility(page, visibility)
            self._pause_for_write()
            self._click_first(
                page,
                [
                    "[role='dialog'] button:has-text('Post')",
                    "button.share-actions__primary-action",
                ],
            )
        return BrowserActionResult(True, "Post created through browser fallback.")

    def comment_on_post(self, activity_identifier: str, text: str) -> BrowserActionResult:
        with self._open_page(_activity_url(activity_identifier)) as page:
            self._click_first(
                page,
                [
                    "button[aria-label*='Comment']",
                    "button:has-text('Comment')",
                ],
                optional=True,
            )
            editor = self._locator_for(
                page,
                [
                    "form.comments-comment-box__form [contenteditable='true']",
                    ".comments-comment-box__form-container [contenteditable='true']",
                    "[role='textbox'][contenteditable='true']",
                ],
            )
            editor.click()
            page.keyboard.type(text)
            self._pause_for_write()
            self._click_first(
                page,
                [
                    "button.comments-comment-box__submit-button--cr",
                    "button:has-text('Post comment')",
                    "button:has-text('Comment')",
                ],
            )
        return BrowserActionResult(True, "Comment posted through browser fallback.")

    def get_saved_posts(self, count: int) -> list[dict[str, object]]:
        with self._open_page("https://www.linkedin.com/my-items/saved-posts/") as page:
            page.wait_for_timeout(2000)
            self._scroll_until_saved_count(page, count)
            posts = page.evaluate(_SAVED_POSTS_SCRIPT, count)
            if not isinstance(posts, list):
                raise BrowserActionError("LinkedIn saved posts page returned an unexpected payload.")
            return [post for post in posts if isinstance(post, dict)]

    def toggle_save(self, activity_identifier: str, should_save: bool) -> BrowserActionResult:
        with self._open_page(_activity_url(activity_identifier)) as page:
            self._click_first(
                page,
                [
                    "button[aria-label*='More actions']",
                    "button[aria-label*='업데이트 메뉴 더보기']",
                    "button[aria-label*='더보기']",
                    "button[aria-label*='관리 메뉴 열기']",
                    "button.feed-shared-control-menu__trigger",
                    "button[aria-label*='Open control menu']",
                ],
            )
            labels = _wait_for_menu_labels(page, timeout=self.config.rate_limit.timeout)
            if _click_visible_menu_label(page, _save_action_labels(should_save), labels):
                verb = "saved" if should_save else "removed from saved items"
                return BrowserActionResult(True, f"Post {verb} through browser fallback.")

            if any(label in labels for label in _save_action_labels(not should_save)):
                state = "already saved" if should_save else "already not saved"
                return BrowserActionResult(True, f"Post was {state} through browser fallback.")

            if self._click_first(page, _save_action_selectors(should_save), optional=True):
                verb = "saved" if should_save else "removed from saved items"
                return BrowserActionResult(True, f"Post {verb} through browser fallback.")

            if _menu_contains_any(page, _save_action_labels(not should_save)):
                state = "already saved" if should_save else "already not saved"
                return BrowserActionResult(True, f"Post was {state} through browser fallback.")

            raise BrowserActionError(
                "Unable to locate LinkedIn save state control. "
                f"Visible menu items: {_visible_menu_labels(page)}"
            )

    def toggle_reaction(
        self,
        activity_identifier: str,
        reaction: str,
        *,
        remove: bool = False,
    ) -> BrowserActionResult:
        with self._open_page(_activity_url(activity_identifier)) as page:
            if remove:
                self._click_first(
                    page,
                    [
                        "button[aria-pressed='true'][aria-label*='reaction']",
                        "button.react-button--active",
                        "button.reactions-react-button[aria-pressed='true']",
                    ],
                )
                return BrowserActionResult(True, "Reaction removed through browser fallback.")

            if reaction.lower() == "like":
                self._click_first(
                    page,
                    [
                        "button[aria-label*='Like']",
                        "button:has-text('Like')",
                        "button.reactions-react-button",
                    ],
                )
                return BrowserActionResult(True, "Reaction applied through browser fallback.")

            raise BrowserActionError(
                f"Browser fallback currently supports removing reactions and applying 'like'; got '{reaction}'."
            )

    @contextmanager
    def _open_page(self, url: str):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - guarded by packaging
            raise BrowserActionError(
                "Playwright is not installed. Install it to enable browser fallback."
            ) from exc

        timeout_ms = int(self.config.rate_limit.timeout * 1000)
        with sync_playwright() as playwright:
            browser = self._launch_browser(playwright)
            context = self._new_context(browser)
            try:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                self._ensure_authenticated_page(page, target_url=url, context=context)
                yield page
            finally:
                context.close()
                browser.close()

    def _new_context(self, browser):
        state_path = _browser_state_path()
        if state_path.exists():
            return browser.new_context(storage_state=str(state_path))

        context = browser.new_context()
        context.add_cookies(self.auth_session.as_playwright_cookies())
        return context

    def _launch_browser(self, playwright):
        headless = self.config.browser.headless
        preferred = self.config.browser.preferred

        if preferred == "firefox":
            return playwright.firefox.launch(headless=headless)
        if preferred == "edge":
            return playwright.chromium.launch(channel="msedge", headless=headless)
        if preferred == "brave":
            brave_path = _first_existing_path(_BRAVE_EXECUTABLES)
            if brave_path is not None:
                return playwright.chromium.launch(executable_path=str(brave_path), headless=headless)

        if preferred == "chrome":
            return self._launch_chrome(playwright, headless=headless)

        return playwright.chromium.launch(headless=headless)

    def _launch_chrome(self, playwright, *, headless: bool):
        errors: list[str] = []
        for kwargs in _chrome_launch_candidates(headless=headless):
            try:
                return playwright.chromium.launch(**kwargs)
            except Exception as exc:  # Playwright raises implementation-specific errors.
                errors.append(str(exc).splitlines()[0])
        details = "; ".join(error for error in errors if error)
        raise BrowserActionError(
            "Unable to launch Chrome for browser fallback. "
            "Install Google Chrome or run `playwright install chromium`."
            + (f" Details: {details}" if details else "")
        )

    def _set_visibility(self, page, visibility: str) -> None:
        label = "Anyone" if visibility == "public" else "Connections only"
        self._click_first(
            page,
            [
                "[role='dialog'] button[aria-label*='Post setting']",
                "[role='dialog'] button:has-text('Anyone')",
                "[role='dialog'] button:has-text('Connections only')",
            ],
            optional=True,
        )
        self._click_first(
            page,
            [
                f"[role='dialog'] label:has-text('{label}')",
                f"[role='dialog'] div:has-text('{label}')",
                f"[role='dialog'] span:has-text('{label}')",
            ],
            optional=True,
        )
        self._click_first(
            page,
            [
                "[role='dialog'] button:has-text('Done')",
                "[role='dialog'] button:has-text('Save')",
            ],
            optional=True,
        )

    def _click_first(self, page, selectors: Iterable[str], optional: bool = False) -> bool:
        timeout_ms = min(max(int(self.config.rate_limit.timeout * 250), 1000), 5000)
        last_error: Exception | None = None
        for selector in selectors:
            locator = page.locator(selector)
            for target in _locator_candidates(locator):
                try:
                    target.wait_for(state="visible", timeout=timeout_ms)
                    target.click(timeout=timeout_ms)
                    return True
                except Exception as exc:
                    last_error = exc
        if optional:
            return False

        detail = f" Last error: {last_error}" if last_error else ""
        raise BrowserActionError(
            f"Unable to locate LinkedIn UI control for selectors: {selectors}.{detail}"
        )

    def _locator_for(self, page, selectors: Iterable[str]):
        for selector in selectors:
            locator = page.locator(selector)
            for target in _locator_candidates(locator):
                try:
                    target.wait_for(state="visible", timeout=1000)
                    return target
                except Exception:
                    continue
        raise BrowserActionError(f"Unable to locate LinkedIn editor for selectors: {selectors}")

    def _pause_for_write(self) -> None:
        delay = random.uniform(
            self.config.rate_limit.write_delay_min,
            self.config.rate_limit.write_delay_max,
        )
        time.sleep(delay)

    def _scroll_until_saved_count(self, page, count: int) -> None:
        if count <= 0:
            return
        for _ in range(5):
            current_count = page.evaluate(
                """
                () => Array.from(document.querySelectorAll('main li'))
                  .filter(li => li.querySelector('a[href*="/feed/update/urn:li:activity:"]'))
                  .length
                """
            )
            if isinstance(current_count, int) and current_count >= count:
                return
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)

    def _ensure_authenticated_page(self, page, *, target_url: str, context) -> None:
        try:
            body_text = page.locator("body").inner_text(timeout=3000)
        except Exception:
            body_text = ""
        if not _looks_logged_out(page.url, body_text):
            return

        if self.config.browser.fallback_enabled:
            self._recover_login(page, target_url=target_url, context=context)
            return

        raise BrowserActionError(
            "LinkedIn browser fallback opened a logged-out page. "
            "The resolved cookies are present but not accepted by LinkedIn; refresh the browser "
            "session or provide a fresh LINKEDIN_COOKIE_HEADER."
        )

    def _recover_login(self, page, *, target_url: str, context) -> None:
        timeout_ms = int(self.config.rate_limit.timeout * 1000)
        page.goto("https://www.linkedin.com/login/", wait_until="domcontentloaded", timeout=timeout_ms)

        if self._complete_auto_login_if_available(page, target_url=target_url, context=context):
            return

        credentials = _load_login_credentials(self.config.browser.preferred)
        if credentials is None:
            raise BrowserActionError(
                "LinkedIn browser fallback opened a logged-out page. "
                "No non-interactive login credentials were available. Set LINKEDIN_USERNAME and "
                "LINKEDIN_PASSWORD, or save the LinkedIn password in Chrome Password Manager on macOS."
            )

        self._fill_first(
            page,
            [
                "input[name='session_key']",
                "#username",
                "input[autocomplete='username']",
                "input[type='email']",
                "input[type='text']",
            ],
            credentials.username,
        )
        self._fill_first(
            page,
            [
                "input[name='session_password']",
                "#password",
                "input[autocomplete='current-password']",
                "input[type='password']",
            ],
            credentials.password,
        )
        self._click_first(
            page,
            [
                "button[type='submit']",
                "button:has-text('로그인')",
                "button:has-text('Sign in')",
            ],
        )
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(2000)
        page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1000)

        try:
            body_text = page.locator("body").inner_text(timeout=3000)
        except Exception:
            body_text = ""
        if _looks_logged_out(page.url, body_text):
            raise BrowserActionError(
                f"LinkedIn login fallback using {credentials.source} did not produce an "
                "authenticated session."
            )

        state_path = _browser_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_path))
        _harden_state_permissions(state_path)

    def _complete_auto_login_if_available(self, page, *, target_url: str, context) -> bool:
        body_text = _page_body_text(page)
        if not _looks_auto_login_page(body_text):
            return False

        timeout_ms = int(self.config.rate_limit.timeout * 1000)
        page.wait_for_timeout(6000)
        page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1000)

        if _looks_logged_out(page.url, _page_body_text(page)):
            return False

        state_path = _browser_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_path))
        _harden_state_permissions(state_path)
        return True

    def _fill_first(self, page, selectors: Iterable[str], value: str) -> None:
        timeout_ms = min(max(int(self.config.rate_limit.timeout * 250), 1000), 5000)
        last_error: Exception | None = None
        for selector in selectors:
            locator = page.locator(selector)
            for target in _locator_candidates(locator):
                try:
                    target.wait_for(state="visible", timeout=timeout_ms)
                    target.fill(value, timeout=timeout_ms)
                    return
                except Exception as exc:
                    last_error = exc
        raise BrowserActionError(f"Unable to locate LinkedIn login input. Last error: {last_error}")


def _activity_url(activity_identifier: str) -> str:
    if activity_identifier.startswith("http://") or activity_identifier.startswith("https://"):
        return activity_identifier
    if activity_identifier.startswith("urn:li:activity:"):
        activity_identifier = activity_identifier.split(":")[-1]
    return f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_identifier}/"


_CHROME_EXECUTABLES = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

_BRAVE_EXECUTABLES = (
    Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    Path.home() / "Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)


def _first_existing_path(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _chrome_launch_candidates(*, headless: bool) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = [{"channel": "chrome", "headless": headless}]
    chrome_path = _first_existing_path(_CHROME_EXECUTABLES)
    if chrome_path is not None:
        candidates.append({"executable_path": str(chrome_path), "headless": headless})
    candidates.append({"headless": headless})
    return candidates


def _locator_candidates(locator, *, limit: int = 12):
    try:
        count = locator.count()
    except Exception:
        count = 0
    if count <= 0:
        return [locator.first]
    return [locator.nth(index) for index in range(min(count, limit))]


def _browser_state_path() -> Path:
    raw = os.getenv(ENV_BROWSER_STATE)
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".config" / "linkedin-cli" / "browser-state.json"


def _harden_state_permissions(state_path: Path) -> None:
    """Best-effort restriction of the cached browser session to the current user."""
    try:
        os.chmod(state_path.parent, 0o700)
        os.chmod(state_path, 0o600)
    except OSError:
        pass  # non-POSIX FS or unsupported; best-effort only


def _save_action_labels(should_save: bool) -> tuple[str, ...]:
    return ("Save", "저장") if should_save else ("Unsave", "저장 취소", "저장 해제")


def _save_action_selectors(should_save: bool) -> list[str]:
    selectors: list[str] = []
    for label in _save_action_labels(should_save):
        selectors.extend(
            [
                f"[role='menuitem']:has-text('{label}')",
                f"div[role='menuitem']:has-text('{label}')",
                f"button:has-text('{label}')",
                f"span:has-text('{label}')",
            ]
        )
    return selectors


def _visible_menu_labels(page) -> list[str]:
    try:
        labels = page.locator("[role='menuitem']").evaluate_all(
            """
            els => els
              .map(el => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim())
              .filter(Boolean)
            """
        )
    except Exception:
        return []
    return [str(label) for label in labels]


def _wait_for_menu_labels(page, *, timeout: float) -> list[str]:
    deadline = time.monotonic() + min(max(timeout, 1.0), 8.0)
    while time.monotonic() < deadline:
        labels = _visible_menu_labels(page)
        if labels:
            return labels
        try:
            page.wait_for_timeout(250)
        except Exception:
            break
    return _visible_menu_labels(page)


def _click_visible_menu_label(page, labels: Iterable[str], visible_labels: list[str]) -> bool:
    wanted = set(labels)
    items = page.locator("[role='menuitem']")
    try:
        count = items.count()
    except Exception:
        count = 0
    for index in range(count):
        try:
            text = " ".join((items.nth(index).inner_text() or "").split())
        except Exception:
            continue
        if text in wanted:
            items.nth(index).click()
            return True
    return False


def _menu_contains_any(page, labels: Iterable[str]) -> bool:
    visible = set(_visible_menu_labels(page))
    return any(label in visible for label in labels)


def _looks_logged_out(url: str, body_text: str) -> bool:
    lowered_url = url.lower()
    if "/login" in lowered_url or "/checkpoint" in lowered_url:
        return True
    logged_out_markers = (
        "로그인해서 콘텐츠 더보기",
        "댓글을 보거나 남기려면 로그인",
        "Sign in to view",
        "Sign in to continue",
        "Join LinkedIn",
    )
    return any(marker in body_text for marker in logged_out_markers)


_SAVED_POSTS_SCRIPT = """
(limit) => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const cards = Array.from(document.querySelectorAll('main li'))
    .filter((li) => li.querySelector('a[href*="/feed/update/urn:li:activity:"]'));

  return cards.slice(0, limit).map((card) => {
    const text = clean(card.innerText);
    const menu = card.querySelector('button[aria-label*="업데이트 메뉴 더보기"], button[aria-label*="관리 메뉴 열기"], button[aria-label*="More actions"], button[aria-label*="Open control menu"], button[aria-label*="Open options"]');
    const menuLabel = menu ? (menu.getAttribute('aria-label') || '') : '';
    const authorFromMenu = menuLabel
      .replace(/^클릭해서 /, '')
      .replace(/의 업데이트 메뉴 더보기$/, '')
      .replace(/ 님의 게시물에 대한 관리 메뉴 열기$/, '')
      .replace(/님의 게시물에 대한 관리 메뉴 열기$/, '')
      .trim();
    const authorFromText = clean(text.split('님의 프로필 보기')[0]).replace(/^상태 - \\S+\\s+/, '');
    const activityLink = Array.from(card.querySelectorAll('a[href*="/feed/update/urn:li:activity:"]'))[0];
    const activityUrl = activityLink ? activityLink.href.split('?')[0] : '';
    const activityMatch = activityUrl.match(/urn:li:activity:(\\d+)/);
    const profileLink = Array.from(card.querySelectorAll('a[href*="/in/"], a[href*="/company/"]'))[0];
    const profileUrl = profileLink ? profileLink.href.split('?')[0] : '';
    const headlineMatch = text.match(/님의 프로필 보기\\s*[^•]*•\\s*[^•]*\\s*(.*?)\\s+\\d+[분시간일주개월년]/);

    return {
      entityUrn: activityMatch ? `urn:li:activity:${activityMatch[1]}` : '',
      url: activityUrl,
      commentary: text,
      author_name: authorFromMenu || authorFromText,
      author_profile: profileUrl,
      headline: headlineMatch ? clean(headlineMatch[1]) : '',
      savedByViewer: true,
    };
  });
}
"""


def _looks_auto_login_page(body_text: str) -> bool:
    markers = (
        "로그인중",
        "이 페이지에 남아 있을 경우 로그인됩니다",
        "You will be signed in",
        "stay on this page",
    )
    return any(marker in body_text for marker in markers)


def _page_body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


def _load_login_credentials(preferred_browser: str) -> BrowserLoginCredentials | None:
    env_username = os.getenv(ENV_USERNAME, "").strip()
    env_password = os.getenv(ENV_PASSWORD, "")
    if env_username and env_password:
        return BrowserLoginCredentials(
            username=env_username,
            password=env_password,
            source=f"{ENV_USERNAME}/{ENV_PASSWORD}",
        )

    if preferred_browser != "chrome" or sys.platform != "darwin":
        return None

    return _load_chrome_password_manager_credentials()


def _load_chrome_password_manager_credentials() -> BrowserLoginCredentials | None:
    chrome_root = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    if not chrome_root.exists():
        return None

    safe_storage = _read_chrome_safe_storage_key()
    if not safe_storage:
        return None

    candidates: list[tuple[int, str, bytes]] = []
    for login_db in _chrome_login_data_paths(chrome_root):
        candidates.extend(_read_linkedin_logins(login_db))
    if not candidates:
        return None

    for _, username, encrypted_password in sorted(candidates, key=lambda row: row[0], reverse=True):
        password = _decrypt_chrome_password(encrypted_password, safe_storage)
        if username and password:
            return BrowserLoginCredentials(
                username=username,
                password=password,
                source="Chrome Password Manager",
            )
    return None


def _chrome_login_data_paths(chrome_root: Path) -> list[Path]:
    paths = [chrome_root / "Default" / "Login Data"]
    paths.extend(sorted(chrome_root.glob("Profile */Login Data")))
    return [path for path in paths if path.exists()]


def _read_linkedin_logins(login_db: Path) -> list[tuple[int, str, bytes]]:
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        shutil.copy2(login_db, tmp_path)
        conn = sqlite3.connect(tmp_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(logins)").fetchall()}
            password_column = (
                "password_value" if "password_value" in columns else "encrypted_password"
            )
            date_column = "date_last_used" if "date_last_used" in columns else "date_created"
            rows = conn.execute(
                f"""
                SELECT {date_column}, username_value, {password_column}
                FROM logins
                WHERE origin_url LIKE '%linkedin.com%' OR signon_realm LIKE '%linkedin.com%'
                ORDER BY {date_column} DESC
                """
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    finally:
        tmp_path.unlink(missing_ok=True)

    parsed: list[tuple[int, str, bytes]] = []
    for date_value, username, encrypted in rows:
        if username and encrypted:
            parsed.append((int(date_value or 0), str(username), bytes(encrypted)))
    return parsed


def _read_chrome_safe_storage_key() -> bytes | None:
    try:
        return subprocess.check_output(
            [
                "security",
                "find-generic-password",
                "-w",
                "-s",
                "Chrome Safe Storage",
                "-a",
                "Chrome",
            ],
            stderr=subprocess.DEVNULL,
        ).rstrip(b"\n")
    except Exception:
        return None


def _decrypt_chrome_password(encrypted_password: bytes, safe_storage: bytes) -> str | None:
    if not encrypted_password:
        return None

    blob = encrypted_password
    if blob.startswith(b"v10") or blob.startswith(b"v11"):
        blob = blob[3:]

    key = hashlib.pbkdf2_hmac("sha1", safe_storage, b"saltysalt", 1003, 16)
    iv = b" " * 16
    try:
        proc = subprocess.run(
            [
                "openssl",
                "enc",
                "-aes-128-cbc",
                "-d",
                "-K",
                key.hex(),
                "-iv",
                iv.hex(),
            ],
            input=blob,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return proc.stdout.decode("utf-8")
    except Exception:
        return None
