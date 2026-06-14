"""Public Python API for official LinkedIn write operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

import httpx

from .oauth import DEFAULT_LINKEDIN_VERSION
from .oauth import OAuthConfig
from .oauth import load_oauth_config
from .publisher import LinkedInPublisher
from .publisher import DeleteResult
from .publisher import PublishResult

DRY_RUN_ACCESS_TOKEN = "DRY_RUN"
DRY_RUN_AUTHOR_URN = "urn:li:person:DRY_RUN"
DRY_RUN_IMAGE_URN = "urn:li:image:DRY_RUN"


@dataclass(frozen=True)
class PostPlan:
    """Validated plan for an official LinkedIn post without publishing it."""

    command: str
    visibility: str
    text_length: int
    media_count: int
    api: str
    author_urn: str
    linkedin_version: str
    payload: dict[str, Any]
    media_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable plan."""
        return {
            "command": self.command,
            "visibility": self.visibility,
            "text_length": self.text_length,
            "media_count": self.media_count,
            "api": self.api,
            "author_urn": self.author_urn,
            "linkedin_version": self.linkedin_version,
            "payload": self.payload,
            "media_paths": list(self.media_paths),
        }


@dataclass(frozen=True)
class DeletePlan:
    """Validated plan for an official LinkedIn post deletion."""

    command: str
    post_id: str
    api: str
    author_urn: str
    linkedin_version: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable plan."""
        return {
            "command": self.command,
            "post_id": self.post_id,
            "api": self.api,
            "author_urn": self.author_urn,
            "linkedin_version": self.linkedin_version,
        }


class LinkedInWriteAPI:
    """High-level official LinkedIn write API for agents and Python callers."""

    def __init__(
        self,
        oauth: OAuthConfig,
        *,
        client: Optional[httpx.Client] = None,
        publisher: Optional[LinkedInPublisher] = None,
        timeout: float = 20.0,
    ) -> None:
        self.oauth = oauth
        self.publisher = publisher or LinkedInPublisher(oauth, client=client, timeout=timeout)

    @classmethod
    def from_config(
        cls,
        path: Optional[Union[str, Path]] = None,
        *,
        author_override: Optional[str] = None,
        version_override: Optional[str] = None,
        client: Optional[httpx.Client] = None,
        timeout: float = 20.0,
    ) -> "LinkedInWriteAPI":
        """Load OAuth config and return a write API instance."""
        oauth_path = Path(path).expanduser() if path is not None else None
        oauth = load_oauth_config(
            oauth_path,
            author_override=author_override,
            version_override=version_override,
        )
        return cls(oauth, client=client, timeout=timeout)

    @classmethod
    def for_dry_run(
        cls,
        *,
        author_urn: Optional[str] = None,
        linkedin_version: Optional[str] = None,
    ) -> "LinkedInWriteAPI":
        """Return a write API instance that can validate payloads without credentials."""
        oauth = OAuthConfig(
            access_token=DRY_RUN_ACCESS_TOKEN,
            author_urn=author_urn or DRY_RUN_AUTHOR_URN,
            linkedin_version=linkedin_version or DEFAULT_LINKEDIN_VERSION,
            source="dry-run",
        )
        return cls(oauth)

    def plan_text_post(self, *, text: str, visibility: str = "public") -> PostPlan:
        """Validate and build the official UGC Posts API payload for a text post."""
        payload = self.publisher.build_text_payload(text=text, visibility=visibility)
        return PostPlan(
            command="post.text",
            visibility=visibility,
            text_length=len(_payload_commentary(payload)),
            media_count=0,
            api="linkedin.ugcPosts",
            author_urn=self.oauth.author_urn,
            linkedin_version=self.oauth.linkedin_version,
            payload=payload,
        )

    def create_text_post(self, *, text: str, visibility: str = "public") -> PublishResult:
        """Publish a text post through LinkedIn's official UGC Posts API."""
        return self.publisher.post_text(text=text, visibility=visibility)

    def plan_image_post(
        self,
        *,
        text: str,
        media_path: Union[str, Path],
        visibility: str = "public",
    ) -> PostPlan:
        """Validate and build the official UGC Posts API payload shape for one image post."""
        path = Path(media_path).expanduser()
        payload = self.publisher.build_media_payload(
            text=text,
            visibility=visibility,
            image_urn=DRY_RUN_IMAGE_URN,
        )
        return PostPlan(
            command="post.media",
            visibility=visibility,
            text_length=len(_payload_commentary(payload)),
            media_count=1,
            api="linkedin.ugcPosts+assets",
            author_urn=self.oauth.author_urn,
            linkedin_version=self.oauth.linkedin_version,
            payload=payload,
            media_paths=(str(path),),
        )

    def create_image_post(
        self,
        *,
        text: str,
        media_path: Union[str, Path],
        visibility: str = "public",
    ) -> PublishResult:
        """Upload one local image and publish it through official LinkedIn APIs."""
        return self.publisher.post_image(
            text=text,
            visibility=visibility,
            media_path=Path(media_path),
        )


    def plan_delete_post(self, *, post_id: str) -> DeletePlan:
        """Validate and build the official Posts API delete target without deleting it."""
        normalized = self.publisher.normalize_delete_post_id(post_id)
        return DeletePlan(
            command="post.delete",
            post_id=normalized,
            api="linkedin.posts.delete",
            author_urn=self.oauth.author_urn,
            linkedin_version=self.oauth.linkedin_version,
        )

    def delete_post(self, *, post_id: str) -> DeleteResult:
        """Delete a post through LinkedIn's official Posts API."""
        return self.publisher.delete_post(post_id=post_id)


__all__ = ["DeletePlan", "LinkedInWriteAPI", "PostPlan"]


def _payload_commentary(payload: dict[str, Any]) -> str:
    share_content = payload.get("specificContent", {}).get("com.linkedin.ugc.ShareContent", {})
    commentary = share_content.get("shareCommentary", {})
    text = commentary.get("text")
    return text if isinstance(text, str) else ""
