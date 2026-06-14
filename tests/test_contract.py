from __future__ import annotations

import json

from linkedin_cli.contract import SCHEMA_VERSION
from linkedin_cli.contract import envelope
from linkedin_cli.contract import error_envelope
from linkedin_cli.contract import feed_data
from linkedin_cli.contract import post_text_dry_run_data
from linkedin_cli.contract import to_contract_json


def test_envelope_serializes_success_payload(sample_post) -> None:
    payload = envelope(
        command="read.feed",
        source="unofficial",
        request={"limit": 5, "cursor": None, "dry_run": False},
        data=feed_data([sample_post], cursor=None),
    )

    parsed = json.loads(to_contract_json(payload))

    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["ok"] is True
    assert parsed["platform"] == "linkedin"
    assert parsed["command"] == "read.feed"
    assert parsed["source"] == "unofficial"
    assert parsed["data"]["posts"][0]["id"] == "urn:li:activity:999"
    assert parsed["data"]["posts"][0]["created_at"] is None
    assert parsed["data"]["posts"][0]["metrics"]["likes"] == 42
    assert parsed["data"]["paging"]["has_more"] is False
    assert parsed["error"] is None


def test_error_envelope_uses_standard_error_shape() -> None:
    payload = error_envelope(
        command="read.feed",
        source="unofficial",
        request={"limit": 5, "cursor": None, "dry_run": False},
        code="auth_missing",
        message="No LinkedIn cookies found.",
        retryable=False,
        details={"auth_kind": "cookie_session"},
    )

    parsed = json.loads(to_contract_json(payload))

    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["ok"] is False
    assert parsed["data"] is None
    assert parsed["error"] == {
        "code": "auth_missing",
        "message": "No LinkedIn cookies found.",
        "retryable": False,
        "details": {"auth_kind": "cookie_session"},
    }


def test_metrics_distinguish_unknown_from_confirmed_zero() -> None:
    from linkedin_cli.contract import post_to_contract, profile_data
    from linkedin_cli.models import Actor, EngagementMetrics, Post, Profile, ReactionSummary

    # No counts at all -> every metric is null (unknown), never a confirmed 0.
    unknown = post_to_contract(
        Post(urn="urn:li:activity:1", author=Actor(name="Ada"), text="x"),
        source="unofficial",
    )["metrics"]
    assert unknown == {"likes": None, "comments": None, "reposts": None, "views": None}

    # Unknown aggregate reaction count but a populated summary -> likes falls back to the total.
    fallback = post_to_contract(
        Post(
            urn="urn:li:activity:2",
            author=Actor(name="Ada"),
            text="x",
            reactions=ReactionSummary(like=30, celebrate=10, insightful=2),
        ),
        source="unofficial",
    )["metrics"]
    assert fallback["likes"] == 42

    # Confirmed zeros stay 0; unknown impressions still serialize as null views.
    confirmed = post_to_contract(
        Post(
            urn="urn:li:activity:3",
            author=Actor(name="Ada"),
            text="x",
            metrics=EngagementMetrics(reactions=0, comments=0, reposts=0),
        ),
        source="unofficial",
    )["metrics"]
    assert confirmed["likes"] == 0
    assert confirmed["comments"] == 0
    assert confirmed["reposts"] == 0
    assert confirmed["views"] is None

    # Profile with unknown follower/connection counts -> null, not 0.
    prof = profile_data(Profile(public_id="ada", full_name="Ada"))["profile"]["metrics"]
    assert prof == {"followers": None, "connections": None}


def test_coerce_utc_timestamp_rules() -> None:
    from linkedin_cli.contract import _coerce_utc_timestamp

    # Naive (tz-less) ISO is unrecoverable -> null, never a wrong-tz guess.
    assert _coerce_utc_timestamp("2026-06-12T00:00:00") is None
    # Non-numeric relative time -> null.
    assert _coerce_utc_timestamp("1h") is None
    assert _coerce_utc_timestamp("") is None
    assert _coerce_utc_timestamp(None) is None
    # Epoch seconds and milliseconds resolve to the same instant.
    assert _coerce_utc_timestamp(1749686400) == _coerce_utc_timestamp(1749686400000)
    assert _coerce_utc_timestamp(1749686400).endswith("Z")
    # tz-aware ISO round-trips to the canonical Z form.
    assert _coerce_utc_timestamp("2026-06-12T00:00:00Z") == "2026-06-12T00:00:00Z"
    assert _coerce_utc_timestamp("2026-06-12T09:00:00+09:00") == "2026-06-12T00:00:00Z"


def test_post_text_dry_run_data_has_no_side_effect_result() -> None:
    data = post_text_dry_run_data(text="hello", visibility="public")

    assert data["dry_run"] is True
    assert data["post"] is None
    assert data["planned"] == {
        "visibility": "public",
        "text_length": 5,
        "media_count": 0,
        "api": "linkedin.ugcPosts",
    }
