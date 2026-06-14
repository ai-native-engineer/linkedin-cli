"""Official LinkedIn Share on LinkedIn publisher."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import mimetypes
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, unquote, urlencode, urlparse

import httpx

from .oauth import OAuthConfig

POSTS_URL = "https://api.linkedin.com/rest/posts"
REST_POSTS_URL = POSTS_URL
IMAGES_INITIALIZE_URL = "https://api.linkedin.com/rest/images?action=initializeUpload"
RESTLI_PROTOCOL_VERSION = "2.0.0"
SUPPORTED_IMAGE_CONTENT_TYPES = {"image/gif", "image/jpeg", "image/png"}
VISIBILITY_MAP = {
    "public": "PUBLIC",
    "connections": "CONNECTIONS",
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
        path = media_path.expanduser()
        if not path.exists() or not path.is_file():
            raise LinkedInPublishError(
                f"Media file not found: {path}",
                code="media_invalid",
                retryable=False,
            )
        content_type = _image_content_type(path)
        image_urn = self._upload_image(path, content_type=content_type)
        payload = self.build_media_payload(text=text, visibility=visibility, image_urn=image_urn)
        return self._create_post(payload=payload, visibility=visibility, media={"image": image_urn})

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
