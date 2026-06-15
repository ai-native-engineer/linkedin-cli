"""Official LinkedIn Share on LinkedIn publisher."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import mimetypes
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import quote, unquote, urlencode, urlparse

import httpx

from .oauth import OAuthConfig

POSTS_URL = "https://api.linkedin.com/rest/posts"
REST_POSTS_URL = POSTS_URL
IMAGES_INITIALIZE_URL = "https://api.linkedin.com/rest/images?action=initializeUpload"
VIDEOS_INITIALIZE_URL = "https://api.linkedin.com/rest/videos?action=initializeUpload"
VIDEOS_FINALIZE_URL = "https://api.linkedin.com/rest/videos?action=finalizeUpload"
DOCUMENTS_INITIALIZE_URL = "https://api.linkedin.com/rest/documents?action=initializeUpload"
SOCIAL_ACTIONS_URL = "https://api.linkedin.com/rest/socialActions"
REACTIONS_URL = "https://api.linkedin.com/rest/reactions"
SOCIAL_METADATA_URL = "https://api.linkedin.com/rest/socialMetadata"
ORGANIZATIONAL_ENTITY_SHARE_STATISTICS_URL = (
    "https://api.linkedin.com/rest/organizationalEntityShareStatistics"
)
RESTLI_PROTOCOL_VERSION = "2.0.0"
SUPPORTED_IMAGE_CONTENT_TYPES = {"image/gif", "image/jpeg", "image/png"}
SUPPORTED_VIDEO_CONTENT_TYPES = {"video/mp4"}
SUPPORTED_DOCUMENT_CONTENT_TYPES = {
    "application/msword",
    "application/pdf",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
DOCUMENT_CONTENT_TYPES_BY_SUFFIX = {
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
MAX_DOCUMENT_SIZE_BYTES = 100 * 1024 * 1024
MIN_MULTI_IMAGE_COUNT = 2
MAX_MULTI_IMAGE_COUNT = 20
MIN_POLL_OPTION_COUNT = 2
MAX_POLL_OPTION_COUNT = 4
MAX_POLL_QUESTION_LENGTH = 140
MAX_POLL_OPTION_LENGTH = 30
VISIBILITY_MAP = {
    "public": "PUBLIC",
    "connections": "CONNECTIONS",
}
POLL_DURATION_MAP = {
    "one-day": "ONE_DAY",
    "one_day": "ONE_DAY",
    "1d": "ONE_DAY",
    "three-days": "THREE_DAYS",
    "three_days": "THREE_DAYS",
    "3d": "THREE_DAYS",
    "seven-days": "SEVEN_DAYS",
    "seven_days": "SEVEN_DAYS",
    "one-week": "SEVEN_DAYS",
    "one_week": "SEVEN_DAYS",
    "7d": "SEVEN_DAYS",
    "fourteen-days": "FOURTEEN_DAYS",
    "fourteen_days": "FOURTEEN_DAYS",
    "two-weeks": "FOURTEEN_DAYS",
    "two_weeks": "FOURTEEN_DAYS",
    "14d": "FOURTEEN_DAYS",
}
REACTION_TYPE_MAP = {
    "like": "LIKE",
    "celebrate": "PRAISE",
    "praise": "PRAISE",
    "support": "APPRECIATION",
    "appreciation": "APPRECIATION",
    "love": "EMPATHY",
    "empathy": "EMPATHY",
    "insightful": "INTEREST",
    "interest": "INTEREST",
    "funny": "ENTERTAINMENT",
    "entertainment": "ENTERTAINMENT",
    "curious": "MAYBE",
    "maybe": "MAYBE",
}
COMMENT_STATE_MAP = {
    "open": "OPEN",
    "closed": "CLOSED",
}


class LinkedInPublishError(RuntimeError):
    """Raised when official LinkedIn publishing fails."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "post_rejected",
        retryable: bool = False,
        status_code: Optional[int] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class PublishResult:
    """Successful official post result."""

    post_id: str
    url: str
    created_at: str
    visibility: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class DeleteResult:
    """Successful official post deletion result."""

    post_id: str
    deleted_at: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class UpdateResult:
    """Successful official post update result."""

    post_id: str
    updated_at: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class GetPostResult:
    """Official post retrieval result."""

    post_id: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class ListPostsResult:
    """Official posts-by-author retrieval result."""

    author_urn: str
    elements: list[dict[str, Any]]
    paging: dict[str, Any]
    raw: dict[str, Any]


@dataclass(frozen=True)
class CommentResult:
    """Official comment mutation or retrieval result."""

    entity_urn: str
    comment_id: Optional[str]
    raw: dict[str, Any]


@dataclass(frozen=True)
class CommentListResult:
    """Official comments retrieval result."""

    entity_urn: str
    elements: list[dict[str, Any]]
    paging: dict[str, Any]
    raw: dict[str, Any]


@dataclass(frozen=True)
class ReactionResult:
    """Official reaction mutation or retrieval result."""

    actor_urn: str
    entity_urn: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class SocialMetadataResult:
    """Official social metadata retrieval or update result."""

    entity_urn: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class OrganizationShareStatisticsResult:
    """Official organization share statistics result."""

    organization_urn: str
    elements: list[dict[str, Any]]
    paging: dict[str, Any]
    raw: dict[str, Any]


@dataclass(frozen=True)
class SocialActionResult:
    """Successful official social action with no body requirement."""

    action: str
    entity_urn: str
    completed_at: str
    raw: dict[str, Any]


class LinkedInPublisher:
    """Small wrapper around LinkedIn's official Posts API."""

    def __init__(
        self,
        oauth: OAuthConfig,
        *,
        client: Optional[httpx.Client] = None,
        timeout: float = 20.0,
    ) -> None:
        self.oauth = oauth
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        """Close the underlying HTTP client if this publisher created it."""
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "LinkedInPublisher":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def build_text_payload(self, *, text: str, visibility: str) -> dict[str, Any]:
        """Build the official Posts API payload for text publishing."""
        return self._build_rest_post_payload(text=text, visibility=visibility)

    def build_media_payload(self, *, text: str, visibility: str, image_urn: str) -> dict[str, Any]:
        """Build the official Posts API payload for a single image post."""
        return self._build_rest_post_payload(
            text=text,
            visibility=visibility,
            content={"media": {"id": image_urn}},
        )

    def build_multi_image_payload(
        self,
        *,
        text: str,
        visibility: str,
        images: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Build the official Posts API payload for a multi-image post."""
        return self._build_rest_post_payload(
            text=text,
            visibility=visibility,
            content={"multiImage": {"images": _validate_multi_image_entries(images)}},
        )

    def build_video_payload(
        self,
        *,
        text: str,
        visibility: str,
        video_urn: str,
        title: Optional[str] = None,
    ) -> dict[str, Any]:
        """Build the official Posts API payload for a video post."""
        video = video_urn.strip()
        if not video:
            raise LinkedInPublishError(
                "Video URN cannot be empty.",
                code="media_invalid",
                retryable=False,
            )
        media: dict[str, str] = {"id": video}
        if title and title.strip():
            media["title"] = title.strip()
        return self._build_rest_post_payload(
            text=text,
            visibility=visibility,
            content={"media": media},
        )

    def build_document_payload(
        self,
        *,
        text: str,
        visibility: str,
        document_urn: str,
        title: str,
    ) -> dict[str, Any]:
        """Build the official Posts API payload for a document post."""
        document = document_urn.strip()
        if not document:
            raise LinkedInPublishError(
                "Document URN cannot be empty.",
                code="media_invalid",
                retryable=False,
            )
        normalized_title = _normalize_document_title(title)
        return self._build_rest_post_payload(
            text=text,
            visibility=visibility,
            content={"media": {"title": normalized_title, "id": document}},
        )

    def build_poll_payload(
        self,
        *,
        text: str,
        visibility: str,
        question: str,
        options: Sequence[str],
        duration: str,
    ) -> dict[str, Any]:
        """Build the official Posts API payload for a poll post."""
        normalized_options = _normalize_poll_options(options)
        poll = {
            "question": _normalize_poll_question(question),
            "options": [{"text": option} for option in normalized_options],
            "settings": {"duration": normalize_poll_duration(duration)},
        }
        return self._build_rest_post_payload(
            text=text,
            visibility=visibility,
            content={"poll": poll},
        )

    def build_article_payload(
        self,
        *,
        text: str,
        visibility: str,
        url: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        thumbnail: Optional[str] = None,
    ) -> dict[str, Any]:
        """Build the official Posts API payload for an article/link post."""
        source = url.strip()
        if not source:
            raise LinkedInPublishError(
                "Article URL cannot be empty.",
                code="invalid_request",
                retryable=False,
            )
        article: dict[str, Any] = {"source": source}
        if title and title.strip():
            article["title"] = title.strip()
        if description and description.strip():
            article["description"] = description.strip()
        if thumbnail and thumbnail.strip():
            article["thumbnail"] = thumbnail.strip()
        return self._build_rest_post_payload(
            text=text,
            visibility=visibility,
            content={"article": article},
        )

    def build_reshare_payload(
        self,
        *,
        text: str,
        visibility: str,
        parent: str,
    ) -> dict[str, Any]:
        """Build the official Posts API payload for resharing a post."""
        parent_urn = normalize_post_id(parent)
        return self._build_rest_post_payload(
            text=text,
            visibility=visibility,
            reshare_context={"parent": parent_urn},
        )

    def build_update_payload(self, *, text: str) -> dict[str, Any]:
        """Build the official Posts API partial update payload."""
        body = text.strip()
        if not body:
            raise LinkedInPublishError(
                "Post text cannot be empty.",
                code="invalid_request",
                retryable=False,
            )
        return {"patch": {"$set": {"commentary": body}}}

    def _build_rest_post_payload(
        self,
        *,
        text: str,
        visibility: str,
        content: Optional[dict[str, Any]] = None,
        reshare_context: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        body = text.strip()
        if not body:
            raise LinkedInPublishError(
                "Post text cannot be empty.",
                code="invalid_request",
                retryable=False,
            )
        api_visibility = VISIBILITY_MAP.get(visibility)
        if api_visibility is None:
            raise LinkedInPublishError(
                f"Unsupported visibility: {visibility}",
                code="invalid_request",
                retryable=False,
                details={"supported_visibility": sorted(VISIBILITY_MAP)},
            )

        payload: dict[str, Any] = {
            "author": self.oauth.author_urn,
            "commentary": body,
            "visibility": api_visibility,
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        if content:
            payload["content"] = content
        if reshare_context:
            payload["reshareContext"] = reshare_context
        return payload

    def post_text(self, *, text: str, visibility: str) -> PublishResult:
        """Publish a text post through LinkedIn's official Posts API."""
        payload = self.build_text_payload(text=text, visibility=visibility)
        return self._create_post(payload=payload, visibility=visibility)

    def post_image(self, *, text: str, visibility: str, media_path: Path) -> PublishResult:
        """Upload one local image and publish it in a post."""
        path = _existing_media_file(media_path)
        content_type = _image_content_type(path)
        image_urn = self._upload_image(path, content_type=content_type)
        payload = self.build_media_payload(text=text, visibility=visibility, image_urn=image_urn)
        return self._create_post(payload=payload, visibility=visibility, media={"image": image_urn})

    def post_multi_image(
        self,
        *,
        text: str,
        visibility: str,
        media_paths: list[Path],
        alt_texts: Sequence[str] = (),
    ) -> PublishResult:
        """Upload multiple local images and publish them in a post."""
        _validate_multi_image_count(len(media_paths))
        paths = [_existing_media_file(path) for path in media_paths]
        alt_values = _normalize_alt_texts(alt_texts, media_count=len(paths))
        images: list[dict[str, str]] = []
        for index, path in enumerate(paths):
            content_type = _image_content_type(path)
            image_urn = self._upload_image(path, content_type=content_type)
            item = {"id": image_urn}
            if alt_values[index]:
                item["altText"] = alt_values[index]
            images.append(item)
        payload = self.build_multi_image_payload(text=text, visibility=visibility, images=images)
        return self._create_post(
            payload=payload,
            visibility=visibility,
            media={"multiImage": images},
        )

    def post_video(
        self,
        *,
        text: str,
        visibility: str,
        media_path: Path,
        title: Optional[str] = None,
    ) -> PublishResult:
        """Upload one local MP4 video and publish it in a post."""
        path = _existing_media_file(media_path)
        _video_content_type(path)
        video_urn = self._upload_video(path)
        payload = self.build_video_payload(
            text=text,
            visibility=visibility,
            video_urn=video_urn,
            title=title,
        )
        return self._create_post(payload=payload, visibility=visibility, media={"video": video_urn})

    def post_document(
        self,
        *,
        text: str,
        visibility: str,
        media_path: Path,
        title: Optional[str] = None,
    ) -> PublishResult:
        """Upload one local document and publish it in a post."""
        path = _existing_media_file(media_path)
        content_type = _document_content_type(path)
        document_urn = self._upload_document(path, content_type=content_type)
        document_title = title.strip() if title and title.strip() else path.name
        payload = self.build_document_payload(
            text=text,
            visibility=visibility,
            document_urn=document_urn,
            title=document_title,
        )
        return self._create_post(
            payload=payload,
            visibility=visibility,
            media={"document": document_urn, "title": document_title},
        )

    def post_poll(
        self,
        *,
        text: str,
        visibility: str,
        question: str,
        options: Sequence[str],
        duration: str,
    ) -> PublishResult:
        """Publish a poll through LinkedIn's official Posts API."""
        payload = self.build_poll_payload(
            text=text,
            visibility=visibility,
            question=question,
            options=options,
            duration=duration,
        )
        return self._create_post(
            payload=payload,
            visibility=visibility,
            media={"poll": payload["content"]["poll"]},
        )

    def post_article(
        self,
        *,
        text: str,
        visibility: str,
        url: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        thumbnail: Optional[str] = None,
    ) -> PublishResult:
        """Publish an article/link post through LinkedIn's official Posts API."""
        payload = self.build_article_payload(
            text=text,
            visibility=visibility,
            url=url,
            title=title,
            description=description,
            thumbnail=thumbnail,
        )
        return self._create_post(
            payload=payload,
            visibility=visibility,
            media={"article": payload["content"]["article"]},
        )

    def post_reshare(self, *, text: str, visibility: str, parent: str) -> PublishResult:
        """Publish a reshare through LinkedIn's official Posts API."""
        payload = self.build_reshare_payload(text=text, visibility=visibility, parent=parent)
        return self._create_post(
            payload=payload,
            visibility=visibility,
            media={"reshare": payload["reshareContext"]},
        )

    def normalize_delete_post_id(self, post_id: str) -> str:
        """Normalize a post URN, feed URL, or numeric share id for official deletion."""
        return normalize_post_id(post_id)

    def normalize_post_id(self, post_id: str) -> str:
        """Normalize a post URN, feed URL, or numeric share id."""
        return normalize_post_id(post_id)

    def delete_post(self, *, post_id: str) -> DeleteResult:
        """Delete a post through LinkedIn's official Posts API."""
        normalized = self.normalize_post_id(post_id)
        encoded = quote(normalized, safe="")
        try:
            response = self.client.delete(
                f"{REST_POSTS_URL}/{encoded}",
                headers=self._rest_headers(method="DELETE"),
            )
        except httpx.TimeoutException as exc:
            raise LinkedInPublishError(
                "LinkedIn Posts API delete request timed out.",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LinkedInPublishError(
                f"LinkedIn Posts API delete request failed: {exc}",
                code="upstream_unavailable",
                retryable=True,
            ) from exc

        if response.status_code != 204:
            raise self._error_from_response(response)

        deleted_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return DeleteResult(
            post_id=normalized,
            deleted_at=deleted_at,
            raw={
                "status_code": response.status_code,
                "request": {
                    "api": "linkedin.posts.delete",
                    "post_id": normalized,
                },
            },
        )

    def update_post(self, *, post_id: str, text: str) -> UpdateResult:
        """Update a post's commentary through LinkedIn's official Posts API."""
        normalized = self.normalize_post_id(post_id)
        payload = self.build_update_payload(text=text)
        try:
            response = self.client.post(
                f"{REST_POSTS_URL}/{quote(normalized, safe='')}",
                headers=self._rest_headers(method="PARTIAL_UPDATE", content_type="application/json"),
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise LinkedInPublishError(
                "LinkedIn Posts API update request timed out.",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LinkedInPublishError(
                f"LinkedIn Posts API update request failed: {exc}",
                code="upstream_unavailable",
                retryable=True,
            ) from exc

        if response.status_code != 204:
            raise self._error_from_response(response)

        updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return UpdateResult(
            post_id=normalized,
            updated_at=updated_at,
            raw={
                "status_code": response.status_code,
                "request": {
                    "api": "linkedin.posts.update",
                    "post_id": normalized,
                    "payload": payload,
                },
            },
        )

    def get_post(self, *, post_id: str, view_context: str = "AUTHOR") -> GetPostResult:
        """Retrieve one post through LinkedIn's official Posts API."""
        normalized = self.normalize_post_id(post_id)
        response = self._get(
            f"{REST_POSTS_URL}/{quote(normalized, safe='')}",
            params={"viewContext": view_context},
        )
        return GetPostResult(post_id=normalized, raw=response)

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
        author = (author_urn or self.oauth.author_urn).strip()
        if not author:
            raise LinkedInPublishError(
                "Author URN cannot be empty.",
                code="invalid_request",
                retryable=False,
            )
        if count < 1 or count > 100:
            raise LinkedInPublishError(
                "Count must be between 1 and 100.",
                code="invalid_request",
                retryable=False,
            )
        if start < 0:
            raise LinkedInPublishError(
                "Start must be greater than or equal to 0.",
                code="invalid_request",
                retryable=False,
            )
        response = self._get(
            REST_POSTS_URL,
            params={
                "author": author,
                "q": "author",
                "count": str(count),
                "start": str(start),
                "sortBy": sort_by,
                "viewContext": view_context,
            },
            restli_method="FINDER",
        )
        elements = response.get("elements")
        if not isinstance(elements, list):
            elements = []
        paging = response.get("paging")
        if not isinstance(paging, dict):
            paging = {}
        return ListPostsResult(author_urn=author, elements=elements, paging=paging, raw=response)

    def list_comments(
        self,
        *,
        entity: str,
        count: int = 10,
        start: int = 0,
    ) -> CommentListResult:
        """Retrieve comments on a post or comment through LinkedIn's official Comments API."""
        entity_urn = normalize_social_entity_id(entity)
        if count < 1 or count > 100:
            raise LinkedInPublishError(
                "Count must be between 1 and 100.",
                code="invalid_request",
                retryable=False,
            )
        if start < 0:
            raise LinkedInPublishError(
                "Start must be greater than or equal to 0.",
                code="invalid_request",
                retryable=False,
            )
        response = self._get(
            f"{SOCIAL_ACTIONS_URL}/{quote(entity_urn, safe='')}/comments",
            params={"count": str(count), "start": str(start)},
        )
        elements = response.get("elements")
        if not isinstance(elements, list):
            elements = []
        paging = response.get("paging")
        if not isinstance(paging, dict):
            paging = {}
        return CommentListResult(entity_urn=entity_urn, elements=elements, paging=paging, raw=response)

    def get_comment(self, *, entity: str, comment_id: str) -> CommentResult:
        """Retrieve one comment through LinkedIn's official Comments API."""
        entity_urn = normalize_social_entity_id(entity)
        comment = _normalize_non_empty(comment_id, label="Comment id")
        response = self._get(
            f"{SOCIAL_ACTIONS_URL}/{quote(entity_urn, safe='')}/comments/{quote(comment, safe='')}",
        )
        return CommentResult(entity_urn=entity_urn, comment_id=comment, raw=response)

    def create_comment(
        self,
        *,
        entity: str,
        text: str,
        actor_urn: Optional[str] = None,
        parent_comment: Optional[str] = None,
    ) -> CommentResult:
        """Create a comment through LinkedIn's official Comments API."""
        entity_urn = normalize_social_entity_id(entity)
        actor = _normalize_actor_urn(actor_urn or self.oauth.author_urn)
        body = _normalize_non_empty(text, label="Comment text")
        payload: dict[str, Any] = {
            "actor": actor,
            "object": entity_urn,
            "message": {"text": body},
        }
        if parent_comment:
            payload["parentComment"] = normalize_social_entity_id(parent_comment)
        response = self._post_json(
            f"{SOCIAL_ACTIONS_URL}/{quote(entity_urn, safe='')}/comments",
            payload=payload,
            expected_statuses={200, 201},
            api_name="LinkedIn Comments API create",
        )
        comment_id = response.get("id") if isinstance(response.get("id"), str) else None
        return CommentResult(entity_urn=entity_urn, comment_id=comment_id, raw=response)

    def update_comment(
        self,
        *,
        entity: str,
        comment_id: str,
        text: str,
        actor_urn: Optional[str] = None,
    ) -> SocialActionResult:
        """Update a comment through LinkedIn's official Comments API."""
        entity_urn = normalize_social_entity_id(entity)
        comment = _normalize_non_empty(comment_id, label="Comment id")
        actor = _normalize_actor_urn(actor_urn or self.oauth.author_urn)
        body = _normalize_non_empty(text, label="Comment text")
        payload = {"patch": {"message": {"$set": {"text": body}}}}
        response = self._post_json(
            f"{SOCIAL_ACTIONS_URL}/{quote(entity_urn, safe='')}/comments/{quote(comment, safe='')}",
            params={"actor": actor},
            payload=payload,
            method="PARTIAL_UPDATE",
            expected_statuses={200, 204},
            api_name="LinkedIn Comments API update",
        )
        return SocialActionResult(
            action="comment.update",
            entity_urn=entity_urn,
            completed_at=utc_now_iso(),
            raw=response,
        )

    def delete_comment(
        self,
        *,
        entity: str,
        comment_id: str,
        actor_urn: Optional[str] = None,
    ) -> SocialActionResult:
        """Delete a comment through LinkedIn's official Comments API."""
        entity_urn = normalize_social_entity_id(entity)
        comment = _normalize_non_empty(comment_id, label="Comment id")
        actor = _normalize_actor_urn(actor_urn or self.oauth.author_urn)
        url = _url_with_params(
            f"{SOCIAL_ACTIONS_URL}/{quote(entity_urn, safe='')}/comments/{quote(comment, safe='')}",
            params={"actor": actor},
        )
        self._delete(url, expected_statuses={204}, api_name="LinkedIn Comments API delete")
        return SocialActionResult(
            action="comment.delete",
            entity_urn=entity_urn,
            completed_at=utc_now_iso(),
            raw={
                "status_code": 204,
                "request": {
                    "api": "linkedin.comments.delete",
                    "actor": actor,
                    "entity": entity_urn,
                    "comment_id": comment,
                },
            },
        )

    def list_reactions(
        self,
        *,
        entity: str,
        count: int = 10,
        start: int = 0,
    ) -> CommentListResult:
        """Retrieve reactions on a post or comment through LinkedIn's official Reactions API."""
        entity_urn = normalize_social_entity_id(entity)
        if count < 1 or count > 100:
            raise LinkedInPublishError(
                "Count must be between 1 and 100.",
                code="invalid_request",
                retryable=False,
            )
        if start < 0:
            raise LinkedInPublishError(
                "Start must be greater than or equal to 0.",
                code="invalid_request",
                retryable=False,
            )
        key = f"(entity:{quote(entity_urn, safe='')})"
        response = self._get(
            f"{REACTIONS_URL}/{key}",
            params={
                "q": "entity",
                "sort": "(value:REVERSE_CHRONOLOGICAL)",
                "count": str(count),
                "start": str(start),
            },
        )
        elements = response.get("elements")
        if not isinstance(elements, list):
            elements = []
        paging = response.get("paging")
        if not isinstance(paging, dict):
            paging = {}
        return CommentListResult(entity_urn=entity_urn, elements=elements, paging=paging, raw=response)

    def get_reaction(self, *, entity: str, actor_urn: Optional[str] = None) -> ReactionResult:
        """Retrieve the current actor's reaction to a post or comment."""
        entity_urn = normalize_social_entity_id(entity)
        actor = _normalize_actor_urn(actor_urn or self.oauth.author_urn)
        response = self._get(f"{REACTIONS_URL}/{_reaction_key(actor=actor, entity=entity_urn)}")
        return ReactionResult(actor_urn=actor, entity_urn=entity_urn, raw=response)

    def create_reaction(
        self,
        *,
        entity: str,
        reaction_type: str = "like",
        actor_urn: Optional[str] = None,
    ) -> ReactionResult:
        """Create a reaction through LinkedIn's official Reactions API."""
        entity_urn = normalize_social_entity_id(entity)
        actor = _normalize_actor_urn(actor_urn or self.oauth.author_urn)
        payload = {
            "root": entity_urn,
            "reactionType": normalize_reaction_type(reaction_type),
        }
        response = self._post_json(
            REACTIONS_URL,
            params={"actor": actor},
            payload=payload,
            expected_statuses={200, 201},
            api_name="LinkedIn Reactions API create",
        )
        return ReactionResult(actor_urn=actor, entity_urn=entity_urn, raw=response)

    def delete_reaction(
        self,
        *,
        entity: str,
        actor_urn: Optional[str] = None,
    ) -> SocialActionResult:
        """Delete the current actor's reaction through LinkedIn's official Reactions API."""
        entity_urn = normalize_social_entity_id(entity)
        actor = _normalize_actor_urn(actor_urn or self.oauth.author_urn)
        url = f"{REACTIONS_URL}/{_reaction_key(actor=actor, entity=entity_urn)}"
        self._delete(url, expected_statuses={204}, api_name="LinkedIn Reactions API delete")
        return SocialActionResult(
            action="reaction.delete",
            entity_urn=entity_urn,
            completed_at=utc_now_iso(),
            raw={
                "status_code": 204,
                "request": {"api": "linkedin.reactions.delete", "actor": actor, "entity": entity_urn},
            },
        )

    def get_social_metadata(self, *, entity: str) -> SocialMetadataResult:
        """Retrieve social metadata through LinkedIn's official Social Metadata API."""
        entity_urn = normalize_social_entity_id(entity)
        response = self._get(f"{SOCIAL_METADATA_URL}/{quote(entity_urn, safe='')}")
        return SocialMetadataResult(entity_urn=entity_urn, raw=response)

    def get_organization_share_statistics(
        self,
        *,
        organization: str,
        shares: Sequence[str] = (),
        ugc_posts: Sequence[str] = (),
        time_granularity: Optional[str] = None,
        time_start: Optional[int] = None,
        time_end: Optional[int] = None,
    ) -> OrganizationShareStatisticsResult:
        """Retrieve share statistics for a LinkedIn organization."""
        organization_urn = normalize_organization_urn(organization)
        params: dict[str, str] = {
            "q": "organizationalEntity",
            "organizationalEntity": organization_urn,
        }
        if shares:
            params["shares"] = _restli_list([normalize_share_urn(value) for value in shares])
        if ugc_posts:
            params["ugcPosts"] = _restli_list([normalize_ugc_post_urn(value) for value in ugc_posts])
        if time_granularity:
            params["timeIntervals.timeGranularityType"] = normalize_time_granularity(time_granularity)
        if time_start is not None:
            params["timeIntervals.timeRange.start"] = str(int(time_start))
        if time_end is not None:
            params["timeIntervals.timeRange.end"] = str(int(time_end))

        response = self._get(ORGANIZATIONAL_ENTITY_SHARE_STATISTICS_URL, params=params)
        elements = response.get("elements", [])
        if not isinstance(elements, list):
            raise LinkedInPublishError(
                "LinkedIn Organization Share Statistics API returned a non-list elements field.",
                code="contract_error",
                retryable=True,
            )
        paging = response.get("paging", {})
        if not isinstance(paging, dict):
            paging = {}
        return OrganizationShareStatisticsResult(
            organization_urn=organization_urn,
            elements=elements,
            paging=paging,
            raw=response,
        )

    def update_comments_state(
        self,
        *,
        entity: str,
        state: str,
        actor_urn: Optional[str] = None,
    ) -> SocialMetadataResult:
        """Open or close comments through LinkedIn's official Social Metadata API."""
        entity_urn = normalize_social_entity_id(entity)
        actor = _normalize_actor_urn(actor_urn or self.oauth.author_urn)
        comments_state = normalize_comments_state(state)
        response = self._post_json(
            f"{SOCIAL_METADATA_URL}/{quote(entity_urn, safe='')}",
            params={"actor": actor},
            payload={"patch": {"$set": {"commentsState": comments_state}}},
            method="PARTIAL_UPDATE",
            expected_statuses={200, 202},
            api_name="LinkedIn Social Metadata API update",
        )
        if not response:
            response = {
                "status_code": 202,
                "request": {
                    "api": "linkedin.social_metadata.update",
                    "actor": actor,
                    "entity": entity_urn,
                    "commentsState": comments_state,
                },
            }
        return SocialMetadataResult(entity_urn=entity_urn, raw=response)

    def _create_post(
        self,
        *,
        payload: dict[str, Any],
        visibility: str,
        media: Optional[dict[str, Any]] = None,
    ) -> PublishResult:
        try:
            response = self.client.post(
                POSTS_URL,
                headers=self._rest_headers(content_type="application/json"),
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise LinkedInPublishError(
                "LinkedIn Posts API request timed out.",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LinkedInPublishError(
                f"LinkedIn Posts API request failed: {exc}",
                code="upstream_unavailable",
                retryable=True,
            ) from exc

        if response.status_code != 201:
            raise self._error_from_response(response)

        post_id = response.headers.get("x-restli-id", "").strip()
        if not post_id:
            raise LinkedInPublishError(
                "LinkedIn Posts API did not return x-restli-id.",
                code="contract_error",
                retryable=False,
                status_code=response.status_code,
                details={"status_code": response.status_code},
            )

        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return PublishResult(
            post_id=post_id,
            url=f"https://www.linkedin.com/feed/update/{post_id}/",
            created_at=created_at,
            visibility=visibility,
            raw={
                "status_code": response.status_code,
                "headers": {"x-restli-id": post_id},
                "request": {
                    "api": "linkedin.posts",
                    "author": self.oauth.author_urn,
                    "visibility": payload["visibility"],
                    "media": media,
                },
            },
        )

    def _upload_image(self, path: Path, *, content_type: str) -> str:
        try:
            init_response = self.client.post(
                IMAGES_INITIALIZE_URL,
                headers=self._rest_headers(content_type="application/json"),
                json={
                    "initializeUploadRequest": {
                        "owner": self.oauth.author_urn,
                    }
                },
            )
        except httpx.TimeoutException as exc:
            raise LinkedInPublishError(
                "LinkedIn Images API initialize upload request timed out.",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LinkedInPublishError(
                f"LinkedIn Images API initialize upload request failed: {exc}",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        if init_response.status_code != 200:
            raise self._error_from_response(init_response, fallback_code="media_upload_failed")
        try:
            value = init_response.json().get("value", {})
        except ValueError as exc:
            raise LinkedInPublishError(
                "LinkedIn Images API returned invalid JSON.",
                code="media_upload_failed",
                retryable=True,
                status_code=init_response.status_code,
            ) from exc
        upload_url = value.get("uploadUrl")
        image_urn = value.get("image")
        if not upload_url or not image_urn:
            raise LinkedInPublishError(
                "LinkedIn Images API did not return uploadUrl and image URN.",
                code="media_upload_failed",
                retryable=True,
                status_code=init_response.status_code,
            )

        try:
            upload_response = self.client.put(
                upload_url,
                content=path.read_bytes(),
                headers={"Content-Type": content_type},
            )
        except httpx.TimeoutException as exc:
            raise LinkedInPublishError(
                "LinkedIn image upload request timed out.",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LinkedInPublishError(
                f"LinkedIn image upload request failed: {exc}",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        if not 200 <= upload_response.status_code <= 299:
            raise self._error_from_response(upload_response, fallback_code="media_upload_failed")
        return str(image_urn)

    def _upload_video(self, path: Path) -> str:
        file_size = path.stat().st_size
        try:
            init_response = self.client.post(
                VIDEOS_INITIALIZE_URL,
                headers=self._rest_headers(content_type="application/json"),
                json={
                    "initializeUploadRequest": {
                        "owner": self.oauth.author_urn,
                        "fileSizeBytes": file_size,
                        "uploadCaptions": False,
                        "uploadThumbnail": False,
                    }
                },
            )
        except httpx.TimeoutException as exc:
            raise LinkedInPublishError(
                "LinkedIn Videos API initialize upload request timed out.",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LinkedInPublishError(
                f"LinkedIn Videos API initialize upload request failed: {exc}",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        if init_response.status_code != 200:
            raise self._error_from_response(init_response, fallback_code="media_upload_failed")

        try:
            value = init_response.json().get("value", {})
        except ValueError as exc:
            raise LinkedInPublishError(
                "LinkedIn Videos API returned invalid JSON.",
                code="media_upload_failed",
                retryable=True,
                status_code=init_response.status_code,
            ) from exc
        video_urn = value.get("video")
        upload_instructions = value.get("uploadInstructions")
        upload_token = value.get("uploadToken", "")
        if not video_urn or not isinstance(upload_instructions, list) or not upload_instructions:
            raise LinkedInPublishError(
                "LinkedIn Videos API did not return video URN and upload instructions.",
                code="media_upload_failed",
                retryable=True,
                status_code=init_response.status_code,
            )

        uploaded_part_ids = self._upload_video_parts(
            path,
            upload_instructions=upload_instructions,
        )
        try:
            finalize_response = self.client.post(
                VIDEOS_FINALIZE_URL,
                headers=self._rest_headers(content_type="application/json"),
                json={
                    "finalizeUploadRequest": {
                        "video": video_urn,
                        "uploadToken": str(upload_token or ""),
                        "uploadedPartIds": uploaded_part_ids,
                    }
                },
            )
        except httpx.TimeoutException as exc:
            raise LinkedInPublishError(
                "LinkedIn Videos API finalize upload request timed out.",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LinkedInPublishError(
                f"LinkedIn Videos API finalize upload request failed: {exc}",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        if finalize_response.status_code != 200:
            raise self._error_from_response(finalize_response, fallback_code="media_upload_failed")
        return str(video_urn)

    def _upload_video_parts(
        self,
        path: Path,
        *,
        upload_instructions: list[Any],
    ) -> list[str]:
        uploaded_part_ids: list[str] = []
        with path.open("rb") as file:
            for instruction in upload_instructions:
                if not isinstance(instruction, dict):
                    raise LinkedInPublishError(
                        "LinkedIn Videos API returned malformed upload instructions.",
                        code="media_upload_failed",
                        retryable=True,
                    )
                upload_url = instruction.get("uploadUrl")
                if not upload_url:
                    raise LinkedInPublishError(
                        "LinkedIn Videos API upload instruction is missing uploadUrl.",
                        code="media_upload_failed",
                        retryable=True,
                    )
                first_byte = _coerce_video_byte(instruction.get("firstByte"), default=0)
                last_byte = _coerce_video_byte(
                    instruction.get("lastByte"),
                    default=path.stat().st_size - 1,
                )
                if first_byte < 0 or last_byte < first_byte:
                    raise LinkedInPublishError(
                        "LinkedIn Videos API returned an invalid upload byte range.",
                        code="media_upload_failed",
                        retryable=True,
                    )
                file.seek(first_byte)
                content = file.read(last_byte - first_byte + 1)
                try:
                    upload_response = self.client.put(
                        upload_url,
                        content=content,
                        headers={"Content-Type": "application/octet-stream"},
                    )
                except httpx.TimeoutException as exc:
                    raise LinkedInPublishError(
                        "LinkedIn video upload request timed out.",
                        code="upstream_unavailable",
                        retryable=True,
                    ) from exc
                except httpx.HTTPError as exc:
                    raise LinkedInPublishError(
                        f"LinkedIn video upload request failed: {exc}",
                        code="upstream_unavailable",
                        retryable=True,
                    ) from exc
                if not 200 <= upload_response.status_code <= 299:
                    raise self._error_from_response(
                        upload_response,
                        fallback_code="media_upload_failed",
                    )
                etag = upload_response.headers.get("etag") or upload_response.headers.get("ETag")
                if not etag:
                    raise LinkedInPublishError(
                        "LinkedIn video upload response did not return an ETag.",
                        code="media_upload_failed",
                        retryable=True,
                        status_code=upload_response.status_code,
                    )
                uploaded_part_ids.append(etag.strip('"'))
        return uploaded_part_ids

    def _upload_document(self, path: Path, *, content_type: str) -> str:
        file_size = path.stat().st_size
        if file_size > MAX_DOCUMENT_SIZE_BYTES:
            raise LinkedInPublishError(
                "LinkedIn document uploads cannot exceed 100MB.",
                code="media_invalid",
                retryable=False,
                details={"max_size_bytes": MAX_DOCUMENT_SIZE_BYTES, "size_bytes": file_size},
            )
        try:
            init_response = self.client.post(
                DOCUMENTS_INITIALIZE_URL,
                headers=self._rest_headers(content_type="application/json"),
                json={
                    "initializeUploadRequest": {
                        "owner": self.oauth.author_urn,
                    }
                },
            )
        except httpx.TimeoutException as exc:
            raise LinkedInPublishError(
                "LinkedIn Documents API initialize upload request timed out.",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LinkedInPublishError(
                f"LinkedIn Documents API initialize upload request failed: {exc}",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        if init_response.status_code != 200:
            raise self._error_from_response(init_response, fallback_code="media_upload_failed")
        try:
            value = init_response.json().get("value", {})
        except ValueError as exc:
            raise LinkedInPublishError(
                "LinkedIn Documents API returned invalid JSON.",
                code="media_upload_failed",
                retryable=True,
                status_code=init_response.status_code,
            ) from exc
        upload_url = value.get("uploadUrl")
        document_urn = value.get("document")
        if not upload_url or not document_urn:
            raise LinkedInPublishError(
                "LinkedIn Documents API did not return uploadUrl and document URN.",
                code="media_upload_failed",
                retryable=True,
                status_code=init_response.status_code,
            )

        try:
            upload_response = self.client.put(
                upload_url,
                content=path.read_bytes(),
                headers={
                    "Authorization": f"Bearer {self.oauth.access_token}",
                    "Content-Type": content_type,
                },
            )
        except httpx.TimeoutException as exc:
            raise LinkedInPublishError(
                "LinkedIn document upload request timed out.",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LinkedInPublishError(
                f"LinkedIn document upload request failed: {exc}",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        if not 200 <= upload_response.status_code <= 299:
            raise self._error_from_response(upload_response, fallback_code="media_upload_failed")
        return str(document_urn)

    def _get(
        self,
        url: str,
        *,
        params: Optional[dict[str, str]] = None,
        restli_method: Optional[str] = None,
    ) -> dict[str, Any]:
        query_url = url
        if params:
            query_url = f"{url}?{urlencode(params, quote_via=quote)}"
        try:
            response = self.client.get(
                query_url,
                headers=self._rest_headers(method=restli_method),
            )
        except httpx.TimeoutException as exc:
            raise LinkedInPublishError(
                "LinkedIn Posts API get request timed out.",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LinkedInPublishError(
                f"LinkedIn Posts API get request failed: {exc}",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        if response.status_code != 200:
            raise self._error_from_response(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise LinkedInPublishError(
                "LinkedIn Posts API returned invalid JSON.",
                code="contract_error",
                retryable=True,
                status_code=response.status_code,
            ) from exc
        if not isinstance(payload, dict):
            raise LinkedInPublishError(
                "LinkedIn Posts API returned a non-object response.",
                code="contract_error",
                retryable=True,
                status_code=response.status_code,
            )
        return payload

    def _post_json(
        self,
        url: str,
        *,
        payload: dict[str, Any],
        expected_statuses: set[int],
        api_name: str,
        params: Optional[dict[str, str]] = None,
        method: Optional[str] = None,
    ) -> dict[str, Any]:
        request_url = _url_with_params(url, params=params)
        try:
            response = self.client.post(
                request_url,
                headers=self._rest_headers(method=method, content_type="application/json"),
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise LinkedInPublishError(
                f"{api_name} request timed out.",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LinkedInPublishError(
                f"{api_name} request failed: {exc}",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        if response.status_code not in expected_statuses:
            raise self._error_from_response(response)
        restli_id = response.headers.get("x-restli-id") or response.headers.get("x-resourceidentity-urn")
        if response.status_code == 204 or not response.content:
            result = {
                "status_code": response.status_code,
                "request": {"url": request_url, "payload": payload},
            }
            if restli_id:
                result["headers"] = {"x-restli-id": restli_id}
            return result
        try:
            parsed = response.json()
        except ValueError as exc:
            raise LinkedInPublishError(
                f"{api_name} returned invalid JSON.",
                code="contract_error",
                retryable=True,
                status_code=response.status_code,
            ) from exc
        if not isinstance(parsed, dict):
            raise LinkedInPublishError(
                f"{api_name} returned a non-object response.",
                code="contract_error",
                retryable=True,
                status_code=response.status_code,
            )
        parsed.setdefault("status_code", response.status_code)
        if restli_id:
            parsed.setdefault("headers", {})["x-restli-id"] = restli_id
        return parsed

    def _delete(
        self,
        url: str,
        *,
        expected_statuses: set[int],
        api_name: str,
    ) -> None:
        try:
            response = self.client.delete(url, headers=self._rest_headers(method="DELETE"))
        except httpx.TimeoutException as exc:
            raise LinkedInPublishError(
                f"{api_name} request timed out.",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LinkedInPublishError(
                f"{api_name} request failed: {exc}",
                code="upstream_unavailable",
                retryable=True,
            ) from exc
        if response.status_code not in expected_statuses:
            raise self._error_from_response(response)

    def _rest_headers(
        self,
        *,
        method: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.oauth.access_token}",
            "LinkedIn-Version": self.oauth.linkedin_version,
            "X-Restli-Protocol-Version": RESTLI_PROTOCOL_VERSION,
        }
        if content_type:
            headers["Content-Type"] = content_type
        if method:
            headers["X-RestLi-Method"] = method
        return headers

    def _error_from_response(
        self,
        response: httpx.Response,
        *,
        fallback_code: Optional[str] = None,
    ) -> LinkedInPublishError:
        code = _error_code_for_status(response.status_code, fallback_code=fallback_code)
        retryable = (
            response.status_code in {408, 425, 429, 500, 502, 503, 504}
            or code == "media_upload_failed"
        )
        message = _response_error_message(response)
        details: dict[str, Any] = {"status_code": response.status_code}
        retry_after = response.headers.get("retry-after")
        if retry_after:
            retry_after_seconds = _coerce_retry_after(retry_after)
            if retry_after_seconds is not None:
                details["retry_after_seconds"] = retry_after_seconds
        return LinkedInPublishError(
            message,
            code=code,
            retryable=retryable,
            status_code=response.status_code,
            details=details,
        )


def _error_code_for_status(status_code: int, *, fallback_code: Optional[str] = None) -> str:
    if status_code == 401:
        return "auth_expired"
    if status_code == 403:
        return "permission_denied"
    if status_code == 404:
        return "not_found"
    if status_code == 429:
        return "rate_limited"
    if 500 <= status_code <= 599:
        return "upstream_unavailable"
    if status_code == 400:
        return "invalid_request"
    return fallback_code or "post_rejected"


def _response_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        for key in ("message", "error_description", "serviceErrorCode"):
            value = payload.get(key)
            if value:
                return f"LinkedIn API rejected the request: {value}"
    text = response.text.strip()
    if text:
        return f"LinkedIn API rejected the request: {text[:300]}"
    return f"LinkedIn API rejected the request with HTTP {response.status_code}."


def _coerce_retry_after(value: str) -> Optional[int]:
    try:
        return int(value)
    except ValueError:
        return None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _url_with_params(url: str, *, params: Optional[dict[str, str]] = None) -> str:
    if not params:
        return url
    return f"{url}?{urlencode(params, quote_via=quote)}"


def _existing_media_file(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.exists() or not expanded.is_file():
        raise LinkedInPublishError(
            f"Media file not found: {expanded}",
            code="media_invalid",
            retryable=False,
        )
    return expanded


def _image_content_type(path: Path) -> str:
    content_type = mimetypes.guess_type(path.name)[0]
    if content_type not in SUPPORTED_IMAGE_CONTENT_TYPES:
        raise LinkedInPublishError(
            f"Unsupported image type for LinkedIn upload: {path.name}",
            code="media_invalid",
            retryable=False,
            details={"supported_content_types": sorted(SUPPORTED_IMAGE_CONTENT_TYPES)},
        )
    return content_type


def _video_content_type(path: Path) -> str:
    content_type = mimetypes.guess_type(path.name)[0]
    if content_type not in SUPPORTED_VIDEO_CONTENT_TYPES:
        raise LinkedInPublishError(
            f"Unsupported video type for LinkedIn upload: {path.name}",
            code="media_invalid",
            retryable=False,
            details={"supported_content_types": sorted(SUPPORTED_VIDEO_CONTENT_TYPES)},
        )
    return content_type


def _document_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    content_type = mimetypes.guess_type(path.name)[0] or DOCUMENT_CONTENT_TYPES_BY_SUFFIX.get(suffix)
    if content_type not in SUPPORTED_DOCUMENT_CONTENT_TYPES:
        raise LinkedInPublishError(
            f"Unsupported document type for LinkedIn upload: {path.name}",
            code="media_invalid",
            retryable=False,
            details={
                "supported_extensions": sorted(DOCUMENT_CONTENT_TYPES_BY_SUFFIX),
                "supported_content_types": sorted(SUPPORTED_DOCUMENT_CONTENT_TYPES),
            },
        )
    return content_type


def _validate_multi_image_count(count: int) -> None:
    if count < MIN_MULTI_IMAGE_COUNT or count > MAX_MULTI_IMAGE_COUNT:
        raise LinkedInPublishError(
            "LinkedIn multi-image posts require between 2 and 20 images.",
            code="media_invalid",
            retryable=False,
            details={
                "media_count": count,
                "min_media_count": MIN_MULTI_IMAGE_COUNT,
                "max_media_count": MAX_MULTI_IMAGE_COUNT,
            },
        )


def _normalize_alt_texts(alt_texts: Sequence[str], *, media_count: int) -> list[str]:
    values = [value.strip() for value in alt_texts]
    if values and len(values) != media_count:
        raise LinkedInPublishError(
            "Pass either no --alt-text values or exactly one --alt-text per image.",
            code="media_invalid",
            retryable=False,
            details={"alt_text_count": len(values), "media_count": media_count},
        )
    if not values:
        return [""] * media_count
    return values


def _validate_multi_image_entries(images: list[dict[str, str]]) -> list[dict[str, str]]:
    _validate_multi_image_count(len(images))
    normalized: list[dict[str, str]] = []
    for image in images:
        image_id = image.get("id", "").strip()
        if not image_id:
            raise LinkedInPublishError(
                "Each multi-image item requires an image URN.",
                code="media_invalid",
                retryable=False,
            )
        item = {"id": image_id}
        alt_text = image.get("altText", "").strip()
        if alt_text:
            item["altText"] = alt_text
        normalized.append(item)
    return normalized


def _coerce_video_byte(value: Any, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise LinkedInPublishError(
            "LinkedIn Videos API returned a non-integer upload byte range.",
            code="media_upload_failed",
            retryable=True,
        ) from exc


def _normalize_non_empty(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise LinkedInPublishError(
            f"{label} cannot be empty.",
            code="invalid_request",
            retryable=False,
        )
    return normalized


def _normalize_document_title(value: str) -> str:
    title = _normalize_non_empty(value, label="Document title")
    if len(title) > 255:
        raise LinkedInPublishError(
            "Document title cannot exceed 255 characters.",
            code="media_invalid",
            retryable=False,
            details={"max_length": 255, "length": len(title)},
        )
    return title


def _normalize_poll_question(value: str) -> str:
    question = _normalize_non_empty(value, label="Poll question")
    if len(question) > MAX_POLL_QUESTION_LENGTH:
        raise LinkedInPublishError(
            "Poll question cannot exceed 140 characters.",
            code="invalid_request",
            retryable=False,
            details={"max_length": MAX_POLL_QUESTION_LENGTH, "length": len(question)},
        )
    return question


def _normalize_poll_options(options: Sequence[str]) -> list[str]:
    values = [_normalize_non_empty(option, label="Poll option") for option in options]
    if len(values) < MIN_POLL_OPTION_COUNT or len(values) > MAX_POLL_OPTION_COUNT:
        raise LinkedInPublishError(
            "LinkedIn polls require between 2 and 4 options.",
            code="invalid_request",
            retryable=False,
            details={
                "option_count": len(values),
                "min_option_count": MIN_POLL_OPTION_COUNT,
                "max_option_count": MAX_POLL_OPTION_COUNT,
            },
        )
    too_long = [value for value in values if len(value) > MAX_POLL_OPTION_LENGTH]
    if too_long:
        raise LinkedInPublishError(
            "Poll options cannot exceed 30 characters.",
            code="invalid_request",
            retryable=False,
            details={"max_length": MAX_POLL_OPTION_LENGTH},
        )
    return values


def _normalize_actor_urn(value: str) -> str:
    actor = _normalize_non_empty(value, label="Actor URN")
    if actor.startswith(("urn:li:person:", "urn:li:organization:")):
        return actor
    raise LinkedInPublishError(
        "Actor must be a LinkedIn person or organization URN.",
        code="invalid_request",
        retryable=False,
        details={"accepted_prefixes": ["urn:li:person:", "urn:li:organization:"]},
    )


def normalize_poll_duration(value: str) -> str:
    normalized = _normalize_non_empty(value, label="Poll duration").lower()
    api_value = POLL_DURATION_MAP.get(normalized)
    if api_value:
        return api_value
    upper_value = normalized.upper()
    if upper_value in set(POLL_DURATION_MAP.values()):
        return upper_value
    raise LinkedInPublishError(
        f"Unsupported poll duration: {value}",
        code="invalid_request",
        retryable=False,
        details={"supported_durations": sorted(POLL_DURATION_MAP)},
    )


def normalize_reaction_type(value: str) -> str:
    normalized = _normalize_non_empty(value, label="Reaction type").lower()
    api_value = REACTION_TYPE_MAP.get(normalized)
    if api_value:
        return api_value
    upper_value = normalized.upper()
    if upper_value in set(REACTION_TYPE_MAP.values()):
        return upper_value
    raise LinkedInPublishError(
        f"Unsupported reaction type: {value}",
        code="invalid_request",
        retryable=False,
        details={"supported_reaction_types": sorted(REACTION_TYPE_MAP)},
    )


def normalize_comments_state(value: str) -> str:
    normalized = _normalize_non_empty(value, label="Comments state").lower()
    api_value = COMMENT_STATE_MAP.get(normalized)
    if api_value:
        return api_value
    upper_value = normalized.upper()
    if upper_value in set(COMMENT_STATE_MAP.values()):
        return upper_value
    raise LinkedInPublishError(
        f"Unsupported comments state: {value}",
        code="invalid_request",
        retryable=False,
        details={"supported_comments_states": sorted(COMMENT_STATE_MAP)},
    )


def _reaction_key(*, actor: str, entity: str) -> str:
    return f"(actor:{quote(actor, safe='')},entity:{quote(entity, safe='')})"


def normalize_social_entity_id(entity: str) -> str:
    """Return a URN accepted by LinkedIn's official social action APIs."""
    value = _normalize_non_empty(entity, label="Entity")
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        path_parts = [unquote(part) for part in parsed.path.split("/") if part]
        if "feed" in path_parts and "update" in path_parts:
            value = path_parts[-1]
        else:
            raise LinkedInPublishError(
                "LinkedIn social APIs accept a feed update URL or a supported entity URN.",
                code="invalid_request",
                retryable=False,
            )
    value = unquote(value.strip().rstrip("/"))
    if value.startswith(
        (
            "urn:li:share:",
            "urn:li:ugcPost:",
            "urn:li:activity:",
            "urn:li:comment:",
        )
    ):
        return value
    if value.isdigit():
        return f"urn:li:share:{value}"
    raise LinkedInPublishError(
        "LinkedIn social APIs accept share, ugcPost, activity, or comment URNs.",
        code="invalid_request",
        retryable=False,
        details={
            "accepted_prefixes": [
                "urn:li:share:",
                "urn:li:ugcPost:",
                "urn:li:activity:",
                "urn:li:comment:",
            ]
        },
    )


def normalize_organization_urn(value: str) -> str:
    """Return an organization URN accepted by LinkedIn organization analytics APIs."""
    normalized = unquote(_normalize_non_empty(value, label="Organization").strip().rstrip("/"))
    if normalized.startswith("urn:li:organization:"):
        return normalized
    if normalized.isdigit():
        return f"urn:li:organization:{normalized}"
    raise LinkedInPublishError(
        "LinkedIn organization insights require an organization URN or numeric organization id.",
        code="invalid_request",
        retryable=False,
        details={"accepted_prefixes": ["urn:li:organization:"]},
    )


def normalize_share_urn(value: str) -> str:
    """Return a share URN accepted by LinkedIn organization share statistics filters."""
    normalized = unquote(_normalize_non_empty(value, label="Share").strip().rstrip("/"))
    if normalized.startswith("urn:li:share:"):
        return normalized
    if normalized.isdigit():
        return f"urn:li:share:{normalized}"
    raise LinkedInPublishError(
        "LinkedIn organization share statistics --share filters require share URNs or numeric share ids.",
        code="invalid_request",
        retryable=False,
        details={"accepted_prefixes": ["urn:li:share:"]},
    )


def normalize_ugc_post_urn(value: str) -> str:
    """Return a UGC post URN accepted by LinkedIn organization share statistics filters."""
    normalized = unquote(_normalize_non_empty(value, label="UGC post").strip().rstrip("/"))
    if normalized.startswith("urn:li:ugcPost:"):
        return normalized
    if normalized.isdigit():
        return f"urn:li:ugcPost:{normalized}"
    raise LinkedInPublishError(
        "LinkedIn organization share statistics --ugc-post filters require ugcPost URNs or numeric ids.",
        code="invalid_request",
        retryable=False,
        details={"accepted_prefixes": ["urn:li:ugcPost:"]},
    )


def normalize_time_granularity(value: str) -> str:
    """Return a LinkedIn analytics time granularity enum."""
    normalized = _normalize_non_empty(value, label="Time granularity").replace("-", "_").upper()
    if normalized in {"DAY", "MONTH"}:
        return normalized
    raise LinkedInPublishError(
        "LinkedIn organization share statistics time granularity must be DAY or MONTH.",
        code="invalid_request",
        retryable=False,
        details={"supported_time_granularity": ["DAY", "MONTH"]},
    )


def _restli_list(values: Sequence[str]) -> str:
    return "List(" + ",".join(values) + ")"


def normalize_post_id(post_id: str) -> str:
    """Return a share or ugcPost URN accepted by LinkedIn's official Posts API."""
    value = post_id.strip()
    if not value:
        raise LinkedInPublishError(
            "Post id cannot be empty.",
            code="invalid_request",
            retryable=False,
        )

    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        path_parts = [unquote(part) for part in parsed.path.split("/") if part]
        if "feed" in path_parts and "update" in path_parts:
            value = path_parts[-1]
        else:
            raise LinkedInPublishError(
                "LinkedIn post delete accepts a feed update URL, share URN, ugcPost URN, or numeric share id.",
                code="invalid_request",
                retryable=False,
            )

    value = unquote(value.strip().rstrip("/"))
    if value.isdigit():
        return f"urn:li:share:{value}"
    if value.startswith(("urn:li:share:", "urn:li:ugcPost:")):
        return value
    if value.startswith("urn:li:activity:"):
        raise LinkedInPublishError(
            "Official LinkedIn post delete requires a share or ugcPost URN, not an activity URN.",
            code="invalid_request",
            retryable=False,
            details={"accepted_prefixes": ["urn:li:share:", "urn:li:ugcPost:"]},
        )
    raise LinkedInPublishError(
        "LinkedIn post delete accepts a feed update URL, share URN, ugcPost URN, or numeric share id.",
        code="invalid_request",
        retryable=False,
        details={"accepted_prefixes": ["urn:li:share:", "urn:li:ugcPost:"]},
    )


def normalize_delete_post_id(post_id: str) -> str:
    """Return a share or ugcPost URN accepted by LinkedIn's official delete API."""
    return normalize_post_id(post_id)
