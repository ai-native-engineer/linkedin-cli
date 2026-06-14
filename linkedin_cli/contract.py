"""SNS JSON Contract v1 helpers for linkedin-cli."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Iterable, Optional

from . import __version__
from .models import Post
from .models import Profile
from .models import SearchResult
from .publisher import DeleteResult
from .publisher import PublishResult
from .serialization import to_dict

SCHEMA_VERSION = "sns-json-v1"
PLATFORM = "linkedin"
CLI_NAME = "linkedin-cli"


def utc_now_iso() -> str:
    """Return the current UTC timestamp in contract format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def envelope(
    *,
    command: str,
    source: str,
    request: dict[str, Any],
    data: Optional[dict[str, Any]],
    ok: bool = True,
    error: Optional[dict[str, Any]] = None,
    warnings: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Build a SNS JSON Contract v1 envelope."""
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "platform": PLATFORM,
        "command": command,
        "source": source,
        "request": request,
        "data": data if ok else None,
        "error": None if ok else error,
        "warnings": warnings or [],
        "meta": {
            "generated_at": utc_now_iso(),
            "cli_name": CLI_NAME,
            "cli_version": __version__,
        },
    }


def error_envelope(
    *,
    command: str,
    source: str,
    request: dict[str, Any],
    code: str,
    message: str,
    retryable: bool = False,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a failure envelope."""
    return envelope(
        command=command,
        source=source,
        request=request,
        data=None,
        ok=False,
        error={
            "code": code,
            "message": message,
            "retryable": retryable,
            "details": details or {},
        },
    )


def to_contract_json(payload: dict[str, Any]) -> str:
    """Serialize a contract payload."""
    return json.dumps(payload, ensure_ascii=False, indent=2)


def feed_data(
    posts: Iterable[Post],
    *,
    cursor: Optional[str] = None,
    next_cursor: Optional[str] = None,
    has_more: bool = False,
) -> dict[str, Any]:
    """Build `read.feed` data."""
    return {
        "posts": [post_to_contract(item, source="unofficial") for item in posts],
        "paging": {
            "cursor": cursor,
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
    }


def profile_data(profile: Profile) -> dict[str, Any]:
    """Build `read.profile` data."""
    return {
        "profile": {
            "id": _empty_to_none(profile.urn),
            "handle": _empty_to_none(profile.public_id),
            "name": _empty_to_none(profile.full_name),
            "headline": _empty_to_none(profile.headline),
            "url": _empty_to_none(profile.profile_url),
            "avatar_url": _empty_to_none(profile.photo_url),
            "bio": _empty_to_none(profile.summary),
            "location": _empty_to_none(profile.location),
            "metrics": {
                "followers": _coerce_metric(profile.followers_count),
                "connections": _coerce_metric(profile.connections_count),
            },
            "source": "unofficial",
            "raw": to_dict(profile),
        }
    }


def search_data(
    results: Iterable[SearchResult],
    *,
    cursor: Optional[str] = None,
    next_cursor: Optional[str] = None,
    has_more: bool = False,
) -> dict[str, Any]:
    """Build `read.search` data."""
    return {
        "results": [search_result_to_contract(item) for item in results],
        "paging": {
            "cursor": cursor,
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
    }


def search_result_to_contract(result: SearchResult) -> dict[str, Any]:
    """Convert the internal SearchResult model to the SNS JSON Contract result shape."""
    identifier = None
    if result.profile:
        identifier = result.profile.urn or result.profile.public_id
    elif result.post:
        identifier = result.post.urn
    return {
        "type": _empty_to_none(result.kind),
        "id": _empty_to_none(identifier),
        "title": _empty_to_none(result.title),
        "subtitle": _empty_to_none(result.subtitle),
        "url": _empty_to_none(result.url),
        "snippet": _empty_to_none(result.snippet),
        "source": "unofficial",
        "raw": to_dict(result),
    }


def post_to_contract(post: Post, *, source: str) -> dict[str, Any]:
    """Convert the internal Post model to the SNS JSON Contract post shape."""
    raw = to_dict(post)
    return {
        "id": _empty_to_none(post.urn),
        "url": _empty_to_none(post.url),
        "author": {
            "id": _empty_to_none(post.author.urn),
            "name": _empty_to_none(post.author.name),
            "handle": _empty_to_none(post.author.public_id),
            "url": _empty_to_none(post.author.profile_url),
            "avatar_url": _empty_to_none(post.author.avatar_url),
        },
        "text": _empty_to_none(post.text),
        "created_at": _coerce_utc_timestamp(post.created_at),
        "edited_at": _coerce_utc_timestamp(post.edited_at),
        "metrics": {
            "likes": _coerce_metric(
                post.metrics.reactions
                if post.metrics.reactions is not None
                else (post.reactions.total or None)
            ),
            "comments": _coerce_metric(post.metrics.comments),
            "reposts": _coerce_metric(post.metrics.reposts),
            "views": _coerce_metric(post.metrics.impressions, unknown_zero=True),
        },
        "media": [
            {
                "type": _empty_to_none(item.kind),
                "url": _empty_to_none(item.url),
                "thumbnail_url": _empty_to_none(item.thumbnail_url),
                "alt_text": _empty_to_none(item.alt_text),
                "width": item.width,
                "height": item.height,
            }
            for item in post.media
        ],
        "source": source,
        "raw": raw,
    }


def post_text_dry_run_data(*, text: str, visibility: str) -> dict[str, Any]:
    """Build dry-run data for `post.text`."""
    return {
        "dry_run": True,
        "post": None,
        "planned": {
            "visibility": visibility,
            "text_length": len(text),
            "media_count": 0,
            "api": "linkedin.ugcPosts",
        },
    }


def post_media_dry_run_data(*, text: str, visibility: str, media_count: int) -> dict[str, Any]:
    """Build dry-run data for `post.media`."""
    return {
        "dry_run": True,
        "post": None,
        "planned": {
            "visibility": visibility,
            "text_length": len(text),
            "media_count": media_count,
            "api": "linkedin.ugcPosts+assets",
        },
    }


def post_text_success_data(result: PublishResult) -> dict[str, Any]:
    """Build success data for `post.text`."""
    return {
        "dry_run": False,
        "post": {
            "id": result.post_id,
            "url": result.url,
            "created_at": result.created_at,
            "visibility": result.visibility,
            "source": "official",
            "raw": result.raw,
        },
        "planned": None,
    }


def post_delete_dry_run_data(*, post_id: str) -> dict[str, Any]:
    """Build dry-run data for `post.delete`."""
    return {
        "dry_run": True,
        "post": None,
        "planned": {
            "id": post_id,
            "api": "linkedin.posts.delete",
        },
    }


def post_delete_success_data(result: DeleteResult) -> dict[str, Any]:
    """Build success data for `post.delete`."""
    return {
        "dry_run": False,
        "post": {
            "id": result.post_id,
            "deleted": True,
            "deleted_at": result.deleted_at,
            "source": "official",
            "raw": result.raw,
        },
        "planned": None,
    }


def saved_unsave_success_data(*, identifier: str, detail: str) -> dict[str, Any]:
    """Build success data for `saved.unsave`."""
    return {
        "action": "unsave",
        "target": {
            "id": identifier,
        },
        "result": {
            "detail": detail,
        },
    }


def _empty_to_none(value: Any) -> Any:
    if value == "":
        return None
    return value


def _coerce_metric(value: Any, *, unknown_zero: bool = False) -> Optional[int]:
    if value is None:
        return None
    try:
        metric = int(value)
    except (TypeError, ValueError):
        return None
    if metric == 0 and unknown_zero:
        return None
    return metric


def _coerce_utc_timestamp(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return (
            datetime.fromtimestamp(seconds, tz=timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _coerce_utc_timestamp(int(text))
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
