"""SNS JSON Contract v1 helpers for linkedin-cli."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Iterable, Optional

from . import __version__
from .models import Comment
from .models import Post
from .models import Profile
from .models import SearchResult
from .publisher import CommentListResult
from .publisher import CommentResult
from .publisher import DeleteResult
from .publisher import GetPostResult
from .publisher import ListPostsResult
from .publisher import OrganizationShareStatisticsResult
from .publisher import PublishResult
from .publisher import ReactionResult
from .publisher import SocialActionResult
from .publisher import SocialMetadataResult
from .publisher import UpdateResult
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


def activity_data(post: Post) -> dict[str, Any]:
    """Build `read.activity` data."""
    return {
        "post": post_to_contract(post, source="unofficial"),
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
            "raw": _redact_secrets(to_dict(profile)),
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
        "raw": _redact_secrets(to_dict(result)),
    }


def comments_data(
    comments: Iterable[Comment],
    *,
    cursor: Optional[str] = None,
    next_cursor: Optional[str] = None,
    has_more: bool = False,
) -> dict[str, Any]:
    """Build `read.comments` data."""
    return {
        "comments": [comment_to_contract(item, source="unofficial") for item in comments],
        "paging": {
            "cursor": cursor,
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
    }


def comment_to_contract(comment: Comment, *, source: str) -> dict[str, Any]:
    """Convert the internal Comment model to the SNS JSON Contract comment shape."""
    raw = _redact_secrets(to_dict(comment))
    return {
        "id": _empty_to_none(comment.urn),
        "post_id": _empty_to_none(comment.post_urn),
        "author": {
            "id": _empty_to_none(comment.author.urn),
            "name": _empty_to_none(comment.author.name),
            "handle": _empty_to_none(comment.author.public_id),
            "url": _empty_to_none(comment.author.profile_url),
            "avatar_url": _empty_to_none(comment.author.avatar_url),
        },
        "text": _empty_to_none(comment.text),
        "created_at": _coerce_utc_timestamp(comment.created_at),
        "edited_at": _coerce_utc_timestamp(comment.edited_at),
        "metrics": {
            "likes": _coerce_metric(comment.reactions.total or None),
            "replies": _coerce_metric(comment.replies_count),
        },
        "source": source,
        "raw": raw,
    }


def reactions_data(
    reactions: Iterable[dict[str, Any]],
    *,
    cursor: Optional[str] = None,
    next_cursor: Optional[str] = None,
    has_more: bool = False,
) -> dict[str, Any]:
    """Build `read.reactions` data."""
    return {
        "reactions": [reaction_to_contract(item, source="unofficial") for item in reactions],
        "paging": {
            "cursor": cursor,
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
    }


def reaction_to_contract(reaction: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Convert an unofficial raw reaction payload to a stable contract shape."""
    raw = _redact_secrets(reaction)
    actor = reaction.get("actor")
    if not isinstance(actor, dict):
        actor = {}
    return {
        "type": _empty_to_none(_reaction_type(raw)),
        "actor": {
            "id": _empty_to_none(
                _first_present_value(raw, "actor.entityUrn", "actorUrn", "*actor")
            ),
            "name": _empty_to_none(_first_present_value(actor, "name.text", "name")),
            "handle": _empty_to_none(_first_present_value(actor, "publicIdentifier", "public_id")),
            "url": _empty_to_none(_first_present_value(actor, "navigationUrl", "url")),
        },
        "source": source,
        "raw": raw,
    }


def post_to_contract(post: Post, *, source: str) -> dict[str, Any]:
    """Convert the internal Post model to the SNS JSON Contract post shape."""
    raw = _redact_secrets(to_dict(post))
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
        "comments": [comment_to_contract(item, source=source) for item in post.comments],
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
            "api": "linkedin.posts",
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
            "api": "linkedin.posts+images",
        },
    }


def post_create_dry_run_data(
    *,
    text: str,
    visibility: str,
    media_count: int,
    api: str = "linkedin.posts",
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build generic dry-run data for official post creation commands."""
    planned = {
        "visibility": visibility,
        "text_length": len(text),
        "media_count": media_count,
        "api": api,
    }
    if extra:
        planned.update(extra)
    return {
        "dry_run": True,
        "post": None,
        "planned": planned,
    }


def post_reply_dry_run_data(
    *,
    text: str,
    reply_to: str,
    parent_comment: Optional[str] = None,
) -> dict[str, Any]:
    """Build dry-run data for `post.reply` through LinkedIn Comments API."""
    planned: dict[str, Any] = {
        "reply_to": reply_to,
        "text_length": len(text),
        "media_count": 0,
        "api": "linkedin.comments",
    }
    if parent_comment:
        planned["parent_comment"] = parent_comment
    return {
        "dry_run": True,
        "post": None,
        "planned": planned,
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


def post_reply_success_data(result: CommentResult) -> dict[str, Any]:
    """Build success data for `post.reply` through LinkedIn Comments API."""
    raw = _redact_secrets(result.raw)
    return {
        "dry_run": False,
        "post": {
            "id": result.comment_id,
            "reply_to": result.entity_urn,
            "source": "official",
            "raw": raw,
        },
        "comment": {
            "id": result.comment_id,
            "entity": result.entity_urn,
            "source": "official",
            "raw": raw,
        },
        "planned": None,
    }


def post_update_dry_run_data(*, post_id: str, text: str) -> dict[str, Any]:
    """Build dry-run data for `post.update`."""
    return {
        "dry_run": True,
        "post": None,
        "planned": {
            "id": post_id,
            "text_length": len(text),
            "api": "linkedin.posts.update",
        },
    }


def post_update_success_data(result: UpdateResult) -> dict[str, Any]:
    """Build success data for `post.update`."""
    return {
        "dry_run": False,
        "post": {
            "id": result.post_id,
            "updated": True,
            "updated_at": result.updated_at,
            "source": "official",
            "raw": result.raw,
        },
        "planned": None,
    }


def post_get_success_data(result: GetPostResult) -> dict[str, Any]:
    """Build success data for `post.get`."""
    return {
        "post": {
            "id": result.post_id,
            "source": "official",
            "raw": result.raw,
        }
    }


def post_list_success_data(result: ListPostsResult) -> dict[str, Any]:
    """Build success data for `post.list`."""
    return {
        "posts": [
            {
                "id": item.get("id"),
                "source": "official",
                "raw": item,
            }
            for item in result.elements
        ],
        "paging": result.paging,
        "raw": result.raw,
    }


def comment_success_data(result: CommentResult) -> dict[str, Any]:
    """Build success data for official comment get/create."""
    return {
        "comment": {
            "id": result.comment_id,
            "entity": result.entity_urn,
            "source": "official",
            "raw": _redact_secrets(result.raw),
        }
    }


def comment_list_success_data(result: CommentListResult) -> dict[str, Any]:
    """Build success data for official comment list."""
    return {
        "comments": [
            {
                "id": item.get("id"),
                "source": "official",
                "raw": _redact_secrets(item),
            }
            for item in result.elements
        ],
        "paging": result.paging,
        "raw": _redact_secrets(result.raw),
    }


def comment_dry_run_data(*, planned: dict[str, Any]) -> dict[str, Any]:
    """Build dry-run data for official comment mutation commands."""
    return {
        "dry_run": True,
        "comment": None,
        "planned": planned,
    }


def reaction_success_data(result: ReactionResult) -> dict[str, Any]:
    """Build success data for official reaction get/create."""
    return {
        "reaction": {
            "actor": result.actor_urn,
            "entity": result.entity_urn,
            "source": "official",
            "raw": _redact_secrets(result.raw),
        }
    }


def reaction_list_success_data(result: CommentListResult) -> dict[str, Any]:
    """Build success data for official reaction list."""
    return {
        "reactions": [
            {
                "id": item.get("id"),
                "source": "official",
                "raw": _redact_secrets(item),
            }
            for item in result.elements
        ],
        "paging": result.paging,
        "raw": _redact_secrets(result.raw),
    }


def reaction_dry_run_data(*, planned: dict[str, Any]) -> dict[str, Any]:
    """Build dry-run data for official reaction mutation commands."""
    return {
        "dry_run": True,
        "reaction": None,
        "planned": planned,
    }


def social_metadata_success_data(result: SocialMetadataResult) -> dict[str, Any]:
    """Build success data for official social metadata."""
    return {
        "social_metadata": {
            "entity": result.entity_urn,
            "source": "official",
            "raw": _redact_secrets(result.raw),
        }
    }


def social_metadata_dry_run_data(*, planned: dict[str, Any]) -> dict[str, Any]:
    """Build dry-run data for official social metadata mutation commands."""
    return {
        "dry_run": True,
        "social_metadata": None,
        "planned": planned,
    }


def insights_data(result: SocialMetadataResult, *, scope: str) -> dict[str, Any]:
    """Build `insights.media` data from LinkedIn social metadata."""
    raw = _redact_secrets(result.raw)
    metrics = {
        "likes": _coerce_metric(
            _first_present_value(
                result.raw,
                "likesSummary.totalLikes",
                "likeSummary.totalLikes",
                "reactionSummaries.LIKE",
                "reactionCount",
                "likes",
            )
        ),
        "comments": _coerce_metric(
            _first_present_value(
                result.raw,
                "commentsSummary.aggregatedTotalComments",
                "commentsSummary.totalFirstLevelComments",
                "aggregatedTotalComments",
                "totalFirstLevelComments",
                "commentCount",
                "comments",
            )
        ),
        "reposts": _coerce_metric(
            _first_present_value(
                result.raw,
                "shareSummary.totalShares",
                "resharesSummary.totalReshares",
                "reshareCount",
                "repostCount",
                "reposts",
            )
        ),
        "views": _coerce_metric(
            _first_present_value(
                result.raw,
                "viewSummary.totalViews",
                "impressionCount",
                "views",
            )
        ),
    }
    return {
        "scope": scope,
        "metrics": metrics,
        "raw": {
            "entity": result.entity_urn,
            "source": "official",
            "social_metadata": raw,
        },
    }


def organization_insights_data(result: OrganizationShareStatisticsResult) -> dict[str, Any]:
    """Build `insights.organization` data from LinkedIn organization share statistics."""
    raw = _redact_secrets(result.raw)
    metrics = {
        "likes": _sum_metric(result.elements, "totalShareStatistics.likeCount"),
        "comments": _sum_metric(result.elements, "totalShareStatistics.commentCount"),
        "reposts": _sum_metric(result.elements, "totalShareStatistics.shareCount"),
        "views": _sum_metric(result.elements, "totalShareStatistics.impressionCount"),
        "unique_views": _sum_metric(result.elements, "totalShareStatistics.uniqueImpressionsCount"),
        "clicks": _sum_metric(result.elements, "totalShareStatistics.clickCount"),
    }
    return {
        "scope": "organization",
        "organization": {
            "id": result.organization_urn,
        },
        "metrics": metrics,
        "entries": [
            {
                "organization": _empty_to_none(item.get("organizationalEntity")),
                "share": _empty_to_none(item.get("share")),
                "ugc_post": _empty_to_none(item.get("ugcPost")),
                "time_range": item.get("timeRange") if isinstance(item.get("timeRange"), dict) else None,
                "metrics": {
                    "likes": _coerce_metric(_first_present_value(item, "totalShareStatistics.likeCount")),
                    "comments": _coerce_metric(_first_present_value(item, "totalShareStatistics.commentCount")),
                    "reposts": _coerce_metric(_first_present_value(item, "totalShareStatistics.shareCount")),
                    "views": _coerce_metric(_first_present_value(item, "totalShareStatistics.impressionCount")),
                    "unique_views": _coerce_metric(
                        _first_present_value(item, "totalShareStatistics.uniqueImpressionsCount")
                    ),
                    "clicks": _coerce_metric(_first_present_value(item, "totalShareStatistics.clickCount")),
                },
                "raw": _redact_secrets(item),
            }
            for item in result.elements
        ],
        "paging": result.paging,
        "raw": {
            "source": "official",
            "organization": result.organization_urn,
            "organization_share_statistics": raw,
        },
    }


def social_action_success_data(result: SocialActionResult) -> dict[str, Any]:
    """Build success data for official social actions without a resource body."""
    return {
        "action": result.action,
        "target": {
            "id": result.entity_urn,
        },
        "result": {
            "completed_at": result.completed_at,
            "raw": _redact_secrets(result.raw),
        },
    }


def social_action_dry_run_data(*, action: str, target_id: str, planned: dict[str, Any]) -> dict[str, Any]:
    """Build dry-run data for official social actions without a resource body."""
    return {
        "dry_run": True,
        "action": action,
        "target": {
            "id": target_id,
        },
        "result": None,
        "planned": planned,
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


def auth_status_data(
    *,
    state: str,
    cookie_count: int,
    cookie_names: list[str],
    cookie_domains: list[str],
    required_missing: list[str],
    session_path: Optional[str] = None,
) -> dict[str, Any]:
    """Build `auth.status` data. Reports cookie presence only — never cookie values."""
    return {
        "auth": {
            "platform": PLATFORM,
            "state": state,
            "session_path": session_path,
            "cookie_count": cookie_count,
            "cookie_names": cookie_names,
            "cookie_domains": cookie_domains,
            "required_missing": required_missing,
        }
    }


def permission_check_data(
    *,
    oauth: dict[str, Any],
    probes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build `auth.permission_check` data without exposing OAuth secrets."""
    return {
        "oauth": oauth,
        "probes": probes,
        "summary": {
            "ok": all(item.get("ok") for item in probes),
            "passed": sum(1 for item in probes if item.get("ok")),
            "failed": sum(1 for item in probes if not item.get("ok")),
        },
    }


_SECRET_RAW_KEYS = frozenset(
    {
        "liat",
        "jsessionid",
        "accesstoken",
        "refreshtoken",
        "authorization",
        "cookie",
        "setcookie",
        "csrftoken",
        "password",
        "clientsecret",
    }
)


def _redact_secrets(value: Any) -> Any:
    """Recursively drop credential-like keys from a raw payload (contract rule 6).

    The contract forbids cookies, OAuth/CSRF tokens, Authorization headers, and
    session ids in `raw`. Read models never populate these today, so this is a
    defense-in-depth guard against future regressions.
    """
    if isinstance(value, dict):
        return {
            key: _redact_secrets(item)
            for key, item in value.items()
            if not (
                isinstance(key, str)
                and key.lower().replace("-", "").replace("_", "") in _SECRET_RAW_KEYS
            )
        }
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


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


def _sum_metric(items: Iterable[dict[str, Any]], path: str) -> Optional[int]:
    total = 0
    seen = False
    for item in items:
        value = _coerce_metric(_first_present_value(item, path))
        if value is None:
            continue
        total += value
        seen = True
    return total if seen else None


def _first_present_value(payload: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        value: Any = payload
        for part in path.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if value not in (None, "", [], {}):
            return value
    return None


def _reaction_type(payload: dict[str, Any]) -> str:
    value = _first_present_value(payload, "reactionType", "reaction_type", "type")
    return str(value or "").lower()


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
