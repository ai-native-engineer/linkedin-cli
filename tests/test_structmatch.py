from __future__ import annotations

from linkedin_cli.structmatch import extract_activity_id
from linkedin_cli.structmatch import find_first_key
from linkedin_cli.structmatch import find_in_included
from linkedin_cli.structmatch import safe_int
from linkedin_cli.structmatch import type_matches


def test_safe_int_handles_non_numeric_and_separators() -> None:
    assert safe_int("800px") == 800
    assert safe_int("1,024") == 1024
    assert safe_int(None) == 0
    assert safe_int("") == 0
    assert safe_int("n/a", default=-1) == -1
    assert safe_int(42) == 42
    assert safe_int(3.9) == 3


def test_extract_activity_id_variants() -> None:
    assert extract_activity_id("urn:li:activity:123") == "123"
    assert extract_activity_id("urn:li:fsd_update:(urn:li:activity:123,FEED)") == "123"
    assert extract_activity_id("urn%3Ali%3Aactivity%3A123") == "123"
    assert extract_activity_id("https://www.linkedin.com/feed/update/urn:li:activity:55/") == "55"
    assert extract_activity_id("urn:li:share:9") is None
    assert extract_activity_id(None) is None


def test_type_matches_anchors_on_suffix() -> None:
    profile = {"$type": "com.linkedin.voyager.dash.identity.profileV2.Profile"}
    assert type_matches(profile, ".Profile")
    assert not type_matches(profile, ".profile.Profile")
    assert not type_matches({"$type": 123}, ".Profile")
    assert not type_matches("not-a-dict", ".Profile")
    assert not type_matches({"$type": "x.Profile"})  # no suffixes given


def test_find_in_included_returns_first_match_and_swallows_errors() -> None:
    included = [
        "junk",
        {"$type": "A"},
        {"$type": "com.example.Profile", "id": 1},
        {"$type": "com.example.Profile", "id": 2},
    ]

    match = find_in_included(included, lambda item: type_matches(item, ".Profile"))
    assert match["id"] == 1

    def boom(item: dict) -> bool:
        raise RuntimeError("predicate should not abort the scan")

    assert find_in_included(included, boom) is None


def test_find_first_key_searches_priority_then_depth() -> None:
    tree = {"socialActivityCounts": {"numLikes": 7, "numComments": 0}}
    assert find_first_key(tree, "numLikes") == 7
    # priority order at the same level wins
    assert find_first_key({"b": 2, "a": 1}, "a", "b") == 1
    # a real 0 is a valid value, not skipped
    assert find_first_key({"numComments": 0, "nested": {"numComments": 3}}, "numComments") == 0
    # genuine empties (None) are skipped while descending
    assert find_first_key({"numComments": None, "nested": {"numComments": 3}}, "numComments") == 3
    assert find_first_key({"x": 1}, "missing") is None
    assert find_first_key({"deep": {"x": 1}}, "x", max_depth=0) is None
