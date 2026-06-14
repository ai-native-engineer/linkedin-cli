"""Public Python API for official LinkedIn write operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

import httpx

from .oauth import DEFAULT_LINKEDIN_VERSION
from .oauth import OAuthConfig
from .oauth import load_oauth_config
from .publisher import DeleteResult
from .publisher import CommentListResult
from .publisher import CommentResult
from .publisher import GetPostResult
from .publisher import LinkedInPublishError
from .publisher import LinkedInPublisher
from .publisher import ListPostsResult
from .publisher import PublishResult
from .publisher import ReactionResult
from .publisher import SocialActionResult
from .publisher import SocialMetadataResult
from .publisher import UpdateResult

DRY_RUN_ACCESS_TOKEN = "DRY_RUN"
DRY_RUN_AUTHOR_URN = "urn:li:person:DRY_RUN"
DRY_RUN_IMAGE_URN = "urn:li:image:DRY_RUN"
DRY_RUN_VIDEO_URN = "urn:li:video:DRY_RUN"
DRY_RUN_DOCUMENT_URN = "urn:li:document:DRY_RUN"


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
        self._owns_publisher = publisher is None
        self.publisher = publisher or LinkedInPublisher(oauth, client=client, timeout=timeout)

    def close(self) -> None:
        """Close the underlying publisher (and its HTTP client) if owned."""
        if self._owns_publisher:
            self.publisher.close()

    def __enter__(self) -> "LinkedInWriteAPI":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

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
        """Validate and build the official Posts API payload for a text post."""
        payload = self.publisher.build_text_payload(text=text, visibility=visibility)
        return PostPlan(
            command="post.text",
            visibility=visibility,
            text_length=len(_payload_commentary(payload)),
            media_count=0,
            api="linkedin.posts",
            author_urn=self.oauth.author_urn,
            linkedin_version=self.oauth.linkedin_version,
            payload=payload,
        )

    def create_text_post(self, *, text: str, visibility: str = "public") -> PublishResult:
        """Publish a text post through LinkedIn's official Posts API."""
        return self.publisher.post_text(text=text, visibility=visibility)

    def plan_image_post(
        self,
        *,
        text: str,
        media_path: Union[str, Path],
        visibility: str = "public",
    ) -> PostPlan:
        """Validate and build the official Posts API payload shape for one image post."""
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
            api="linkedin.posts+images",
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

    def plan_multi_image_post(
        self,
        *,
        text: str,
        media_paths: list[Union[str, Path]],
        alt_texts: tuple[str, ...] = (),
        visibility: str = "public",
    ) -> PostPlan:
        """Validate and build the official Posts API payload shape for multiple images."""
        paths = tuple(str(Path(path).expanduser()) for path in media_paths)
        if alt_texts and len(alt_texts) != len(paths):
            raise LinkedInPublishError(
                "Pass either no --alt-text values or exactly one --alt-text per image.",
                code="media_invalid",
                retryable=False,
                details={"alt_text_count": len(alt_texts), "media_count": len(paths)},
            )
        images: list[dict[str, str]] = []
        for index in range(len(paths)):
            item = {"id": f"urn:li:image:DRY_RUN_{index + 1}"}
            if alt_texts:
                item["altText"] = alt_texts[index]
            images.append(item)
        payload = self.publisher.build_multi_image_payload(
            text=text,
            visibility=visibility,
            images=images,
        )
        return PostPlan(
            command="post.multi_image",
            visibility=visibility,
            text_length=len(_payload_commentary(payload)),
            media_count=len(paths),
            api="linkedin.posts+images",
            author_urn=self.oauth.author_urn,
            linkedin_version=self.oauth.linkedin_version,
            payload=payload,
            media_paths=paths,
        )

    def create_multi_image_post(
        self,
        *,
        text: str,
        media_paths: list[Union[str, Path]],
        alt_texts: tuple[str, ...] = (),
        visibility: str = "public",
    ) -> PublishResult:
        """Upload multiple local images and publish them through official LinkedIn APIs."""
        return self.publisher.post_multi_image(
            text=text,
            visibility=visibility,
            media_paths=[Path(path) for path in media_paths],
            alt_texts=alt_texts,
        )

    def plan_video_post(
        self,
        *,
        text: str,
        media_path: Union[str, Path],
        visibility: str = "public",
        title: Optional[str] = None,
    ) -> PostPlan:
        """Validate and build the official Posts API payload shape for one video post."""
        path = Path(media_path).expanduser()
        payload = self.publisher.build_video_payload(
            text=text,
            visibility=visibility,
            video_urn=DRY_RUN_VIDEO_URN,
            title=title,
        )
        return PostPlan(
            command="post.video",
            visibility=visibility,
            text_length=len(_payload_commentary(payload)),
            media_count=1,
            api="linkedin.posts+videos",
            author_urn=self.oauth.author_urn,
            linkedin_version=self.oauth.linkedin_version,
            payload=payload,
            media_paths=(str(path),),
        )

    def create_video_post(
        self,
        *,
        text: str,
        media_path: Union[str, Path],
        visibility: str = "public",
        title: Optional[str] = None,
    ) -> PublishResult:
        """Upload one local video and publish it through official LinkedIn APIs."""
        return self.publisher.post_video(
            text=text,
            visibility=visibility,
            media_path=Path(media_path),
            title=title,
        )

    def plan_document_post(
        self,
        *,
        text: str,
        media_path: Union[str, Path],
        visibility: str = "public",
        title: Optional[str] = None,
    ) -> PostPlan:
        """Validate and build the official Posts API payload shape for one document post."""
        path = Path(media_path).expanduser()
        document_title = title.strip() if title and title.strip() else path.name
        payload = self.publisher.build_document_payload(
            text=text,
            visibility=visibility,
            document_urn=DRY_RUN_DOCUMENT_URN,
            title=document_title,
        )
        return PostPlan(
            command="post.document",
            visibility=visibility,
            text_length=len(_payload_commentary(payload)),
            media_count=1,
            api="linkedin.posts+documents",
            author_urn=self.oauth.author_urn,
            linkedin_version=self.oauth.linkedin_version,
            payload=payload,
            media_paths=(str(path),),
        )

    def create_document_post(
        self,
        *,
        text: str,
        media_path: Union[str, Path],
        visibility: str = "public",
        title: Optional[str] = None,
    ) -> PublishResult:
        """Upload one local document and publish it through official LinkedIn APIs."""
        return self.publisher.post_document(
            text=text,
            visibility=visibility,
            media_path=Path(media_path),
            title=title,
        )

    def plan_poll_post(
        self,
        *,
        text: str,
        question: str,
        options: tuple[str, ...],
        duration: str,
        visibility: str = "public",
    ) -> PostPlan:
        """Validate and build the official Posts API payload for a poll post."""
        payload = self.publisher.build_poll_payload(
            text=text,
            visibility=visibility,
            question=question,
            options=options,
            duration=duration,
        )
        return PostPlan(
            command="post.poll",
            visibility=visibility,
            text_length=len(_payload_commentary(payload)),
            media_count=0,
            api="linkedin.posts+polls",
            author_urn=self.oauth.author_urn,
            linkedin_version=self.oauth.linkedin_version,
            payload=payload,
        )

    def create_poll_post(
        self,
        *,
        text: str,
        question: str,
        options: tuple[str, ...],
        duration: str,
        visibility: str = "public",
    ) -> PublishResult:
        """Publish a poll through official LinkedIn APIs."""
        return self.publisher.post_poll(
            text=text,
            visibility=visibility,
            question=question,
            options=options,
            duration=duration,
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

    def plan_article_post(
        self,
        *,
        text: str,
        url: str,
        visibility: str = "public",
        title: Optional[str] = None,
        description: Optional[str] = None,
        thumbnail: Optional[str] = None,
    ) -> PostPlan:
        """Validate and build the official Posts API payload for an article post."""
        payload = self.publisher.build_article_payload(
            text=text,
            visibility=visibility,
            url=url,
            title=title,
            description=description,
            thumbnail=thumbnail,
        )
        return PostPlan(
            command="post.article",
            visibility=visibility,
            text_length=len(_payload_commentary(payload)),
            media_count=0,
            api="linkedin.posts",
            author_urn=self.oauth.author_urn,
            linkedin_version=self.oauth.linkedin_version,
            payload=payload,
        )

    def create_article_post(
        self,
        *,
        text: str,
        url: str,
        visibility: str = "public",
        title: Optional[str] = None,
        description: Optional[str] = None,
        thumbnail: Optional[str] = None,
    ) -> PublishResult:
        """Publish an article post through LinkedIn's official Posts API."""
        return self.publisher.post_article(
            text=text,
            visibility=visibility,
            url=url,
            title=title,
            description=description,
            thumbnail=thumbnail,
        )

    def plan_reshare_post(
        self,
        *,
        text: str,
        parent: str,
        visibility: str = "public",
    ) -> PostPlan:
        """Validate and build the official Posts API payload for a reshare."""
        payload = self.publisher.build_reshare_payload(text=text, visibility=visibility, parent=parent)
        return PostPlan(
            command="post.reshare",
            visibility=visibility,
            text_length=len(_payload_commentary(payload)),
            media_count=0,
            api="linkedin.posts",
            author_urn=self.oauth.author_urn,
            linkedin_version=self.oauth.linkedin_version,
            payload=payload,
        )

    def create_reshare_post(
        self,
        *,
        text: str,
        parent: str,
        visibility: str = "public",
    ) -> PublishResult:
        """Publish a reshare through LinkedIn's official Posts API."""
        return self.publisher.post_reshare(text=text, visibility=visibility, parent=parent)

    def plan_update_post(self, *, post_id: str, text: str) -> dict[str, Any]:
        """Validate and build the official Posts API partial update payload."""
        normalized = self.publisher.normalize_post_id(post_id)
        payload = self.publisher.build_update_payload(text=text)
        return {
            "command": "post.update",
            "post_id": normalized,
            "api": "linkedin.posts.update",
            "author_urn": self.oauth.author_urn,
            "linkedin_version": self.oauth.linkedin_version,
            "payload": payload,
        }

    def update_post(self, *, post_id: str, text: str) -> UpdateResult:
        """Update a post through LinkedIn's official Posts API."""
        return self.publisher.update_post(post_id=post_id, text=text)

    def get_post(self, *, post_id: str, view_context: str = "AUTHOR") -> GetPostResult:
        """Retrieve one post through LinkedIn's official Posts API."""
        return self.publisher.get_post(post_id=post_id, view_context=view_context)

    def list_posts_by_author(
        self,
        *,
        author_urn: Optional[str] = None,
        count: int = 10,
        start: int = 0,
        sort_by: str = "LAST_MODIFIED",
        view_context: str = "AUTHOR",
    ) -> ListPostsResult:
        """Retrieve posts authored by a person or organization."""
        return self.publisher.list_posts_by_author(
            author_urn=author_urn,
            count=count,
            start=start,
            sort_by=sort_by,
            view_context=view_context,
        )

    def list_comments(self, *, entity: str, count: int = 10, start: int = 0) -> CommentListResult:
        """Retrieve comments through LinkedIn's official Comments API."""
        return self.publisher.list_comments(entity=entity, count=count, start=start)

    def get_comment(self, *, entity: str, comment_id: str) -> CommentResult:
        """Retrieve one comment through LinkedIn's official Comments API."""
        return self.publisher.get_comment(entity=entity, comment_id=comment_id)

    def create_comment(
        self,
        *,
        entity: str,
        text: str,
        actor_urn: Optional[str] = None,
        parent_comment: Optional[str] = None,
    ) -> CommentResult:
        """Create a comment through LinkedIn's official Comments API."""
        return self.publisher.create_comment(
            entity=entity,
            text=text,
            actor_urn=actor_urn,
            parent_comment=parent_comment,
        )

    def update_comment(
        self,
        *,
        entity: str,
        comment_id: str,
        text: str,
        actor_urn: Optional[str] = None,
    ) -> SocialActionResult:
        """Update a comment through LinkedIn's official Comments API."""
        return self.publisher.update_comment(
            entity=entity,
            comment_id=comment_id,
            text=text,
            actor_urn=actor_urn,
        )

    def delete_comment(
        self,
        *,
        entity: str,
        comment_id: str,
        actor_urn: Optional[str] = None,
    ) -> SocialActionResult:
        """Delete a comment through LinkedIn's official Comments API."""
        return self.publisher.delete_comment(
            entity=entity,
            comment_id=comment_id,
            actor_urn=actor_urn,
        )

    def list_reactions(self, *, entity: str, count: int = 10, start: int = 0) -> CommentListResult:
        """Retrieve reactions through LinkedIn's official Reactions API."""
        return self.publisher.list_reactions(entity=entity, count=count, start=start)

    def get_reaction(self, *, entity: str, actor_urn: Optional[str] = None) -> ReactionResult:
        """Retrieve the current actor's reaction through LinkedIn's official Reactions API."""
        return self.publisher.get_reaction(entity=entity, actor_urn=actor_urn)

    def create_reaction(
        self,
        *,
        entity: str,
        reaction_type: str = "like",
        actor_urn: Optional[str] = None,
    ) -> ReactionResult:
        """Create a reaction through LinkedIn's official Reactions API."""
        return self.publisher.create_reaction(
            entity=entity,
            reaction_type=reaction_type,
            actor_urn=actor_urn,
        )

    def delete_reaction(
        self,
        *,
        entity: str,
        actor_urn: Optional[str] = None,
    ) -> SocialActionResult:
        """Delete the current actor's reaction through LinkedIn's official Reactions API."""
        return self.publisher.delete_reaction(entity=entity, actor_urn=actor_urn)

    def get_social_metadata(self, *, entity: str) -> SocialMetadataResult:
        """Retrieve social metadata through LinkedIn's official Social Metadata API."""
        return self.publisher.get_social_metadata(entity=entity)

    def update_comments_state(
        self,
        *,
        entity: str,
        state: str,
        actor_urn: Optional[str] = None,
    ) -> SocialMetadataResult:
        """Open or close comments through LinkedIn's official Social Metadata API."""
        return self.publisher.update_comments_state(
            entity=entity,
            state=state,
            actor_urn=actor_urn,
        )


__all__ = ["DeletePlan", "LinkedInWriteAPI", "PostPlan"]


def _payload_commentary(payload: dict[str, Any]) -> str:
    text = payload.get("commentary")
    return text if isinstance(text, str) else ""
