"""Structure-tolerant helpers for parsing LinkedIn's unofficial web responses.

LinkedIn ships no stable contract for its Voyager JSON or rendered DOM, so these
helpers favour *anchor-relative* and *predicate-driven* matching over absolute key
paths, exact ``$type`` strings, and naive ``split``/index parsing. A small change in
LinkedIn's response shape then degrades gracefully (an empty field) instead of
raising and taking down the whole read.

Pure stdlib, side-effect free, no project imports — so ``transport``, ``client``,
and ``browser`` can all build on it and tests can exercise it in isolation.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Optional
from urllib.parse import unquote

_ACTIVITY_ID_RE = re.compile(r"urn:li:activity:(\d+)")
_NON_DIGITS_RE = re.compile(r"\D")

_EMPTY = (None, "", [], {})


def safe_int(value: Any, default: int = 0) -> int:
    """Coerce ``value`` to an int, tolerating units/separators (``'800px'`` -> 800,
    ``'1,024'`` -> 1024). Returns ``default`` instead of raising on junk input."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    digits = _NON_DIGITS_RE.sub("", str(value or ""))
    return int(digits) if digits else default


def extract_activity_id(value: Any) -> Optional[str]:
    """Return the numeric activity id embedded anywhere in ``value`` (handles bare,
    URL-encoded, and compound ``urn:li:fsd_update:(urn:li:activity:123,...)`` forms),
    or ``None`` if there is none. Never raises."""
    if value in (None, ""):
        return None
    match = _ACTIVITY_ID_RE.search(unquote(str(value)))
    return match.group(1) if match else None


def type_matches(item: Any, *suffixes: str) -> bool:
    """True when ``item`` is a dict whose ``$type`` ends with one of ``suffixes``.
    Anchors on the stable tail of the type name so a versioned dash-namespace bump
    (``...profile`` -> ``...profileV2``) still matches."""
    if not suffixes or not isinstance(item, dict):
        return False
    type_value = item.get("$type")
    return isinstance(type_value, str) and type_value.endswith(suffixes)


def find_in_included(included: Iterable[Any], predicate: Callable[[dict], bool]) -> Optional[dict]:
    """Return the first dict in ``included`` satisfying ``predicate`` (the canonical
    predicate-scan over a Voyager ``included`` list), or ``None``. Swallows predicate
    errors so one odd entry cannot abort the scan."""
    for item in included or []:
        if not isinstance(item, dict):
            continue
        try:
            if predicate(item):
                return item
        except Exception:
            continue
    return None


def find_first_key(tree: Any, *leaf_names: str, max_depth: int = 6) -> Any:
    """Recursively return the first non-empty value whose key is in ``leaf_names``,
    searching ``leaf_names`` in priority order at each level before descending. A
    depth-capped fallback for values that LinkedIn relocates under a renamed parent,
    without committing to a fixed parent path."""
    if not leaf_names or max_depth < 0:
        return None
    if isinstance(tree, dict):
        for name in leaf_names:
            if name in tree and tree[name] not in _EMPTY:
                return tree[name]
        for value in tree.values():
            found = find_first_key(value, *leaf_names, max_depth=max_depth - 1)
            if found not in _EMPTY:
                return found
    elif isinstance(tree, list):
        for item in tree:
            found = find_first_key(item, *leaf_names, max_depth=max_depth - 1)
            if found not in _EMPTY:
                return found
    return None
