"""OAuth token loading for official LinkedIn APIs."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Optional

DEFAULT_LINKEDIN_VERSION = "202605"
DEFAULT_OAUTH_PATH = Path("~/.config/linkedin/oauth.json")
ENV_ACCESS_TOKEN = "LINKEDIN_ACCESS_TOKEN"
ENV_AUTHOR_URN = "LINKEDIN_AUTHOR_URN"
ENV_LINKEDIN_VERSION = "LINKEDIN_VERSION"
ENV_OAUTH_PATH = "LINKEDIN_OAUTH_FILE"


class OAuthConfigError(RuntimeError):
    """Raised when official LinkedIn OAuth config cannot be loaded."""


@dataclass(frozen=True)
class OAuthConfig:
    """Official LinkedIn API auth config."""

    access_token: str
    author_urn: str
    linkedin_version: str = DEFAULT_LINKEDIN_VERSION
    source: str = "unknown"


def default_oauth_path() -> Path:
    """Return the default OAuth token file path."""
    return Path(os.getenv(ENV_OAUTH_PATH, str(DEFAULT_OAUTH_PATH))).expanduser()


def load_oauth_config(
    path: Optional[Path] = None,
    *,
    author_override: Optional[str] = None,
    version_override: Optional[str] = None,
) -> OAuthConfig:
    """Load official LinkedIn OAuth config from env first, then file."""
    env_token = os.getenv(ENV_ACCESS_TOKEN, "").strip()
    env_author = (author_override or os.getenv(ENV_AUTHOR_URN, "")).strip()
    env_version = (version_override or os.getenv(ENV_LINKEDIN_VERSION, "")).strip()
    if env_token:
        return _validate_oauth_config(
            {
                "access_token": env_token,
                "author_urn": env_author,
                "linkedin_version": env_version or DEFAULT_LINKEDIN_VERSION,
            },
            source="env",
        )

    token_path = (path or default_oauth_path()).expanduser()
    if not token_path.exists():
        raise OAuthConfigError(
            f"LinkedIn OAuth token file not found: {token_path}. "
            f"Create it or set {ENV_ACCESS_TOKEN} and {ENV_AUTHOR_URN}."
        )

    try:
        raw = json.loads(token_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OAuthConfigError(f"LinkedIn OAuth token file is not valid JSON: {token_path}") from exc
    if not isinstance(raw, dict):
        raise OAuthConfigError(f"LinkedIn OAuth token file must contain a JSON object: {token_path}")

    if author_override:
        raw["author_urn"] = author_override
    if version_override:
        raw["linkedin_version"] = version_override

    return _validate_oauth_config(raw, source=str(token_path))


def _validate_oauth_config(raw: dict[str, Any], *, source: str) -> OAuthConfig:
    access_token = _first_string(raw, "access_token", "accessToken", "token")
    author_urn = _first_string(raw, "author_urn", "authorUrn", "author", "owner")
    linkedin_version = _first_string(raw, "linkedin_version", "linkedinVersion", "version")
    if not access_token:
        raise OAuthConfigError("LinkedIn OAuth access token is missing.")
    if not author_urn:
        raise OAuthConfigError("LinkedIn author URN is missing.")
    if not author_urn.startswith(("urn:li:person:", "urn:li:organization:")):
        raise OAuthConfigError(
            "LinkedIn author URN must start with urn:li:person: or urn:li:organization:."
        )
    if linkedin_version and (len(linkedin_version) != 6 or not linkedin_version.isdigit()):
        raise OAuthConfigError("LinkedIn-Version must use YYYYMM format.")
    return OAuthConfig(
        access_token=access_token,
        author_urn=author_urn,
        linkedin_version=linkedin_version or DEFAULT_LINKEDIN_VERSION,
        source=source,
    )


def _first_string(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
