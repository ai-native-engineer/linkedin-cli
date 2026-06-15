"""CLI entrypoint for linkedin-cli."""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import click
import httpx
from rich.console import Console

from . import __version__
from .auth import AuthenticationError
from .auth import collect_auth_diagnostics
from .auth import default_cookie_file_path
from .auth import resolve_auth_session
from .auth import try_browser_login
from .auth import write_cookie_header_file
from .api import LinkedInWriteAPI
from .browser import BrowserActionError
from .client import LinkedInClient, LinkedInClientError
from .config import AppConfig, load_config
from .constants import COOKIE_REQUIRED_NAMES
from .constants import ENV_BROWSER
from .constants import SUPPORTED_BROWSERS
from .contract import activity_data
from .contract import auth_status_data
from .contract import comment_list_success_data
from .contract import comment_dry_run_data
from .contract import comments_data
from .contract import comment_success_data
from .contract import envelope
from .contract import error_envelope
from .contract import feed_data
from .contract import insights_data
from .contract import organization_insights_data
from .contract import post_create_dry_run_data
from .contract import post_delete_dry_run_data
from .contract import post_delete_success_data
from .contract import post_get_success_data
from .contract import post_list_success_data
from .contract import post_media_dry_run_data
from .contract import permission_check_data
from .contract import post_reply_dry_run_data
from .contract import post_reply_success_data
from .contract import post_text_dry_run_data
from .contract import post_text_success_data
from .contract import post_update_dry_run_data
from .contract import post_update_success_data
from .contract import profile_data
from .contract import reaction_list_success_data
from .contract import reaction_dry_run_data
from .contract import reactions_data
from .contract import reaction_success_data
from .contract import saved_unsave_success_data
from .contract import search_data
from .contract import social_action_dry_run_data
from .contract import social_action_success_data
from .contract import social_metadata_dry_run_data
from .contract import social_metadata_success_data
from .contract import to_contract_json
from .formatter import (
    build_search_table,
    build_status_panel,
    print_comments,
    print_post_detail,
    print_post_table,
    print_profile,
)
from .oauth import OAuthConfigError
from .oauth import default_oauth_path
from .oauth import load_oauth_config
from .oauth_flow import DEFAULT_REDIRECT_URI
from .oauth_flow import DEFAULT_SCOPES
from .oauth_flow import ENV_CLIENT_ID
from .oauth_flow import ENV_CLIENT_SECRET
from .oauth_flow import ENV_REDIRECT_URI
from .oauth_flow import OAuthFlowError
from .oauth_flow import USERINFO_URL
from .oauth_flow import run_oauth_login
from .publisher import LinkedInPublishError
from .serialization import posts_to_json, profile_to_dict, search_results_to_json, to_json
from .transport import LinkedInTransportError

console = Console(stderr=True)
# Browser/session `react` supports these (see client.REACTION_TYPE_MAP); official
# `reaction create` additionally accepts "funny" (see publisher.REACTION_TYPE_MAP).
REACTION_CHOICES = ["like", "celebrate", "support", "love", "insightful", "curious"]
POLL_DURATION_CHOICES = ["one-day", "three-days", "seven-days", "fourteen-days"]
USER_ERROR_CODES = {
    "auth_missing",
    "auth_expired",
    "invalid_request",
    "media_invalid",
    "not_found",
    "permission_denied",
    "post_rejected",
    "unsupported",
}


class LegacyPostGroup(click.Group):
    """Route `linkedin post "text"` to the hidden legacy command."""

    def resolve_command(self, ctx: click.Context, args: list[str]):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            if args and not args[0].startswith("-") and "legacy" in self.commands:
                return "legacy", self.commands["legacy"], args
            raise


class LegacyCommentGroup(click.Group):
    """Route `linkedin comment <identifier> <text>` to the hidden legacy command."""

    def resolve_command(self, ctx: click.Context, args: list[str]):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            if args and not args[0].startswith("-") and "legacy" in self.commands:
                return "legacy", self.commands["legacy"], args
            raise


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)


def _load_runtime_config(config_path: Optional[str]) -> AppConfig:
    path = Path(config_path) if config_path else None
    return load_config(path)


def _client_from_ctx(ctx: click.Context) -> LinkedInClient:
    return LinkedInClient(ctx.obj["config"])


def _context_output_file() -> Optional[str]:
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return None
    value = ctx.meta.get("output_file")
    return str(value) if value else None


def _capture_output_option(ctx: click.Context, _param: click.Parameter, value: Optional[str]) -> Optional[str]:
    if value:
        ctx.meta["output_file"] = value
    return value


def _contract_output_option(func):
    return click.option(
        "--output",
        "-o",
        "_output_file",
        type=str,
        default=None,
        expose_value=False,
        callback=_capture_output_option,
        help="Write JSON output to a file.",
    )(func)


def _write_output(output_file: Optional[str], payload: str) -> None:
    target = output_file or _context_output_file()
    if target:
        Path(target).write_text(payload + "\n", encoding="utf-8")


def _handle_error(exc: Exception) -> None:
    console.print(build_status_panel("linkedin-cli", False, str(exc)))
    raise SystemExit(1) from exc


def _contract_request(**kwargs) -> dict:
    return kwargs


def _cursor_offset(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        offset = int(payload.get("offset", 0))
    except Exception as exc:
        raise LinkedInPublishError(
            "Invalid cursor.",
            code="invalid_request",
            retryable=False,
        ) from exc
    if offset < 0:
        raise LinkedInPublishError(
            "Invalid cursor.",
            code="invalid_request",
            retryable=False,
        )
    return offset


def _cursor_for_offset(offset: int) -> str:
    payload = json.dumps({"offset": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _fetch_limit_for_page(limit: Optional[int], cursor: Optional[str]) -> Optional[int]:
    if limit is None:
        return None
    if limit <= 0:
        raise LinkedInPublishError(
            "Limit must be greater than 0.",
            code="invalid_request",
            retryable=False,
        )
    return _cursor_offset(cursor) + limit + 1


def _page_items(items: list, *, limit: Optional[int], cursor: Optional[str]) -> tuple[list, Optional[str], bool]:
    offset = _cursor_offset(cursor)
    if limit is None:
        return items[offset:], None, False
    page = items[offset : offset + limit]
    has_more = len(items) > offset + limit
    next_cursor = _cursor_for_offset(offset + limit) if has_more else None
    return page, next_cursor, has_more


def _resolve_post_text(text_body: Optional[str], text_file: Optional[str]) -> str:
    has_text = text_body is not None
    has_file = text_file is not None
    if has_text == has_file:
        raise LinkedInPublishError(
            "Pass exactly one of --text or --text-file.",
            code="invalid_request",
            retryable=False,
        )
    if text_body is not None:
        body = text_body
    elif text_file == "-":
        body = sys.stdin.read()
    else:
        path = Path(text_file or "").expanduser()
        if not path.exists() or not path.is_file():
            raise LinkedInPublishError(
                f"Post text file not found: {path}",
                code="invalid_request",
                retryable=False,
            )
        body = path.read_text(encoding="utf-8")

    normalized = body.strip()
    if not normalized:
        raise LinkedInPublishError(
            "Post text cannot be empty.",
            code="invalid_request",
            retryable=False,
        )
    return normalized


def _write_api_from_options(
    *,
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> LinkedInWriteAPI:
    return LinkedInWriteAPI.from_config(
        Path(oauth_file) if oauth_file else None,
        author_override=author_urn,
        version_override=linkedin_version,
    )


def _emit_contract(payload: dict, output_file: Optional[str] = None) -> None:
    rendered = to_contract_json(payload)
    _write_output(output_file, rendered)
    click.echo(rendered)


def _exit_code_for_error(code: str) -> int:
    if code in USER_ERROR_CODES:
        return 2
    if code in {"rate_limited", "upstream_unavailable", "upstream_changed", "media_upload_failed"}:
        return 3
    return 4


def _classify_contract_error(exc: Exception) -> tuple[str, bool, dict]:
    message = str(exc)
    lowered = message.lower()

    if "multiple cookies with name" in lowered:
        return "auth_expired", False, {"auth_kind": "cookie_session"}

    if isinstance(exc, AuthenticationError):
        if "no linkedin cookies" in lowered or "missing required cookies" in lowered:
            return "auth_missing", False, {"auth_kind": "cookie_session"}
        return "auth_expired", False, {"auth_kind": "cookie_session"}

    if isinstance(exc, OAuthConfigError):
        if "not found" in lowered or "missing" in lowered:
            return "auth_missing", False, {"auth_kind": "oauth"}
        return "invalid_request", False, {"auth_kind": "oauth"}

    if isinstance(exc, OAuthFlowError):
        return exc.code, exc.retryable, dict(exc.details)

    if isinstance(exc, LinkedInPublishError):
        details = dict(exc.details)
        if exc.status_code is not None:
            details.setdefault("status_code", exc.status_code)
        return exc.code, exc.retryable, details

    if isinstance(exc, BrowserActionError):
        if "logged-out page" in lowered or "not accepted by linkedin" in lowered:
            return "auth_expired", False, {"auth_kind": "cookie_session"}
        return "upstream_changed", False, {"operation": "browser_action"}

    if isinstance(exc, LinkedInTransportError):
        if "429" in lowered or "rate" in lowered:
            return "rate_limited", True, {}
        if "redirect" in lowered or "session-rejected" in lowered or "self-redirect" in lowered:
            return "auth_expired", False, {"auth_kind": "cookie_session"}
        if "invalid" in lowered or "included list" in lowered or "payload" in lowered:
            return "upstream_changed", False, {}
        return "upstream_unavailable", True, {}

    if isinstance(exc, LinkedInClientError):
        if "must be greater than 0" in lowered or "cannot be empty" in lowered:
            return "invalid_request", False, {}
        if (
            "redirect loop" in lowered
            or "cookie" in lowered
            or "authwall" in lowered
            or "session-rejected" in lowered
            or "self-redirect" in lowered
        ):
            return "auth_expired", False, {"auth_kind": "cookie_session"}
        if "unsupported" in lowered:
            return "unsupported", False, {}
        if "failed" in lowered:
            return "upstream_unavailable", True, {}

    return "internal_error", False, {"error_type": exc.__class__.__name__}


def _handle_contract_error(
    *,
    command: str,
    source: str,
    request: dict,
    exc: Exception,
    output_file: Optional[str] = None,
) -> None:
    code, retryable, details = _classify_contract_error(exc)
    payload = error_envelope(
        command=command,
        source=source,
        request=request,
        code=code,
        message=str(exc),
        retryable=retryable,
        details=details,
    )
    rendered = to_contract_json(payload)
    _write_output(output_file, rendered)
    click.echo(rendered)
    raise SystemExit(_exit_code_for_error(code)) from exc


def _emit_unsupported_contract(
    *,
    command: str,
    source: str,
    request: dict,
    message: str,
    details: Optional[dict] = None,
    as_json: bool,
    title: str,
    output_file: Optional[str] = None,
) -> None:
    if as_json:
        payload = error_envelope(
            command=command,
            source=source,
            request=request,
            code="unsupported",
            message=message,
            retryable=False,
            details=details or {},
        )
        _emit_contract(payload, output_file=output_file)
        raise SystemExit(_exit_code_for_error("unsupported"))
    console.print(build_status_panel(title, False, message))
    raise SystemExit(2)


def _permission_probe(name: str, callback) -> dict:
    try:
        result = callback()
    except Exception as exc:
        code, retryable, details = _classify_contract_error(exc)
        return {
            "name": name,
            "ok": False,
            "code": code,
            "message": str(exc),
            "retryable": retryable,
            "details": details,
        }
    return {
        "name": name,
        "ok": True,
        "code": None,
        "message": "ok",
        "retryable": False,
        "details": result if isinstance(result, dict) else {},
    }


@click.group()
@click.option("--config", "config_path", type=click.Path(dir_okay=False, path_type=str), default=None, help="Path to a config YAML file.")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.version_option(version=__version__)
@click.pass_context
def cli(ctx: click.Context, config_path: Optional[str], verbose: bool) -> None:
    """linkedin - LinkedIn CLI."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config"] = _load_runtime_config(config_path)


@cli.command("auth-status")
@click.pass_context
def auth_status(ctx: click.Context) -> None:
    """Verify the current LinkedIn session."""
    try:
        payload = collect_auth_diagnostics(ctx.obj["config"])
    except Exception as exc:
        _handle_error(exc)
    if not _render_auth_diagnostics(payload):
        raise SystemExit(1)


def _render_auth_diagnostics(payload: dict) -> bool:
    """Render the auth diagnostics panel shared by `auth-status` and `auth login`."""
    success = bool(payload.get("ok"))
    detail_lines = []
    identity = payload.get("public_id") or payload.get("full_name")
    summary_parts = [f"source={payload.get('source', 'unknown')}"]
    if payload.get("browser"):
        summary_parts.append(f"browser={payload['browser']}")
    if identity:
        summary_parts.append(f"identity={identity}")
    summary_parts.append(f"cookies={payload.get('cookie_count', 0)}")
    detail_lines.append(" | ".join(summary_parts))

    validation = payload.get("validation") or {}
    if validation.get("ok"):
        detail_lines.append("basic-probe=ok")
    else:
        probe_line = f"basic-probe={validation.get('kind') or 'error'}"
        if validation.get("status_code") is not None:
            probe_line += f":{validation['status_code']}"
        if validation.get("location"):
            probe_line += f" -> {validation['location']}"
        elif validation.get("error"):
            probe_line += f" ({validation['error']})"
        detail_lines.append(probe_line)

    for name, result in (payload.get("probes") or {}).items():
        if result.get("ok"):
            probe_line = f"{name}=ok"
            if result.get("status_code") is not None:
                probe_line += f":{result['status_code']}"
            detail_lines.append(probe_line)
            continue

        probe_line = f"{name}={result.get('reason') or result.get('kind') or 'error'}"
        if result.get("status_code") is not None:
            probe_line += f":{result['status_code']}"
        if result.get("location"):
            probe_line += f" -> {result['location']}"
        elif result.get("error"):
            probe_line += f" ({result['error']})"
        detail_lines.append(probe_line)

    if payload.get("hint"):
        detail_lines.append(f"hint={payload['hint']}")

    title = "Authentication OK" if success else "Authentication degraded"
    console.print(build_status_panel(title, success, "\n".join(detail_lines)))
    return success


@cli.group("auth")
def auth_group() -> None:
    """Manage LinkedIn CLI authentication."""


@auth_group.command("status")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.pass_context
def auth_status_contract(ctx: click.Context, as_json: bool, output_file: Optional[str]) -> None:
    """Report read-session cookie status as an SNS JSON Contract envelope."""
    request = _contract_request(dry_run=False)
    try:
        session = resolve_auth_session(ctx.obj["config"])
    except AuthenticationError:
        session = None

    if session is None:
        data = auth_status_data(
            state="missing",
            cookie_count=0,
            cookie_names=[],
            cookie_domains=[],
            required_missing=sorted(COOKIE_REQUIRED_NAMES),
        )
    else:
        cookie_names = set(session.cookie_names)
        missing = sorted(name for name in COOKIE_REQUIRED_NAMES if name not in cookie_names)
        domains = sorted({cookie.domain for cookie in session.cookie_jar if cookie.domain})
        data = auth_status_data(
            state="ready" if not missing else "degraded",
            cookie_count=session.cookie_count,
            cookie_names=session.cookie_names,
            cookie_domains=domains,
            required_missing=missing,
        )

    if as_json:
        _emit_contract(
            envelope(
                command="auth.status",
                source="unofficial",
                request=request,
                data=data,
            ),
            output_file=output_file,
        )
        return

    auth = data["auth"]
    console.print(
        build_status_panel(
            "Auth status",
            auth["state"] == "ready",
            f"state={auth['state']} | cookies={auth['cookie_count']} | "
            f"missing={','.join(auth['required_missing']) or 'none'}",
        )
    )


@auth_group.command("cookie-file")
@click.option(
    "--path",
    "cookie_file",
    type=click.Path(dir_okay=False, path_type=str),
    default=None,
    help="Private cookie env file path. Defaults to ~/.config/linkedin/cookies.env.",
)
@click.option(
    "--cookie-header",
    type=str,
    default=None,
    help="Full LinkedIn Cookie header. Prefer --from-stdin to avoid shell history.",
)
@click.option("--from-stdin", is_flag=True, help="Read the full Cookie header from stdin.")
def auth_cookie_file(
    cookie_file: Optional[str],
    cookie_header: Optional[str],
    from_stdin: bool,
) -> None:
    """Save a full LinkedIn Cookie header to a private read-session file."""
    if bool(cookie_header) == from_stdin:
        raise click.UsageError("Pass exactly one of --cookie-header or --from-stdin.")

    raw_header = sys.stdin.read().strip() if from_stdin else (cookie_header or "").strip()
    path = Path(cookie_file).expanduser() if cookie_file else default_cookie_file_path()
    try:
        summary = write_cookie_header_file(path, raw_header)
    except AuthenticationError as exc:
        raise click.ClickException(str(exc)) from exc

    detail = "\n".join(
        [
            f"path={summary['path']}",
            f"cookies={summary['cookie_count']}",
            "required_missing=none",
            "next=linkedin-cli auth-status",
        ]
    )
    console.print(build_status_panel("Cookie file saved", True, detail))


@auth_group.command("login")
@click.option(
    "--browser",
    type=click.Choice(SUPPORTED_BROWSERS),
    default=None,
    help="Browser to read the logged-in LinkedIn session from. Defaults to trying all supported browsers.",
)
@click.option(
    "--path",
    "cookie_file",
    type=click.Path(dir_okay=False, path_type=str),
    default=None,
    help="Private cookie env file path. Defaults to ~/.config/linkedin/cookies.env.",
)
@click.option("--force", is_flag=True, help="Overwrite an existing cookie file.")
@click.pass_context
def auth_login(
    ctx: click.Context,
    browser: Optional[str],
    cookie_file: Optional[str],
    force: bool,
) -> None:
    """Capture your LinkedIn read session automatically from a logged-in browser.

    Tries to extract li_at + JSESSIONID from a browser you are already logged into, writes
    them to a private 0600 cookie file, and verifies the session. If extraction fails, prints
    manual cookie-capture steps.
    """
    config = ctx.obj["config"]
    path = Path(cookie_file).expanduser() if cookie_file else default_cookie_file_path()

    if path.exists() and not force:
        raise click.ClickException(
            f"{path} already exists. Re-run with --force to overwrite, or run "
            "`linkedin-cli auth-status` to check the existing session."
        )

    if browser:
        os.environ[ENV_BROWSER] = browser

    session, attempts = try_browser_login(config)
    if session is None:
        _print_manual_cookie_steps(attempts)
        raise SystemExit(1)

    try:
        summary = write_cookie_header_file(path, session.cookie_string)
    except AuthenticationError as exc:
        raise click.ClickException(str(exc)) from exc

    console.print(
        build_status_panel(
            "Browser session captured",
            True,
            f"path={summary['path']}\nbrowser={session.browser}\ncookies={summary['cookie_count']}",
        )
    )

    try:
        payload = collect_auth_diagnostics(config)
    except Exception as exc:
        _handle_error(exc)
    if not _render_auth_diagnostics(payload):
        raise SystemExit(1)


def _print_manual_cookie_steps(attempts: list[dict[str, str]]) -> None:
    """Print actionable manual cookie-capture steps when automatic extraction fails."""
    lines = []
    if attempts:
        lines.append("Automatic browser extraction did not find a usable LinkedIn session:")
        for attempt in attempts:
            lines.append(f"  - {attempt['error']}")
        lines.append("")
    lines.extend(
        [
            "Capture the cookie manually instead:",
            "  1. Open https://www.linkedin.com and confirm you are logged in.",
            "  2. Open DevTools (Option+Command+I on macOS, or F12).",
            "  3. Application tab -> Storage -> Cookies -> https://www.linkedin.com.",
            '  4. Copy the values of li_at and JSESSIONID (JSESSIONID looks like "ajax:...";',
            "     copy it including the quotes).",
            "  5. Build one line:  li_at=<value>; JSESSIONID=<value>",
            "  6. Run:  linkedin-cli auth cookie-file --from-stdin",
            "     then paste the line, press Return, and press Control+D.",
            "  7. Verify:  linkedin-cli auth-status",
            "",
            "Tip: Firefox is the most reliable for automatic --browser extraction on macOS.",
            "Never paste these values into chat, commit them, or share them.",
        ]
    )
    console.print(build_status_panel("Manual cookie capture needed", False, "\n".join(lines)))


@auth_group.command("oauth-login")
@click.option("--client-id", type=str, default=None, help="LinkedIn app Client ID.")
@click.option("--client-secret", type=str, default=None, help="LinkedIn app Client Secret.")
@click.option("--redirect-uri", type=str, default=None, help="OAuth redirect URI.")
@click.option("--scope", "scopes", multiple=True, default=DEFAULT_SCOPES, help="OAuth scope to request.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="Token JSON output path.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn-Version metadata to save.")
@click.option("--timeout", type=int, default=180, show_default=True, help="Seconds to wait for browser callback.")
@click.option("--no-open", is_flag=True, help="Print instructions without opening the browser.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
def auth_oauth_login(
    client_id: Optional[str],
    client_secret: Optional[str],
    redirect_uri: Optional[str],
    scopes: tuple[str, ...],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
    timeout: int,
    no_open: bool,
    as_json: bool,
) -> None:
    """Issue and save a LinkedIn OAuth token for official post commands."""
    resolved_client_id = client_id or os.getenv(ENV_CLIENT_ID, "").strip()
    resolved_client_secret = client_secret or os.getenv(ENV_CLIENT_SECRET, "").strip()
    resolved_redirect_uri = redirect_uri or os.getenv(ENV_REDIRECT_URI, DEFAULT_REDIRECT_URI).strip()
    token_path = Path(oauth_file).expanduser() if oauth_file else default_oauth_path()
    request = _contract_request(
        redirect_uri=resolved_redirect_uri,
        scopes=list(scopes),
        dry_run=False,
        open_browser=not no_open,
    )
    if not resolved_client_id:
        exc = OAuthFlowError(f"{ENV_CLIENT_ID} is missing.", code="auth_missing")
        if as_json:
            _handle_contract_error(command="auth.oauth_login", source="official", request=request, exc=exc)
        _handle_error(exc)
    if not resolved_client_secret:
        exc = OAuthFlowError(f"{ENV_CLIENT_SECRET} is missing.", code="auth_missing")
        if as_json:
            _handle_contract_error(command="auth.oauth_login", source="official", request=request, exc=exc)
        _handle_error(exc)

    if not as_json:
        console.print(
            build_status_panel(
                "OAuth login started",
                True,
                (
                    f"redirect_uri={resolved_redirect_uri}\n"
                    f"scopes={','.join(scopes)}\n"
                    f"token_file={token_path}\n"
                    "Complete the LinkedIn consent screen in the browser."
                ),
            )
    )
    announce_url = None
    if no_open:
        def announce_url(url: str) -> None:
            console.print(f"Open this LinkedIn OAuth URL:\n{url}")

    try:
        result = run_oauth_login(
            client_id=resolved_client_id,
            client_secret=resolved_client_secret,
            redirect_uri=resolved_redirect_uri,
            scopes=scopes,
            token_path=token_path,
            linkedin_version=linkedin_version or "202605",
            open_browser=not no_open,
            timeout=timeout,
            announce_url=announce_url,
        )
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="auth.oauth_login",
                source="official",
                request=request,
                exc=exc,
            )
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="auth.oauth_login",
                source="official",
                request=request,
                data={"oauth": result.to_safe_dict()},
            )
        )
        return
    console.print(
        build_status_panel(
            "OAuth token saved",
            True,
            (
                f"token_file={result.token_path}\n"
                f"author_urn={result.author_urn}\n"
                f"scopes={','.join(result.scopes)}"
            ),
        )
    )


@auth_group.command("permission-check")
@click.option("--post-id", type=str, default=None, help="Optional share/ugcPost/activity URN or feed URL for post-scoped probes.")
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
def auth_permission_check(
    post_id: Optional[str],
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
    as_json: bool,
    output_file: Optional[str],
) -> None:
    """Probe official LinkedIn OAuth permissions without mutating LinkedIn."""
    request = _contract_request(post_id=post_id, author=author_urn, dry_run=False)
    try:
        oauth = load_oauth_config(
            Path(oauth_file) if oauth_file else None,
            author_override=author_urn,
            version_override=linkedin_version,
        )
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="auth.permission_check",
                source="official",
                request=request,
                exc=exc,
                output_file=output_file,
            )
        _handle_error(exc)

    probes: list[dict] = []
    with httpx.Client(timeout=20.0) as http:
        probes.append(
            _permission_probe(
                "openid.userinfo",
                lambda: _probe_userinfo(oauth.access_token, http),
            )
        )
    with LinkedInWriteAPI(oauth) as api:
        probes.append(
            _permission_probe(
                "posts.author_list",
                lambda: _probe_posts_author_list(api, oauth.author_urn),
            )
        )
        if post_id:
            probes.extend(
                [
                    _permission_probe("posts.get", lambda: _probe_post_get(api, post_id)),
                    _permission_probe("social.metadata", lambda: _probe_social_metadata(api, post_id)),
                    _permission_probe("comments.list", lambda: _probe_comments_list(api, post_id)),
                    _permission_probe("reactions.list", lambda: _probe_reactions_list(api, post_id)),
                ]
            )

    data = permission_check_data(
        oauth={
            "source": oauth.source,
            "author_urn": oauth.author_urn,
            "linkedin_version": oauth.linkedin_version,
        },
        probes=probes,
    )
    if as_json:
        _emit_contract(
            envelope(
                command="auth.permission_check",
                source="official",
                request=request,
                data=data,
            ),
            output_file=output_file,
        )
        return

    lines = [
        f"author_urn={oauth.author_urn}",
        f"linkedin_version={oauth.linkedin_version}",
    ]
    for probe in probes:
        status = "ok" if probe["ok"] else probe["code"]
        lines.append(f"{probe['name']}={status}")
    console.print(build_status_panel("Permission check", data["summary"]["ok"], "\n".join(lines)))


def _probe_userinfo(access_token: str, client: httpx.Client) -> dict:
    response = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code != 200:
        raise LinkedInPublishError(
            _permission_response_message(response, fallback="LinkedIn userinfo request failed."),
            code="permission_denied" if response.status_code == 403 else "auth_expired",
            retryable=False,
            status_code=response.status_code,
            details={"status_code": response.status_code},
        )
    payload = response.json()
    return {
        "status_code": response.status_code,
        "subject_present": bool(payload.get("sub")),
        "email_present": bool(payload.get("email")),
    }


def _probe_posts_author_list(api: LinkedInWriteAPI, author_urn: str) -> dict:
    result = api.list_posts_by_author(author_urn=author_urn, count=1, start=0)
    return {
        "author_urn": result.author_urn,
        "count": len(result.elements),
        "paging": result.paging,
    }


def _probe_post_get(api: LinkedInWriteAPI, post_id: str) -> dict:
    result = api.get_post(post_id=post_id)
    return {
        "post_id": result.post_id,
        "raw_keys": sorted(result.raw.keys()),
    }


def _probe_social_metadata(api: LinkedInWriteAPI, post_id: str) -> dict:
    result = api.get_social_metadata(entity=post_id)
    return {
        "entity": result.entity_urn,
        "raw_keys": sorted(result.raw.keys()),
    }


def _probe_comments_list(api: LinkedInWriteAPI, post_id: str) -> dict:
    result = api.list_comments(entity=post_id, count=1, start=0)
    return {
        "entity": result.entity_urn,
        "count": len(result.elements),
        "paging": result.paging,
    }


def _probe_reactions_list(api: LinkedInWriteAPI, post_id: str) -> dict:
    result = api.list_reactions(entity=post_id, count=1, start=0)
    return {
        "entity": result.entity_urn,
        "count": len(result.elements),
        "paging": result.paging,
    }


def _permission_response_message(response: httpx.Response, *, fallback: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error_description") or payload.get("error")
        if message:
            return f"LinkedIn API rejected the request: {message}"
    return fallback


@cli.command()
@click.option("--max", "max_count", type=int, default=None, help="Maximum number of feed items to fetch.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON to stdout.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.pass_context
def feed(ctx: click.Context, max_count: Optional[int], as_json: bool, output_file: Optional[str]) -> None:
    """Fetch the authenticated home feed."""
    try:
        posts = _client_from_ctx(ctx).feed(limit=max_count)
    except Exception as exc:
        _handle_error(exc)
    payload = posts_to_json(posts)
    _write_output(output_file, payload)
    if as_json:
        click.echo(payload)
        return
    print_post_table(posts, console=console, title="LinkedIn feed")


@cli.group()
def read() -> None:
    """Read LinkedIn data through unofficial authenticated web APIs."""


@read.command("feed")
@click.option("--limit", type=int, default=None, help="Maximum number of feed items to fetch.")
@click.option("--cursor", type=str, default=None, help="Opaque pagination cursor.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.pass_context
def read_feed(
    ctx: click.Context,
    limit: Optional[int],
    cursor: Optional[str],
    as_json: bool,
    output_file: Optional[str],
) -> None:
    """Fetch the authenticated home feed."""
    request = _contract_request(limit=limit, cursor=cursor, dry_run=False)
    try:
        fetch_limit = _fetch_limit_for_page(limit, cursor)
        posts = _client_from_ctx(ctx).feed(limit=fetch_limit)
        posts, next_cursor, has_more = _page_items(posts, limit=limit, cursor=cursor)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="read.feed",
                source="unofficial",
                request=request,
                exc=exc,
                output_file=output_file,
            )
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="read.feed",
                source="unofficial",
                request=request,
                data=feed_data(posts, cursor=cursor, next_cursor=next_cursor, has_more=has_more),
            ),
            output_file=output_file,
        )
        return

    print_post_table(posts, console=console, title="LinkedIn feed")


@read.command("saved")
@click.option("--limit", type=int, default=None, help="Maximum number of saved feed items to fetch.")
@click.option("--cursor", type=str, default=None, help="Opaque pagination cursor.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.pass_context
def read_saved(
    ctx: click.Context,
    limit: Optional[int],
    cursor: Optional[str],
    as_json: bool,
    output_file: Optional[str],
) -> None:
    """Fetch saved posts from the authenticated account."""
    request = _contract_request(limit=limit, cursor=cursor, dry_run=False)
    try:
        fetch_limit = _fetch_limit_for_page(limit, cursor)
        posts = _client_from_ctx(ctx).get_saved_posts(limit=fetch_limit)
        posts, next_cursor, has_more = _page_items(posts, limit=limit, cursor=cursor)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="read.saved",
                source="unofficial",
                request=request,
                exc=exc,
                output_file=output_file,
            )
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="read.saved",
                source="unofficial",
                request=request,
                data=feed_data(posts, cursor=cursor, next_cursor=next_cursor, has_more=has_more),
            ),
            output_file=output_file,
        )
        return

    print_post_table(posts, console=console, title="LinkedIn saved posts")


@read.command("profile")
@click.argument("identifier")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.pass_context
def read_profile(
    ctx: click.Context,
    identifier: str,
    as_json: bool,
    output_file: Optional[str],
) -> None:
    """Fetch a LinkedIn profile by public id or URL."""
    request = _contract_request(identifier=identifier, dry_run=False)
    try:
        result = _client_from_ctx(ctx).get_profile(identifier)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="read.profile",
                source="unofficial",
                request=request,
                exc=exc,
                output_file=output_file,
            )
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="read.profile",
                source="unofficial",
                request=request,
                data=profile_data(result),
            ),
            output_file=output_file,
        )
        return

    print_profile(result, console=console)


@read.command("search")
@click.argument("query")
@click.option("--limit", type=int, default=None, help="Maximum number of search results to fetch.")
@click.option("--cursor", type=str, default=None, help="Opaque pagination cursor.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.pass_context
def read_search(
    ctx: click.Context,
    query: str,
    limit: Optional[int],
    cursor: Optional[str],
    as_json: bool,
    output_file: Optional[str],
) -> None:
    """Search LinkedIn entities and posts."""
    request = _contract_request(query=query, limit=limit, cursor=cursor, dry_run=False)
    try:
        fetch_limit = _fetch_limit_for_page(limit, cursor)
        results = _client_from_ctx(ctx).search(query, limit=fetch_limit)
        results, next_cursor, has_more = _page_items(results, limit=limit, cursor=cursor)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="read.search",
                source="unofficial",
                request=request,
                exc=exc,
                output_file=output_file,
            )
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="read.search",
                source="unofficial",
                request=request,
                data=search_data(results, cursor=cursor, next_cursor=next_cursor, has_more=has_more),
            ),
            output_file=output_file,
        )
        return

    console.print(build_search_table(results, title=f"Search: {query}"))


@read.command("activity")
@click.argument("identifier")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.pass_context
def read_activity(
    ctx: click.Context,
    identifier: str,
    as_json: bool,
    output_file: Optional[str],
) -> None:
    """Fetch one LinkedIn activity as SNS JSON Contract v1."""
    request = _contract_request(identifier=identifier, dry_run=False)
    try:
        post = _client_from_ctx(ctx).get_activity(identifier)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="read.activity",
                source="unofficial",
                request=request,
                exc=exc,
            )
        _handle_error(exc)
    payload = envelope(
        command="read.activity",
        source="unofficial",
        request=request,
        data=activity_data(post),
    )
    if as_json:
        _emit_contract(payload, output_file=output_file)
        return
    _write_output(output_file, to_contract_json(payload))
    print_post_detail(post, console=console)


@read.command("comments")
@click.argument("identifier")
@click.option("--limit", type=int, default=None, help="Maximum number of comments to fetch.")
@click.option("--cursor", type=str, default=None, help="Opaque pagination cursor.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.pass_context
def read_comments(
    ctx: click.Context,
    identifier: str,
    limit: Optional[int],
    cursor: Optional[str],
    as_json: bool,
    output_file: Optional[str],
) -> None:
    """Fetch comments for one LinkedIn activity through unofficial read APIs."""
    request = _contract_request(identifier=identifier, limit=limit, cursor=cursor, dry_run=False)
    try:
        fetch_limit = _fetch_limit_for_page(limit, cursor)
        comments = _client_from_ctx(ctx).get_comments(identifier, limit=fetch_limit)
        comments, next_cursor, has_more = _page_items(comments, limit=limit, cursor=cursor)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="read.comments",
                source="unofficial",
                request=request,
                exc=exc,
                output_file=output_file,
            )
        _handle_error(exc)
    payload = envelope(
        command="read.comments",
        source="unofficial",
        request=request,
        data=comments_data(comments, cursor=cursor, next_cursor=next_cursor, has_more=has_more),
    )
    if as_json:
        _emit_contract(payload, output_file=output_file)
        return
    _write_output(output_file, to_contract_json(payload))
    print_comments(comments, console=console, title=f"Comments for {identifier}")


@read.command("reactions")
@click.argument("identifier")
@click.option("--limit", type=int, default=None, help="Maximum number of reactions to fetch.")
@click.option("--cursor", type=str, default=None, help="Opaque pagination cursor.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.pass_context
def read_reactions(
    ctx: click.Context,
    identifier: str,
    limit: Optional[int],
    cursor: Optional[str],
    as_json: bool,
    output_file: Optional[str],
) -> None:
    """Fetch reactions for one LinkedIn activity through unofficial read APIs."""
    request = _contract_request(identifier=identifier, limit=limit, cursor=cursor, dry_run=False)
    try:
        fetch_limit = _fetch_limit_for_page(limit, cursor)
        reactions = _client_from_ctx(ctx).get_reactions(identifier, limit=fetch_limit)
        reactions, next_cursor, has_more = _page_items(reactions, limit=limit, cursor=cursor)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="read.reactions",
                source="unofficial",
                request=request,
                exc=exc,
                output_file=output_file,
            )
        _handle_error(exc)
    payload = envelope(
        command="read.reactions",
        source="unofficial",
        request=request,
        data=reactions_data(reactions, cursor=cursor, next_cursor=next_cursor, has_more=has_more),
    )
    if as_json:
        _emit_contract(payload, output_file=output_file)
        return
    _write_output(output_file, to_contract_json(payload))
    console.print(to_json(payload["data"]))


@read.command("profile-posts")
@click.argument("identifier")
@click.option("--limit", type=int, default=None, help="Maximum number of posts to fetch.")
@click.option("--cursor", type=str, default=None, help="Opaque pagination cursor.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.pass_context
def read_profile_posts(
    ctx: click.Context,
    identifier: str,
    limit: Optional[int],
    cursor: Optional[str],
    as_json: bool,
    output_file: Optional[str],
) -> None:
    """Fetch posts for a LinkedIn profile as SNS JSON Contract v1."""
    request = _contract_request(identifier=identifier, limit=limit, cursor=cursor, dry_run=False)
    try:
        fetch_limit = _fetch_limit_for_page(limit, cursor)
        posts = _client_from_ctx(ctx).get_profile_posts(identifier, limit=fetch_limit)
        posts, next_cursor, has_more = _page_items(posts, limit=limit, cursor=cursor)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="read.profile_posts",
                source="unofficial",
                request=request,
                exc=exc,
            )
        _handle_error(exc)
    payload = envelope(
        command="read.profile_posts",
        source="unofficial",
        request=request,
        data=feed_data(posts, cursor=cursor, next_cursor=next_cursor, has_more=has_more),
    )
    if as_json:
        _emit_contract(payload, output_file=output_file)
        return
    _write_output(output_file, to_contract_json(payload))
    print_post_table(posts, console=console, title=f"Posts by {identifier}")


@cli.command()
@click.argument("query")
@click.option("--max", "max_count", type=int, default=None, help="Maximum number of search results to fetch.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON to stdout.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.pass_context
def search(ctx: click.Context, query: str, max_count: Optional[int], as_json: bool, output_file: Optional[str]) -> None:
    """Search LinkedIn entities and posts."""
    try:
        results = _client_from_ctx(ctx).search(query, limit=max_count)
    except Exception as exc:
        _handle_error(exc)
    payload = search_results_to_json(results)
    _write_output(output_file, payload)
    if as_json:
        click.echo(payload)
        return
    console.print(build_search_table(results, title=f"Search: {query}"))


@cli.command()
@click.argument("identifier")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON to stdout.")
@_contract_output_option
@click.pass_context
def profile(ctx: click.Context, identifier: str, as_json: bool) -> None:
    """Fetch a LinkedIn profile by public id or URL."""
    try:
        result = _client_from_ctx(ctx).get_profile(identifier)
    except Exception as exc:
        _handle_error(exc)
    payload = to_json(profile_to_dict(result))
    _write_output(None, payload)
    if as_json:
        click.echo(payload)
        return
    print_profile(result, console=console)


@cli.command("profile-posts")
@click.argument("identifier")
@click.option("--max", "max_count", type=int, default=None, help="Maximum number of posts to fetch.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON to stdout.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.pass_context
def profile_posts(ctx: click.Context, identifier: str, max_count: Optional[int], as_json: bool, output_file: Optional[str]) -> None:
    """Fetch posts for a LinkedIn profile."""
    try:
        posts = _client_from_ctx(ctx).get_profile_posts(identifier, limit=max_count)
    except Exception as exc:
        _handle_error(exc)
    payload = posts_to_json(posts)
    _write_output(output_file, payload)
    if as_json:
        click.echo(payload)
        return
    print_post_table(posts, console=console, title=f"Posts by {identifier}")


@cli.command()
@click.argument("identifier")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON to stdout.")
@_contract_output_option
@click.pass_context
def activity(ctx: click.Context, identifier: str, as_json: bool) -> None:
    """Fetch a LinkedIn activity detail."""
    try:
        post = _client_from_ctx(ctx).get_activity(identifier)
    except Exception as exc:
        _handle_error(exc)
    payload = to_json(post)
    _write_output(None, payload)
    if as_json:
        click.echo(payload)
        return
    print_post_detail(post, console=console)


@cli.group("saved")
def saved_group() -> None:
    """Inspect and manage saved LinkedIn posts through the authenticated session."""


@saved_group.command("list")
@click.option("--limit", type=int, default=None, help="Maximum number of saved feed items to fetch.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.pass_context
def saved_list(
    ctx: click.Context,
    limit: Optional[int],
    as_json: bool,
    output_file: Optional[str],
) -> None:
    """Fetch saved posts from the authenticated account."""
    request = _contract_request(limit=limit, cursor=None, dry_run=False)
    try:
        posts = _client_from_ctx(ctx).get_saved_posts(limit=limit)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="read.saved",
                source="unofficial",
                request=request,
                exc=exc,
                output_file=output_file,
            )
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="read.saved",
                source="unofficial",
                request=request,
                data=feed_data(posts),
            ),
            output_file=output_file,
        )
        return

    print_post_table(posts, console=console, title="LinkedIn saved posts")


@saved_group.command("unsave")
@click.argument("identifier")
@click.option("--dry-run", is_flag=True, help="Validate without changing saved posts.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.pass_context
def saved_unsave(ctx: click.Context, identifier: str, dry_run: bool, as_json: bool) -> None:
    """Remove one LinkedIn activity from saved posts."""
    request = _contract_request(identifier=identifier, dry_run=dry_run)
    if dry_run:
        data = social_action_dry_run_data(
            action="unsave",
            target_id=identifier,
            planned={
                "api": "linkedin.saved.unsave",
                "identifier": identifier,
            },
        )
        if as_json:
            _emit_contract(
                envelope(
                    command="saved.unsave",
                    source="unofficial",
                    request=request,
                    data=data,
                )
            )
            return
        console.print(build_status_panel("Saved unsave dry-run", True, identifier))
        return

    try:
        detail = _client_from_ctx(ctx).unsave(identifier)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="saved.unsave",
                source="unofficial",
                request=request,
                exc=exc,
            )
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="saved.unsave",
                source="unofficial",
                request=request,
                data=saved_unsave_success_data(identifier=identifier, detail=detail),
            )
        )
        return

    console.print(build_status_panel("Post unsaved", True, detail))


@cli.group("post", cls=LegacyPostGroup)
def post_group() -> None:
    """Create or delete LinkedIn posts through official LinkedIn APIs."""


@post_group.command("text")
@click.option("--text", "text_body", required=False, help="Post body text.")
@click.option(
    "--text-file",
    type=str,
    default=None,
    help="Read post body text from a UTF-8 file, or '-' for stdin.",
)
@click.option(
    "--visibility",
    type=click.Choice(["connections", "public"]),
    default="public",
    show_default=True,
)
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_text(
    text_body: Optional[str],
    text_file: Optional[str],
    visibility: str,
    dry_run: bool,
    as_json: bool,
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Publish text through the official LinkedIn Posts API."""
    request = _contract_request(
        visibility=visibility,
        dry_run=dry_run,
        media_count=0,
        text_length=None,
        author=author_urn,
    )
    try:
        text_body = _resolve_post_text(text_body, text_file)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="post.text",
                source="official",
                request=request,
                exc=exc,
            )
        _handle_error(exc)

    request = _contract_request(
        visibility=visibility,
        dry_run=dry_run,
        media_count=0,
        text_length=len(text_body),
        author=author_urn,
    )
    if dry_run:
        plan = LinkedInWriteAPI.for_dry_run(
            author_urn=author_urn,
            linkedin_version=linkedin_version,
        ).plan_text_post(text=text_body, visibility=visibility)
        payload = envelope(
            command="post.text",
            source="official",
            request=request,
            data=post_text_dry_run_data(text=text_body, visibility=plan.visibility),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Post dry-run OK",
                True,
                f"visibility={visibility} | text_length={len(text_body)} | api=linkedin.posts",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=author_urn,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.create_text_post(text=text_body, visibility=visibility)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="post.text",
                source="official",
                request=request,
                exc=exc,
            )
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.text",
                source="official",
                request=request,
                data=post_text_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Post created", True, f"id={result.post_id}\nurl={result.url}"))


@post_group.command("reply")
@click.argument("reply_to")
@click.option("--text", "text_body", required=False, help="Reply/comment text.")
@click.option(
    "--text-file",
    type=str,
    default=None,
    help="Read reply text from a UTF-8 file, or '-' for stdin.",
)
@click.option("--parent-comment", type=str, default=None, help="Optional parent comment URN.")
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--actor", "actor_urn", type=str, default=None, help="Override the actor URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_reply(
    reply_to: str,
    text_body: Optional[str],
    text_file: Optional[str],
    parent_comment: Optional[str],
    dry_run: bool,
    as_json: bool,
    actor_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Reply to a LinkedIn post/comment through the official Comments API."""
    request = _contract_request(
        reply_to=reply_to,
        parent_comment=parent_comment,
        dry_run=dry_run,
        text_length=None,
        actor=actor_urn,
    )
    try:
        text_body = _resolve_post_text(text_body, text_file)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.reply", source="official", request=request, exc=exc)
        _handle_error(exc)

    request["text_length"] = len(text_body)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=actor_urn,
                linkedin_version=linkedin_version,
            ).plan_reply_post(text=text_body, reply_to=reply_to, parent_comment=parent_comment)
        except Exception as exc:
            if as_json:
                _handle_contract_error(command="post.reply", source="official", request=request, exc=exc)
            _handle_error(exc)
        payload = envelope(
            command="post.reply",
            source="official",
            request=request,
            data=post_reply_dry_run_data(
                text=text_body,
                reply_to=plan["reply_to"],
                parent_comment=plan.get("parent_comment"),
            ),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Reply dry-run OK",
                True,
                f"reply_to={plan['reply_to']} | text_length={len(text_body)} | api=linkedin.comments",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.create_reply_post(
                reply_to=reply_to,
                text=text_body,
                actor_urn=actor_urn,
                parent_comment=parent_comment,
            )
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.reply", source="official", request=request, exc=exc)
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.reply",
                source="official",
                request=request,
                data=post_reply_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Reply created", True, f"id={result.comment_id}"))


@post_group.command("media")
@click.option("--text", "text_body", required=False, help="Post body text.")
@click.option(
    "--text-file",
    type=str,
    default=None,
    help="Read post body text from a UTF-8 file, or '-' for stdin.",
)
@click.option("--media", "media_paths", multiple=True, required=True, help="Local image path.")
@click.option(
    "--visibility",
    type=click.Choice(["connections", "public"]),
    default="public",
    show_default=True,
)
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_media(
    text_body: Optional[str],
    text_file: Optional[str],
    media_paths: tuple[str, ...],
    visibility: str,
    dry_run: bool,
    as_json: bool,
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Publish one local image through LinkedIn's official Images and Posts APIs."""
    request = _contract_request(
        visibility=visibility,
        dry_run=dry_run,
        media_count=len(media_paths),
        text_length=None,
        author=author_urn,
    )
    try:
        text_body = _resolve_post_text(text_body, text_file)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="post.media",
                source="official",
                request=request,
                exc=exc,
            )
        _handle_error(exc)

    request = _contract_request(
        visibility=visibility,
        dry_run=dry_run,
        media_count=len(media_paths),
        text_length=len(text_body),
        author=author_urn,
    )
    if len(media_paths) != 1:
        message = "post media accepts exactly one image. Use post multi-image for 2-20 images."
        if as_json:
            payload = error_envelope(
                command="post.media",
                source="official",
                request=request,
                code="media_invalid",
                message=message,
                retryable=False,
                details={"media_count": len(media_paths)},
            )
            click.echo(to_contract_json(payload))
            raise SystemExit(_exit_code_for_error("media_invalid"))
        console.print(build_status_panel("Post not created", False, message))
        raise SystemExit(2)

    if dry_run:
        plan = LinkedInWriteAPI.for_dry_run(
            author_urn=author_urn,
            linkedin_version=linkedin_version,
        ).plan_image_post(text=text_body, visibility=visibility, media_path=media_paths[0])
        payload = envelope(
            command="post.media",
            source="official",
            request=request,
            data=post_media_dry_run_data(
                text=text_body,
                visibility=plan.visibility,
                media_count=plan.media_count,
            ),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Media post dry-run OK",
                True,
                (
                    f"visibility={visibility} | text_length={len(text_body)} | "
                    f"media_count={len(media_paths)} | api=linkedin.posts+images"
                ),
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=author_urn,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.create_image_post(
                text=text_body,
                visibility=visibility,
                media_path=media_paths[0],
            )
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="post.media",
                source="official",
                request=request,
                exc=exc,
            )
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.media",
                source="official",
                request=request,
                data=post_text_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Post created", True, f"id={result.post_id}\nurl={result.url}"))


@post_group.command("multi-image")
@click.option("--text", "text_body", required=False, help="Post body text.")
@click.option(
    "--text-file",
    type=str,
    default=None,
    help="Read post body text from a UTF-8 file, or '-' for stdin.",
)
@click.option("--media", "media_paths", multiple=True, required=True, help="Local image path.")
@click.option(
    "--alt-text",
    "alt_texts",
    multiple=True,
    help="Optional alt text; pass once per image when used.",
)
@click.option(
    "--visibility",
    type=click.Choice(["connections", "public"]),
    default="public",
    show_default=True,
)
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_multi_image(
    text_body: Optional[str],
    text_file: Optional[str],
    media_paths: tuple[str, ...],
    alt_texts: tuple[str, ...],
    visibility: str,
    dry_run: bool,
    as_json: bool,
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Publish 2-20 local images through LinkedIn's official Images and Posts APIs."""
    request = _contract_request(
        visibility=visibility,
        dry_run=dry_run,
        media_count=len(media_paths),
        alt_text_count=len(alt_texts),
        text_length=None,
        author=author_urn,
    )
    try:
        text_body = _resolve_post_text(text_body, text_file)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="post.multi_image",
                source="official",
                request=request,
                exc=exc,
            )
        _handle_error(exc)

    request["text_length"] = len(text_body)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=author_urn,
                linkedin_version=linkedin_version,
            ).plan_multi_image_post(
                text=text_body,
                media_paths=list(media_paths),
                alt_texts=alt_texts,
                visibility=visibility,
            )
        except Exception as exc:
            if as_json:
                _handle_contract_error(
                    command="post.multi_image",
                    source="official",
                    request=request,
                    exc=exc,
                )
            _handle_error(exc)
        payload = envelope(
            command="post.multi_image",
            source="official",
            request=request,
            data=post_create_dry_run_data(
                text=text_body,
                visibility=plan.visibility,
                media_count=plan.media_count,
                api=plan.api,
                extra={
                    "media_paths": list(plan.media_paths),
                    "alt_text_count": len(alt_texts),
                    "min_media_count": 2,
                    "max_media_count": 20,
                },
            ),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Multi-image post dry-run OK",
                True,
                (
                    f"visibility={visibility} | text_length={len(text_body)} | "
                    f"media_count={len(media_paths)} | api=linkedin.posts+images"
                ),
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=author_urn,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.create_multi_image_post(
                text=text_body,
                visibility=visibility,
                media_paths=list(media_paths),
                alt_texts=alt_texts,
            )
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="post.multi_image",
                source="official",
                request=request,
                exc=exc,
            )
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.multi_image",
                source="official",
                request=request,
                data=post_text_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Multi-image post created", True, f"id={result.post_id}\nurl={result.url}"))


@post_group.command("video")
@click.option("--text", "text_body", required=False, help="Post body text.")
@click.option(
    "--text-file",
    type=str,
    default=None,
    help="Read post body text from a UTF-8 file, or '-' for stdin.",
)
@click.option("--video", "video_path", required=True, help="Local MP4 video path.")
@click.option("--title", type=str, default=None, help="Optional video title.")
@click.option(
    "--visibility",
    type=click.Choice(["connections", "public"]),
    default="public",
    show_default=True,
)
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_video(
    text_body: Optional[str],
    text_file: Optional[str],
    video_path: str,
    title: Optional[str],
    visibility: str,
    dry_run: bool,
    as_json: bool,
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Publish one local MP4 video through LinkedIn's official Videos and Posts APIs."""
    request = _contract_request(
        visibility=visibility,
        dry_run=dry_run,
        media_count=1,
        text_length=None,
        title=title,
        video=video_path,
        author=author_urn,
    )
    try:
        text_body = _resolve_post_text(text_body, text_file)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.video", source="official", request=request, exc=exc)
        _handle_error(exc)

    request["text_length"] = len(text_body)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=author_urn,
                linkedin_version=linkedin_version,
            ).plan_video_post(
                text=text_body,
                media_path=video_path,
                visibility=visibility,
                title=title,
            )
        except Exception as exc:
            if as_json:
                _handle_contract_error(command="post.video", source="official", request=request, exc=exc)
            _handle_error(exc)
        payload = envelope(
            command="post.video",
            source="official",
            request=request,
            data=post_create_dry_run_data(
                text=text_body,
                visibility=plan.visibility,
                media_count=plan.media_count,
                api=plan.api,
                extra={"media_path": plan.media_paths[0], "title": title},
            ),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Video post dry-run OK",
                True,
                f"visibility={visibility} | text_length={len(text_body)} | api=linkedin.posts+videos",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=author_urn,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.create_video_post(
                text=text_body,
                visibility=visibility,
                media_path=video_path,
                title=title,
            )
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.video", source="official", request=request, exc=exc)
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.video",
                source="official",
                request=request,
                data=post_text_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Video post created", True, f"id={result.post_id}\nurl={result.url}"))


@post_group.command("document")
@click.option("--text", "text_body", required=False, help="Post body text.")
@click.option(
    "--text-file",
    type=str,
    default=None,
    help="Read post body text from a UTF-8 file, or '-' for stdin.",
)
@click.option("--document", "document_path", required=True, help="Local PDF, DOC, DOCX, PPT, or PPTX path.")
@click.option("--title", type=str, default=None, help="Optional document title; defaults to the file name.")
@click.option(
    "--visibility",
    type=click.Choice(["connections", "public"]),
    default="public",
    show_default=True,
)
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_document(
    text_body: Optional[str],
    text_file: Optional[str],
    document_path: str,
    title: Optional[str],
    visibility: str,
    dry_run: bool,
    as_json: bool,
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Publish one local document through LinkedIn's official Documents and Posts APIs."""
    request = _contract_request(
        visibility=visibility,
        dry_run=dry_run,
        media_count=1,
        text_length=None,
        title=title,
        document=document_path,
        author=author_urn,
    )
    try:
        text_body = _resolve_post_text(text_body, text_file)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.document", source="official", request=request, exc=exc)
        _handle_error(exc)

    request["text_length"] = len(text_body)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=author_urn,
                linkedin_version=linkedin_version,
            ).plan_document_post(
                text=text_body,
                media_path=document_path,
                visibility=visibility,
                title=title,
            )
        except Exception as exc:
            if as_json:
                _handle_contract_error(command="post.document", source="official", request=request, exc=exc)
            _handle_error(exc)
        payload = envelope(
            command="post.document",
            source="official",
            request=request,
            data=post_create_dry_run_data(
                text=text_body,
                visibility=plan.visibility,
                media_count=plan.media_count,
                api=plan.api,
                extra={"media_path": plan.media_paths[0], "title": plan.payload["content"]["media"]["title"]},
            ),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Document post dry-run OK",
                True,
                f"visibility={visibility} | text_length={len(text_body)} | api=linkedin.posts+documents",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=author_urn,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.create_document_post(
                text=text_body,
                visibility=visibility,
                media_path=document_path,
                title=title,
            )
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.document", source="official", request=request, exc=exc)
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.document",
                source="official",
                request=request,
                data=post_text_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Document post created", True, f"id={result.post_id}\nurl={result.url}"))


@post_group.command("poll")
@click.option("--text", "text_body", required=False, help="Post body text.")
@click.option(
    "--text-file",
    type=str,
    default=None,
    help="Read post body text from a UTF-8 file, or '-' for stdin.",
)
@click.option("--question", required=True, help="Poll question, up to 140 characters.")
@click.option("--option", "options", multiple=True, required=True, help="Poll option; pass 2-4 times.")
@click.option(
    "--duration",
    type=click.Choice(POLL_DURATION_CHOICES),
    default="three-days",
    show_default=True,
)
@click.option(
    "--visibility",
    type=click.Choice(["connections", "public"]),
    default="public",
    show_default=True,
)
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_poll(
    text_body: Optional[str],
    text_file: Optional[str],
    question: str,
    options: tuple[str, ...],
    duration: str,
    visibility: str,
    dry_run: bool,
    as_json: bool,
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Publish a non-sponsored poll through LinkedIn's official Posts API."""
    request = _contract_request(
        visibility=visibility,
        dry_run=dry_run,
        media_count=0,
        text_length=None,
        question_length=len(question),
        option_count=len(options),
        duration=duration,
        author=author_urn,
    )
    try:
        text_body = _resolve_post_text(text_body, text_file)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.poll", source="official", request=request, exc=exc)
        _handle_error(exc)

    request["text_length"] = len(text_body)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=author_urn,
                linkedin_version=linkedin_version,
            ).plan_poll_post(
                text=text_body,
                question=question,
                options=options,
                duration=duration,
                visibility=visibility,
            )
        except Exception as exc:
            if as_json:
                _handle_contract_error(command="post.poll", source="official", request=request, exc=exc)
            _handle_error(exc)
        payload = envelope(
            command="post.poll",
            source="official",
            request=request,
            data=post_create_dry_run_data(
                text=text_body,
                visibility=plan.visibility,
                media_count=0,
                api=plan.api,
                extra={
                    "question_length": len(plan.payload["content"]["poll"]["question"]),
                    "option_count": len(plan.payload["content"]["poll"]["options"]),
                    "duration": plan.payload["content"]["poll"]["settings"]["duration"],
                },
            ),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Poll post dry-run OK",
                True,
                f"option_count={len(options)} | duration={plan.payload['content']['poll']['settings']['duration']}",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=author_urn,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.create_poll_post(
                text=text_body,
                visibility=visibility,
                question=question,
                options=options,
                duration=duration,
            )
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.poll", source="official", request=request, exc=exc)
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.poll",
                source="official",
                request=request,
                data=post_text_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Poll post created", True, f"id={result.post_id}\nurl={result.url}"))


@post_group.command("article")
@click.option("--text", "text_body", required=False, help="Post body text.")
@click.option(
    "--text-file",
    type=str,
    default=None,
    help="Read post body text from a UTF-8 file, or '-' for stdin.",
)
@click.option("--url", "article_url", required=True, help="Article URL to share.")
@click.option("--title", type=str, default=None, help="Optional article title.")
@click.option("--description", type=str, default=None, help="Optional article description.")
@click.option("--thumbnail", type=str, default=None, help="Optional LinkedIn image URN thumbnail.")
@click.option(
    "--visibility",
    type=click.Choice(["connections", "public"]),
    default="public",
    show_default=True,
)
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_article(
    text_body: Optional[str],
    text_file: Optional[str],
    article_url: str,
    title: Optional[str],
    description: Optional[str],
    thumbnail: Optional[str],
    visibility: str,
    dry_run: bool,
    as_json: bool,
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Publish an article/link post through the official LinkedIn Posts API."""
    request = _contract_request(
        visibility=visibility,
        dry_run=dry_run,
        media_count=0,
        text_length=None,
        url=article_url,
        author=author_urn,
    )
    try:
        text_body = _resolve_post_text(text_body, text_file)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.article", source="official", request=request, exc=exc)
        _handle_error(exc)

    request["text_length"] = len(text_body)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=author_urn,
                linkedin_version=linkedin_version,
            ).plan_article_post(
                text=text_body,
                visibility=visibility,
                url=article_url,
                title=title,
                description=description,
                thumbnail=thumbnail,
            )
        except Exception as exc:
            if as_json:
                _handle_contract_error(command="post.article", source="official", request=request, exc=exc)
            _handle_error(exc)
        payload = envelope(
            command="post.article",
            source="official",
            request=request,
            data=post_create_dry_run_data(
                text=text_body,
                visibility=plan.visibility,
                media_count=0,
                extra={"url": article_url, "api": plan.api},
            ),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Article post dry-run OK",
                True,
                f"visibility={visibility} | text_length={len(text_body)} | api=linkedin.posts",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=author_urn,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.create_article_post(
                text=text_body,
                visibility=visibility,
                url=article_url,
                title=title,
                description=description,
                thumbnail=thumbnail,
            )
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.article", source="official", request=request, exc=exc)
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.article",
                source="official",
                request=request,
                data=post_text_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Article post created", True, f"id={result.post_id}\nurl={result.url}"))


def _post_reshare_like(
    *,
    command: str,
    panel_label: str,
    parent: str,
    text_body: Optional[str],
    text_file: Optional[str],
    visibility: str,
    dry_run: bool,
    as_json: bool,
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    request = _contract_request(
        parent=parent,
        visibility=visibility,
        dry_run=dry_run,
        media_count=0,
        text_length=None,
        author=author_urn,
    )
    try:
        text_body = _resolve_post_text(text_body, text_file)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command=command, source="official", request=request, exc=exc)
        _handle_error(exc)

    request["text_length"] = len(text_body)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=author_urn,
                linkedin_version=linkedin_version,
            ).plan_reshare_post(text=text_body, parent=parent, visibility=visibility)
        except Exception as exc:
            if as_json:
                _handle_contract_error(command=command, source="official", request=request, exc=exc)
            _handle_error(exc)
        payload = envelope(
            command=command,
            source="official",
            request=request,
            data=post_create_dry_run_data(
                text=text_body,
                visibility=plan.visibility,
                media_count=0,
                extra={"parent": plan.payload["reshareContext"]["parent"], "api": plan.api},
            ),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                f"{panel_label} dry-run OK",
                True,
                f"parent={plan.payload['reshareContext']['parent']} | api=linkedin.posts",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=author_urn,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.create_reshare_post(text=text_body, parent=parent, visibility=visibility)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command=command, source="official", request=request, exc=exc)
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command=command,
                source="official",
                request=request,
                data=post_text_success_data(result),
            )
        )
        return
    console.print(build_status_panel(f"{panel_label} created", True, f"id={result.post_id}\nurl={result.url}"))


@post_group.command("reshare")
@click.argument("parent")
@click.option("--text", "text_body", required=False, help="Post body text.")
@click.option(
    "--text-file",
    type=str,
    default=None,
    help="Read post body text from a UTF-8 file, or '-' for stdin.",
)
@click.option(
    "--visibility",
    type=click.Choice(["connections", "public"]),
    default="public",
    show_default=True,
)
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_reshare(
    parent: str,
    text_body: Optional[str],
    text_file: Optional[str],
    visibility: str,
    dry_run: bool,
    as_json: bool,
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Reshare a post through the official LinkedIn Posts API."""
    _post_reshare_like(
        command="post.reshare",
        panel_label="Reshare",
        parent=parent,
        text_body=text_body,
        text_file=text_file,
        visibility=visibility,
        dry_run=dry_run,
        as_json=as_json,
        author_urn=author_urn,
        oauth_file=oauth_file,
        linkedin_version=linkedin_version,
    )


@post_group.command("quote")
@click.argument("parent")
@click.option("--text", "text_body", required=False, help="Quote commentary text.")
@click.option(
    "--text-file",
    type=str,
    default=None,
    help="Read quote commentary from a UTF-8 file, or '-' for stdin.",
)
@click.option(
    "--visibility",
    type=click.Choice(["connections", "public"]),
    default="public",
    show_default=True,
)
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_quote(
    parent: str,
    text_body: Optional[str],
    text_file: Optional[str],
    visibility: str,
    dry_run: bool,
    as_json: bool,
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Quote a post through LinkedIn's official reshare API."""
    _post_reshare_like(
        command="post.quote",
        panel_label="Quote",
        parent=parent,
        text_body=text_body,
        text_file=text_file,
        visibility=visibility,
        dry_run=dry_run,
        as_json=as_json,
        author_urn=author_urn,
        oauth_file=oauth_file,
        linkedin_version=linkedin_version,
    )


@post_group.command("repost")
@click.argument("parent")
@click.option("--visibility", type=click.Choice(["connections", "public"]), default="public", show_default=True)
@click.option("--dry-run", is_flag=True, help="Return the unsupported JSON boundary without publishing.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
def post_repost(
    parent: str,
    visibility: str,
    dry_run: bool,
    as_json: bool,
    author_urn: Optional[str],
) -> None:
    """Report that commentary-free repost is not implemented for LinkedIn."""
    request = _contract_request(
        parent=parent,
        visibility=visibility,
        dry_run=dry_run,
        media_count=0,
        text_length=0,
        author=author_urn,
    )
    _emit_unsupported_contract(
        command="post.repost",
        source="official",
        request=request,
        message=(
            "LinkedIn CLI currently supports quoted reshare with commentary via `post quote`/`post reshare`; "
            "commentary-free repost is not implemented."
        ),
        details={"use_commands": ["post quote", "post reshare"], "reason": "empty_commentary_not_supported"},
        as_json=as_json,
        title="Repost not created",
    )


@post_group.command("update")
@click.argument("post_id")
@click.option("--text", "text_body", required=False, help="Replacement post commentary.")
@click.option(
    "--text-file",
    type=str,
    default=None,
    help="Read replacement commentary from a UTF-8 file, or '-' for stdin.",
)
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_update(
    post_id: str,
    text_body: Optional[str],
    text_file: Optional[str],
    dry_run: bool,
    as_json: bool,
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Update post commentary through the official LinkedIn Posts API."""
    request = _contract_request(id=post_id, dry_run=dry_run, text_length=None, author=author_urn)
    try:
        text_body = _resolve_post_text(text_body, text_file)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.update", source="official", request=request, exc=exc)
        _handle_error(exc)

    request["text_length"] = len(text_body)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=author_urn,
                linkedin_version=linkedin_version,
            ).plan_update_post(post_id=post_id, text=text_body)
        except Exception as exc:
            if as_json:
                _handle_contract_error(command="post.update", source="official", request=request, exc=exc)
            _handle_error(exc)
        payload = envelope(
            command="post.update",
            source="official",
            request=request,
            data=post_update_dry_run_data(post_id=plan["post_id"], text=text_body),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Post update dry-run OK",
                True,
                f"id={plan['post_id']} | text_length={len(text_body)} | api=linkedin.posts.update",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=author_urn,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.update_post(post_id=post_id, text=text_body)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.update", source="official", request=request, exc=exc)
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.update",
                source="official",
                request=request,
                data=post_update_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Post updated", True, f"id={result.post_id}"))


@post_group.command("get")
@click.argument("post_id")
@click.option(
    "--view-context",
    type=click.Choice(["AUTHOR", "READER"], case_sensitive=False),
    default="AUTHOR",
    show_default=True,
)
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_get(
    post_id: str,
    view_context: str,
    as_json: bool,
    output_file: Optional[str],
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Retrieve one post through the official LinkedIn Posts API."""
    request = _contract_request(id=post_id, view_context=view_context.upper(), author=author_urn)
    try:
        with _write_api_from_options(
            author_urn=author_urn,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.get_post(post_id=post_id, view_context=view_context.upper())
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.get", source="official", request=request, exc=exc, output_file=output_file)
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.get",
                source="official",
                request=request,
                data=post_get_success_data(result),
            ),
            output_file=output_file,
        )
        return
    console.print(to_json(result.raw))


@post_group.command("list")
@click.option("--author", "author_urn", type=str, default=None, help="Author person or organization URN.")
@click.option(
    "--limit",
    "--count",
    "count",
    type=int,
    default=10,
    show_default=True,
    help="Number of posts to fetch, 1-100. --count is kept as a compatibility alias.",
)
@click.option("--start", type=int, default=0, show_default=True, help="Pagination start offset.")
@click.option(
    "--sort-by",
    type=click.Choice(["LAST_MODIFIED", "CREATED"], case_sensitive=False),
    default="LAST_MODIFIED",
    show_default=True,
)
@click.option(
    "--view-context",
    type=click.Choice(["AUTHOR", "READER"], case_sensitive=False),
    default="AUTHOR",
    show_default=True,
)
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_list(
    author_urn: Optional[str],
    count: int,
    start: int,
    sort_by: str,
    view_context: str,
    as_json: bool,
    output_file: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """List posts by author through the official LinkedIn Posts API."""
    request = _contract_request(
        author=author_urn,
        count=count,
        start=start,
        sort_by=sort_by.upper(),
        view_context=view_context.upper(),
    )
    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.list_posts_by_author(
                author_urn=author_urn,
                count=count,
                start=start,
                sort_by=sort_by.upper(),
                view_context=view_context.upper(),
            )
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="post.list", source="official", request=request, exc=exc, output_file=output_file)
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.list",
                source="official",
                request=request,
                data=post_list_success_data(result),
            ),
            output_file=output_file,
        )
        return
    console.print(to_json(result.raw))


@post_group.command("delete")
@click.argument("post_id")
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_delete(
    post_id: str,
    dry_run: bool,
    as_json: bool,
    author_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Delete a post through the official LinkedIn Posts API."""
    request = _contract_request(id=post_id, dry_run=dry_run, author=author_urn)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=author_urn,
                linkedin_version=linkedin_version,
            ).plan_delete_post(post_id=post_id)
        except Exception as exc:
            if as_json:
                _handle_contract_error(
                    command="post.delete",
                    source="official",
                    request=request,
                    exc=exc,
                )
            _handle_error(exc)
        payload = envelope(
            command="post.delete",
            source="official",
            request=request,
            data=post_delete_dry_run_data(post_id=plan.post_id),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Post delete dry-run OK",
                True,
                f"id={plan.post_id} | api=linkedin.posts.delete",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=author_urn,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.delete_post(post_id=post_id)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="post.delete",
                source="official",
                request=request,
                exc=exc,
            )
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.delete",
                source="official",
                request=request,
                data=post_delete_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Post deleted", True, f"id={result.post_id}"))


@post_group.command("legacy", hidden=True)
@click.argument("text")
@click.option("--visibility", type=click.Choice(["connections", "public"]), default="connections", show_default=True)
@click.pass_context
def post_legacy(ctx: click.Context, text: str, visibility: str) -> None:
    """Publish a new LinkedIn post through the browser fallback."""
    try:
        detail = _client_from_ctx(ctx).post(text, visibility=visibility)
    except Exception as exc:
        _handle_error(exc)
    console.print(build_status_panel("Post created", True, detail))


@cli.command()
@click.argument("identifier")
@click.option("--type", "reaction_type", type=click.Choice(REACTION_CHOICES), default="like", show_default=True)
@click.pass_context
def react(ctx: click.Context, identifier: str, reaction_type: str) -> None:
    """React to a LinkedIn activity."""
    try:
        detail = _client_from_ctx(ctx).react(identifier, reaction_type)
    except Exception as exc:
        _handle_error(exc)
    console.print(build_status_panel("Reaction applied", True, detail))


@cli.command()
@click.argument("identifier")
@click.pass_context
def unreact(ctx: click.Context, identifier: str) -> None:
    """Remove the current reaction from a LinkedIn activity."""
    try:
        detail = _client_from_ctx(ctx).unreact(identifier)
    except Exception as exc:
        _handle_error(exc)
    console.print(build_status_panel("Reaction removed", True, detail))


@cli.command()
@click.argument("identifier")
@click.pass_context
def save(ctx: click.Context, identifier: str) -> None:
    """Save a LinkedIn activity."""
    try:
        detail = _client_from_ctx(ctx).save(identifier)
    except Exception as exc:
        _handle_error(exc)
    console.print(build_status_panel("Post saved", True, detail))


@cli.command()
@click.argument("identifier")
@click.pass_context
def unsave(ctx: click.Context, identifier: str) -> None:
    """Remove a saved LinkedIn activity."""
    try:
        detail = _client_from_ctx(ctx).unsave(identifier)
    except Exception as exc:
        _handle_error(exc)
    console.print(build_status_panel("Post unsaved", True, detail))


@cli.group("comment", cls=LegacyCommentGroup)
def comment_group() -> None:
    """Inspect and mutate comments through official LinkedIn APIs."""


@comment_group.command("list")
@click.argument("entity")
@click.option("--count", type=int, default=10, show_default=True, help="Number of comments to fetch.")
@click.option("--start", type=int, default=0, show_default=True, help="Pagination start offset.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def comment_list(
    entity: str,
    count: int,
    start: int,
    as_json: bool,
    output_file: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """List comments through the official LinkedIn Comments API."""
    request = _contract_request(entity=entity, count=count, start=start)
    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.list_comments(entity=entity, count=count, start=start)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="comment.list", source="official", request=request, exc=exc, output_file=output_file)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="comment.list",
                source="official",
                request=request,
                data=comment_list_success_data(result),
            ),
            output_file=output_file,
        )
        return
    console.print(to_json(result.raw))


@comment_group.command("get")
@click.argument("entity")
@click.argument("comment_id")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def comment_get(
    entity: str,
    comment_id: str,
    as_json: bool,
    output_file: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Get one comment through the official LinkedIn Comments API."""
    request = _contract_request(entity=entity, comment_id=comment_id)
    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.get_comment(entity=entity, comment_id=comment_id)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="comment.get", source="official", request=request, exc=exc, output_file=output_file)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="comment.get",
                source="official",
                request=request,
                data=comment_success_data(result),
            ),
            output_file=output_file,
        )
        return
    console.print(to_json(result.raw))


@comment_group.command("create")
@click.argument("entity")
@click.option("--text", "text_body", required=False, help="Comment text.")
@click.option(
    "--text-file",
    type=str,
    default=None,
    help="Read comment text from a UTF-8 file, or '-' for stdin.",
)
@click.option("--parent-comment", type=str, default=None, help="Optional parent comment URN.")
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--actor", "actor_urn", type=str, default=None, help="Override the actor URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def comment_create(
    entity: str,
    text_body: Optional[str],
    text_file: Optional[str],
    parent_comment: Optional[str],
    dry_run: bool,
    as_json: bool,
    actor_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Create a comment through the official LinkedIn Comments API."""
    request = _contract_request(
        entity=entity,
        parent_comment=parent_comment,
        dry_run=dry_run,
        text_length=None,
        actor=actor_urn,
    )
    try:
        text_body = _resolve_post_text(text_body, text_file)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="comment.create", source="official", request=request, exc=exc)
        _handle_error(exc)

    request["text_length"] = len(text_body)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=actor_urn,
                linkedin_version=linkedin_version,
            ).plan_comment_create(entity=entity, text=text_body, actor_urn=actor_urn, parent_comment=parent_comment)
        except Exception as exc:
            if as_json:
                _handle_contract_error(command="comment.create", source="official", request=request, exc=exc)
            _handle_error(exc)
        payload = envelope(
            command="comment.create",
            source="official",
            request=request,
            data=comment_dry_run_data(planned=plan),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Comment create dry-run OK",
                True,
                f"entity={plan['entity']} | text_length={len(text_body)} | api=linkedin.comments",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.create_comment(
                entity=entity,
                text=text_body,
                actor_urn=actor_urn,
                parent_comment=parent_comment,
            )
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="comment.create", source="official", request=request, exc=exc)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="comment.create",
                source="official",
                request=request,
                data=comment_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Comment created", True, f"id={result.comment_id}"))


@comment_group.command("update")
@click.argument("entity")
@click.argument("comment_id")
@click.option("--text", "text_body", required=False, help="Replacement comment text.")
@click.option(
    "--text-file",
    type=str,
    default=None,
    help="Read replacement comment text from a UTF-8 file, or '-' for stdin.",
)
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--actor", "actor_urn", type=str, default=None, help="Override the actor URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def comment_update(
    entity: str,
    comment_id: str,
    text_body: Optional[str],
    text_file: Optional[str],
    dry_run: bool,
    as_json: bool,
    actor_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Update a comment through the official LinkedIn Comments API."""
    request = _contract_request(entity=entity, comment_id=comment_id, dry_run=dry_run, text_length=None, actor=actor_urn)
    try:
        text_body = _resolve_post_text(text_body, text_file)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="comment.update", source="official", request=request, exc=exc)
        _handle_error(exc)

    request["text_length"] = len(text_body)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=actor_urn,
                linkedin_version=linkedin_version,
            ).plan_comment_update(entity=entity, comment_id=comment_id, text=text_body, actor_urn=actor_urn)
        except Exception as exc:
            if as_json:
                _handle_contract_error(command="comment.update", source="official", request=request, exc=exc)
            _handle_error(exc)
        payload = envelope(
            command="comment.update",
            source="official",
            request=request,
            data=social_action_dry_run_data(
                action="comment.update",
                target_id=plan["entity"],
                planned=plan,
            ),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Comment update dry-run OK",
                True,
                f"entity={plan['entity']} | comment_id={plan['comment_id']} | api=linkedin.comments.update",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.update_comment(
                entity=entity,
                comment_id=comment_id,
                text=text_body,
                actor_urn=actor_urn,
            )
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="comment.update", source="official", request=request, exc=exc)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="comment.update",
                source="official",
                request=request,
                data=social_action_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Comment updated", True, f"id={comment_id}"))


@comment_group.command("delete")
@click.argument("entity")
@click.argument("comment_id")
@click.option("--actor", "actor_urn", type=str, default=None, help="Override actor person or organization URN.")
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def comment_delete(
    entity: str,
    comment_id: str,
    actor_urn: Optional[str],
    dry_run: bool,
    as_json: bool,
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Delete a comment through the official LinkedIn Comments API."""
    request = _contract_request(entity=entity, comment_id=comment_id, actor=actor_urn, dry_run=dry_run)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=actor_urn,
                linkedin_version=linkedin_version,
            ).plan_comment_delete(entity=entity, comment_id=comment_id, actor_urn=actor_urn)
        except Exception as exc:
            if as_json:
                _handle_contract_error(command="comment.delete", source="official", request=request, exc=exc)
            _handle_error(exc)
        payload = envelope(
            command="comment.delete",
            source="official",
            request=request,
            data=social_action_dry_run_data(
                action="comment.delete",
                target_id=plan["entity"],
                planned=plan,
            ),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Comment delete dry-run OK",
                True,
                f"entity={plan['entity']} | comment_id={plan['comment_id']} | api=linkedin.comments.delete",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.delete_comment(entity=entity, comment_id=comment_id, actor_urn=actor_urn)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="comment.delete", source="official", request=request, exc=exc)
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="comment.delete",
                source="official",
                request=request,
                data=social_action_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Comment deleted", True, f"id={comment_id}"))


@comment_group.command("legacy", hidden=True)
@click.argument("identifier")
@click.argument("text")
@click.pass_context
def comment_legacy(ctx: click.Context, identifier: str, text: str) -> None:
    """Comment on a LinkedIn activity through the browser fallback."""
    try:
        detail = _client_from_ctx(ctx).comment(identifier, text)
    except Exception as exc:
        _handle_error(exc)
    console.print(build_status_panel("Comment posted", True, detail))


@cli.group("reaction")
def reaction_group() -> None:
    """Inspect and mutate reactions through official LinkedIn APIs."""


@reaction_group.command("list")
@click.argument("entity")
@click.option("--count", type=int, default=10, show_default=True, help="Number of reactions to fetch.")
@click.option("--start", type=int, default=0, show_default=True, help="Pagination start offset.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def reaction_list(
    entity: str,
    count: int,
    start: int,
    as_json: bool,
    output_file: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """List reactions through the official LinkedIn Reactions API."""
    request = _contract_request(entity=entity, count=count, start=start)
    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.list_reactions(entity=entity, count=count, start=start)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="reaction.list", source="official", request=request, exc=exc, output_file=output_file)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="reaction.list",
                source="official",
                request=request,
                data=reaction_list_success_data(result),
            ),
            output_file=output_file,
        )
        return
    console.print(to_json(result.raw))


@reaction_group.command("get")
@click.argument("entity")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.option("--actor", "actor_urn", type=str, default=None, help="Override the actor URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def reaction_get(
    entity: str,
    as_json: bool,
    output_file: Optional[str],
    actor_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Get the current actor's reaction through the official LinkedIn Reactions API."""
    request = _contract_request(entity=entity, actor=actor_urn)
    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.get_reaction(entity=entity, actor_urn=actor_urn)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="reaction.get", source="official", request=request, exc=exc, output_file=output_file)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="reaction.get",
                source="official",
                request=request,
                data=reaction_success_data(result),
            ),
            output_file=output_file,
        )
        return
    console.print(to_json(result.raw))


@reaction_group.command("create")
@click.argument("entity")
@click.option(
    "--type",
    "reaction_type",
    type=click.Choice(REACTION_CHOICES + ["funny"], case_sensitive=False),
    default="like",
    show_default=True,
)
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--actor", "actor_urn", type=str, default=None, help="Override the actor URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def reaction_create(
    entity: str,
    reaction_type: str,
    dry_run: bool,
    as_json: bool,
    actor_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Create a reaction through the official LinkedIn Reactions API."""
    request = _contract_request(entity=entity, reaction_type=reaction_type, actor=actor_urn, dry_run=dry_run)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=actor_urn,
                linkedin_version=linkedin_version,
            ).plan_reaction_create(entity=entity, reaction_type=reaction_type, actor_urn=actor_urn)
        except Exception as exc:
            if as_json:
                _handle_contract_error(command="reaction.create", source="official", request=request, exc=exc)
            _handle_error(exc)
        payload = envelope(
            command="reaction.create",
            source="official",
            request=request,
            data=reaction_dry_run_data(planned=plan),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Reaction create dry-run OK",
                True,
                f"entity={plan['entity']} | reaction_type={plan['reaction_type']} | api=linkedin.reactions",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.create_reaction(
                entity=entity,
                reaction_type=reaction_type,
                actor_urn=actor_urn,
            )
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="reaction.create", source="official", request=request, exc=exc)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="reaction.create",
                source="official",
                request=request,
                data=reaction_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Reaction created", True, f"entity={entity}"))


@reaction_group.command("delete")
@click.argument("entity")
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--actor", "actor_urn", type=str, default=None, help="Override the actor URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def reaction_delete(
    entity: str,
    dry_run: bool,
    as_json: bool,
    actor_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Delete the current actor's reaction through the official LinkedIn Reactions API."""
    request = _contract_request(entity=entity, actor=actor_urn, dry_run=dry_run)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=actor_urn,
                linkedin_version=linkedin_version,
            ).plan_reaction_delete(entity=entity, actor_urn=actor_urn)
        except Exception as exc:
            if as_json:
                _handle_contract_error(command="reaction.delete", source="official", request=request, exc=exc)
            _handle_error(exc)
        payload = envelope(
            command="reaction.delete",
            source="official",
            request=request,
            data=social_action_dry_run_data(
                action="reaction.delete",
                target_id=plan["entity"],
                planned=plan,
            ),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Reaction delete dry-run OK",
                True,
                f"entity={plan['entity']} | api=linkedin.reactions.delete",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.delete_reaction(entity=entity, actor_urn=actor_urn)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="reaction.delete", source="official", request=request, exc=exc)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="reaction.delete",
                source="official",
                request=request,
                data=social_action_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Reaction deleted", True, f"entity={entity}"))


@cli.group("social")
def social_group() -> None:
    """Inspect and mutate social metadata through official LinkedIn APIs."""


@social_group.command("metadata")
@click.argument("entity")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def social_metadata(
    entity: str,
    as_json: bool,
    output_file: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Get social metadata through the official LinkedIn Social Metadata API."""
    request = _contract_request(entity=entity)
    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.get_social_metadata(entity=entity)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="social.metadata", source="official", request=request, exc=exc, output_file=output_file)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="social.metadata",
                source="official",
                request=request,
                data=social_metadata_success_data(result),
            ),
            output_file=output_file,
        )
        return
    console.print(to_json(result.raw))


@social_group.command("comments-state")
@click.argument("entity")
@click.option("--state", type=click.Choice(["open", "closed"], case_sensitive=False), required=True)
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@_contract_output_option
@click.option("--actor", "actor_urn", type=str, default=None, help="Override the actor URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def social_comments_state(
    entity: str,
    state: str,
    dry_run: bool,
    as_json: bool,
    actor_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Open or close comments through the official LinkedIn Social Metadata API."""
    request = _contract_request(entity=entity, state=state, actor=actor_urn, dry_run=dry_run)
    if dry_run:
        try:
            plan = LinkedInWriteAPI.for_dry_run(
                author_urn=actor_urn,
                linkedin_version=linkedin_version,
            ).plan_comments_state(entity=entity, state=state, actor_urn=actor_urn)
        except Exception as exc:
            if as_json:
                _handle_contract_error(
                    command="social.comments_state",
                    source="official",
                    request=request,
                    exc=exc,
                )
            _handle_error(exc)
        payload = envelope(
            command="social.comments_state",
            source="official",
            request=request,
            data=social_metadata_dry_run_data(planned=plan),
        )
        if as_json:
            _emit_contract(payload)
            return
        console.print(
            build_status_panel(
                "Comments state dry-run OK",
                True,
                f"entity={plan['entity']} | comments_state={plan['comments_state']} | "
                "api=linkedin.social_metadata.update",
            )
        )
        return

    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.update_comments_state(entity=entity, state=state, actor_urn=actor_urn)
    except Exception as exc:
        if as_json:
            _handle_contract_error(
                command="social.comments_state",
                source="official",
                request=request,
                exc=exc,
            )
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="social.comments_state",
                source="official",
                request=request,
                data=social_metadata_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Comments state updated", True, f"entity={entity} state={state}"))


@cli.group("insights")
def insights_group() -> None:
    """Read LinkedIn insights-compatible official metadata."""


@insights_group.command("media")
@click.argument("entity")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def insights_media(
    entity: str,
    as_json: bool,
    output_file: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Read media-level social metadata as an insights envelope."""
    request = _contract_request(entity=entity)
    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.get_social_metadata(entity=entity)
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="insights.media", source="official", request=request, exc=exc, output_file=output_file)
        _handle_error(exc)
    data = insights_data(result, scope="media")
    if as_json:
        _emit_contract(
            envelope(
                command="insights.media",
                source="official",
                request=request,
                data=data,
            ),
            output_file=output_file,
        )
        return
    console.print(to_json(data))


@insights_group.command("organization")
@click.argument("organization")
@click.option("--share", "shares", multiple=True, help="Optional share URN/id filter. Repeatable.")
@click.option("--ugc-post", "ugc_posts", multiple=True, help="Optional UGC post URN/id filter. Repeatable.")
@click.option("--time-granularity", type=click.Choice(["day", "month", "DAY", "MONTH"]), default=None, help="Optional time bucket.")
@click.option("--time-start", type=int, default=None, help="Optional epoch-millis time range start.")
@click.option("--time-end", type=int, default=None, help="Optional epoch-millis time range end.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def insights_organization(
    organization: str,
    shares: tuple[str, ...],
    ugc_posts: tuple[str, ...],
    time_granularity: Optional[str],
    time_start: Optional[int],
    time_end: Optional[int],
    as_json: bool,
    output_file: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Read organization share statistics through LinkedIn's official analytics API."""
    request = _contract_request(
        organization=organization,
        shares=list(shares),
        ugc_posts=list(ugc_posts),
        time_granularity=time_granularity,
        time_start=time_start,
        time_end=time_end,
    )
    try:
        with _write_api_from_options(
            author_urn=None,
            oauth_file=oauth_file,
            linkedin_version=linkedin_version,
        ) as api:
            result = api.get_organization_share_statistics(
                organization=organization,
                shares=shares,
                ugc_posts=ugc_posts,
                time_granularity=time_granularity,
                time_start=time_start,
                time_end=time_end,
            )
    except Exception as exc:
        if as_json:
            _handle_contract_error(command="insights.organization", source="official", request=request, exc=exc, output_file=output_file)
        _handle_error(exc)
    data = organization_insights_data(result)
    if as_json:
        _emit_contract(
            envelope(
                command="insights.organization",
                source="official",
                request=request,
                data=data,
            ),
            output_file=output_file,
        )
        return
    console.print(to_json(data))


@insights_group.command("user")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write JSON output to a file.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="Accepted for contract parity.")
@click.option("--linkedin-version", type=str, default=None, help="Accepted for contract parity.")
def insights_user(
    as_json: bool,
    output_file: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Return unsupported for account-level LinkedIn insights."""
    request = _contract_request(
        oauth_file=bool(oauth_file),
        linkedin_version=linkedin_version,
    )
    _emit_unsupported_contract(
        command="insights.user",
        source="official",
        request=request,
        message=(
            "LinkedIn CLI currently exposes media-level social metadata as insights; "
            "account-level insights are not implemented."
        ),
        details={"use_commands": ["insights media", "social metadata"], "reason": "account_insights_not_implemented"},
        as_json=as_json,
        title="Account insights unavailable",
        output_file=output_file,
    )


def main() -> None:
    """Entry point for `python -m linkedin_cli.cli`."""
    try:
        cli(standalone_mode=False)
    except LinkedInClientError as exc:
        _handle_error(exc)
    except click.ClickException as exc:
        exc.show()
        raise SystemExit(exc.exit_code) from exc


if __name__ == "__main__":  # pragma: no cover
    main()
