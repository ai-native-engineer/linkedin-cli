"""CLI entrypoint for linkedin-cli."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from . import __version__
from .auth import AuthenticationError
from .auth import collect_auth_diagnostics
from .auth import resolve_auth_session
from .api import LinkedInWriteAPI
from .browser import BrowserActionError
from .client import LinkedInClient, LinkedInClientError
from .config import AppConfig, load_config
from .constants import COOKIE_REQUIRED_NAMES
from .contract import activity_data
from .contract import auth_status_data
from .contract import comment_list_success_data
from .contract import comment_success_data
from .contract import envelope
from .contract import error_envelope
from .contract import feed_data
from .contract import post_create_dry_run_data
from .contract import post_delete_dry_run_data
from .contract import post_delete_success_data
from .contract import post_get_success_data
from .contract import post_list_success_data
from .contract import post_media_dry_run_data
from .contract import post_text_dry_run_data
from .contract import post_text_success_data
from .contract import post_update_dry_run_data
from .contract import post_update_success_data
from .contract import profile_data
from .contract import reaction_list_success_data
from .contract import reaction_success_data
from .contract import saved_unsave_success_data
from .contract import search_data
from .contract import social_action_success_data
from .contract import social_metadata_success_data
from .contract import to_contract_json
from .formatter import (
    build_search_table,
    build_status_panel,
    print_post_detail,
    print_post_table,
    print_profile,
)
from .oauth import OAuthConfigError
from .oauth import default_oauth_path
from .oauth_flow import DEFAULT_REDIRECT_URI
from .oauth_flow import DEFAULT_SCOPES
from .oauth_flow import ENV_CLIENT_ID
from .oauth_flow import ENV_CLIENT_SECRET
from .oauth_flow import ENV_REDIRECT_URI
from .oauth_flow import OAuthFlowError
from .oauth_flow import run_oauth_login
from .publisher import LinkedInPublishError
from .serialization import posts_to_json, profile_to_dict, search_results_to_json, to_json
from .transport import LinkedInTransportError

console = Console(stderr=True)
REACTION_CHOICES = ["like", "celebrate", "support", "love", "insightful", "curious"]
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


def _write_output(output_file: Optional[str], payload: str) -> None:
    if output_file:
        Path(output_file).write_text(payload + "\n", encoding="utf-8")


def _handle_error(exc: Exception) -> None:
    console.print(build_status_panel("linkedin-cli", False, str(exc)))
    raise SystemExit(1) from exc


def _contract_request(**kwargs) -> dict:
    return kwargs


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
    if not success:
        raise SystemExit(1)


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
        missing = sorted(name for name in COOKIE_REQUIRED_NAMES if not session.cookie_jar.get(name))
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
        posts = _client_from_ctx(ctx).feed(limit=limit)
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
                data=feed_data(posts, cursor=cursor),
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
                data=feed_data(posts, cursor=cursor),
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
        results = _client_from_ctx(ctx).search(query, limit=limit)
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
                data=search_data(results, cursor=cursor),
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
        posts = _client_from_ctx(ctx).get_profile_posts(identifier, limit=limit)
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
        data=feed_data(posts, cursor=cursor),
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
@click.pass_context
def profile(ctx: click.Context, identifier: str, as_json: bool) -> None:
    """Fetch a LinkedIn profile by public id or URL."""
    try:
        result = _client_from_ctx(ctx).get_profile(identifier)
    except Exception as exc:
        _handle_error(exc)
    if as_json:
        click.echo(to_json(profile_to_dict(result)))
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
@click.pass_context
def activity(ctx: click.Context, identifier: str, as_json: bool) -> None:
    """Fetch a LinkedIn activity detail."""
    try:
        post = _client_from_ctx(ctx).get_activity(identifier)
    except Exception as exc:
        _handle_error(exc)
    payload = to_json(post)
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
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.pass_context
def saved_unsave(ctx: click.Context, identifier: str, as_json: bool) -> None:
    """Remove one LinkedIn activity from saved posts."""
    request = _contract_request(identifier=identifier, dry_run=False)
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
            _handle_contract_error(command="post.reshare", source="official", request=request, exc=exc)
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
                _handle_contract_error(command="post.reshare", source="official", request=request, exc=exc)
            _handle_error(exc)
        payload = envelope(
            command="post.reshare",
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
                "Reshare dry-run OK",
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
            _handle_contract_error(command="post.reshare", source="official", request=request, exc=exc)
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.reshare",
                source="official",
                request=request,
                data=post_text_success_data(result),
            )
        )
        return
    console.print(build_status_panel("Reshare created", True, f"id={result.post_id}\nurl={result.url}"))


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
@click.option("--author", "author_urn", type=str, default=None, help="Override the author URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_get(
    post_id: str,
    view_context: str,
    as_json: bool,
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
            _handle_contract_error(command="post.get", source="official", request=request, exc=exc)
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.get",
                source="official",
                request=request,
                data=post_get_success_data(result),
            )
        )
        return
    console.print(to_json(result.raw))


@post_group.command("list")
@click.option("--author", "author_urn", type=str, default=None, help="Author person or organization URN.")
@click.option("--count", type=int, default=10, show_default=True, help="Number of posts to fetch, 1-100.")
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
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def post_list(
    author_urn: Optional[str],
    count: int,
    start: int,
    sort_by: str,
    view_context: str,
    as_json: bool,
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
            _handle_contract_error(command="post.list", source="official", request=request, exc=exc)
        _handle_error(exc)

    if as_json:
        _emit_contract(
            envelope(
                command="post.list",
                source="official",
                request=request,
                data=post_list_success_data(result),
            )
        )
        return
    console.print(to_json(result.raw))


@post_group.command("delete")
@click.argument("post_id")
@click.option("--dry-run", is_flag=True, help="Validate and print the planned official API request.")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
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
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def comment_list(
    entity: str,
    count: int,
    start: int,
    as_json: bool,
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
            _handle_contract_error(command="comment.list", source="official", request=request, exc=exc)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="comment.list",
                source="official",
                request=request,
                data=comment_list_success_data(result),
            )
        )
        return
    console.print(to_json(result.raw))


@comment_group.command("get")
@click.argument("entity")
@click.argument("comment_id")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def comment_get(
    entity: str,
    comment_id: str,
    as_json: bool,
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
            _handle_contract_error(command="comment.get", source="official", request=request, exc=exc)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="comment.get",
                source="official",
                request=request,
                data=comment_success_data(result),
            )
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
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--actor", "actor_urn", type=str, default=None, help="Override the actor URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def comment_create(
    entity: str,
    text_body: Optional[str],
    text_file: Optional[str],
    parent_comment: Optional[str],
    as_json: bool,
    actor_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Create a comment through the official LinkedIn Comments API."""
    request = _contract_request(
        entity=entity,
        parent_comment=parent_comment,
        text_length=None,
        actor=actor_urn,
    )
    try:
        text_body = _resolve_post_text(text_body, text_file)
        request["text_length"] = len(text_body)
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
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--actor", "actor_urn", type=str, default=None, help="Override the actor URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def comment_update(
    entity: str,
    comment_id: str,
    text_body: Optional[str],
    text_file: Optional[str],
    as_json: bool,
    actor_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Update a comment through the official LinkedIn Comments API."""
    request = _contract_request(entity=entity, comment_id=comment_id, text_length=None, actor=actor_urn)
    try:
        text_body = _resolve_post_text(text_body, text_file)
        request["text_length"] = len(text_body)
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
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def reaction_list(
    entity: str,
    count: int,
    start: int,
    as_json: bool,
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
            _handle_contract_error(command="reaction.list", source="official", request=request, exc=exc)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="reaction.list",
                source="official",
                request=request,
                data=reaction_list_success_data(result),
            )
        )
        return
    console.print(to_json(result.raw))


@reaction_group.command("get")
@click.argument("entity")
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--actor", "actor_urn", type=str, default=None, help="Override the actor URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def reaction_get(
    entity: str,
    as_json: bool,
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
            _handle_contract_error(command="reaction.get", source="official", request=request, exc=exc)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="reaction.get",
                source="official",
                request=request,
                data=reaction_success_data(result),
            )
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
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--actor", "actor_urn", type=str, default=None, help="Override the actor URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def reaction_create(
    entity: str,
    reaction_type: str,
    as_json: bool,
    actor_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Create a reaction through the official LinkedIn Reactions API."""
    request = _contract_request(entity=entity, reaction_type=reaction_type, actor=actor_urn)
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
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--actor", "actor_urn", type=str, default=None, help="Override the actor URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def reaction_delete(
    entity: str,
    as_json: bool,
    actor_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Delete the current actor's reaction through the official LinkedIn Reactions API."""
    request = _contract_request(entity=entity, actor=actor_urn)
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
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def social_metadata(
    entity: str,
    as_json: bool,
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
            _handle_contract_error(command="social.metadata", source="official", request=request, exc=exc)
        _handle_error(exc)
    if as_json:
        _emit_contract(
            envelope(
                command="social.metadata",
                source="official",
                request=request,
                data=social_metadata_success_data(result),
            )
        )
        return
    console.print(to_json(result.raw))


@social_group.command("comments-state")
@click.argument("entity")
@click.option("--state", type=click.Choice(["open", "closed"], case_sensitive=False), required=True)
@click.option("--json", "as_json", is_flag=True, help="Emit SNS JSON Contract v1.")
@click.option("--actor", "actor_urn", type=str, default=None, help="Override the actor URN.")
@click.option("--oauth-file", type=click.Path(dir_okay=False, path_type=str), default=None, help="OAuth token JSON file.")
@click.option("--linkedin-version", type=str, default=None, help="LinkedIn version metadata override.")
def social_comments_state(
    entity: str,
    state: str,
    as_json: bool,
    actor_urn: Optional[str],
    oauth_file: Optional[str],
    linkedin_version: Optional[str],
) -> None:
    """Open or close comments through the official LinkedIn Social Metadata API."""
    request = _contract_request(entity=entity, state=state, actor=actor_urn)
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
