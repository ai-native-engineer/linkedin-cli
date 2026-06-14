from __future__ import annotations

import httpx
import pytest

from linkedin_cli.oauth import OAuthConfig
from linkedin_cli.publisher import IMAGES_INITIALIZE_URL
from linkedin_cli.publisher import LinkedInPublishError
from linkedin_cli.publisher import LinkedInPublisher
from linkedin_cli.publisher import POSTS_URL
from linkedin_cli.publisher import REST_POSTS_URL
from linkedin_cli.publisher import normalize_delete_post_id


class FakeClient:
    def __init__(self, *post_responses: httpx.Response, put_response: httpx.Response | None = None) -> None:
        self.post_responses = list(post_responses)
        self.put_response = put_response or httpx.Response(201)
        self.calls = []
        self.delete_calls = []
        self.get_calls = []
        self.put_calls = []

    def post(self, url, *, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.post_responses.pop(0)

    def put(self, url, *, content, headers):
        self.put_calls.append({"url": url, "content": content, "headers": headers})
        return self.put_response

    def delete(self, url, *, headers):
        self.delete_calls.append({"url": url, "headers": headers})
        return self.post_responses.pop(0)

    def get(self, url, *, headers):
        self.get_calls.append({"url": url, "headers": headers})
        return self.post_responses.pop(0)


def _oauth() -> OAuthConfig:
    return OAuthConfig(
        access_token="token-123",
        author_urn="urn:li:person:abc",
        linkedin_version="202605",
        source="test",
    )


def test_build_text_payload() -> None:
    publisher = LinkedInPublisher(_oauth(), client=FakeClient(httpx.Response(201)))

    payload = publisher.build_text_payload(text=" hello ", visibility="public")

    assert payload == {
        "author": "urn:li:person:abc",
        "commentary": "hello",
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }


def test_post_text_success() -> None:
    response = httpx.Response(201, headers={"x-restli-id": "urn:li:share:123"})
    client = FakeClient(response)
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.post_text(text="hello", visibility="public")

    assert result.post_id == "urn:li:share:123"
    assert result.url == "https://www.linkedin.com/feed/update/urn:li:share:123/"
    assert result.visibility == "public"
    assert client.calls[0]["url"] == POSTS_URL
    assert client.calls[0]["headers"]["Authorization"] == "Bearer token-123"
    assert client.calls[0]["headers"]["LinkedIn-Version"] == "202605"
    assert client.calls[0]["json"]["commentary"] == "hello"
    assert client.calls[0]["json"]["visibility"] == "PUBLIC"


def test_post_image_success(tmp_path) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"png-bytes")
    init_response = httpx.Response(
        200,
        json={
            "value": {
                "uploadUrl": "https://upload.example.test/image",
                "image": "urn:li:image:abc",
            }
        },
    )
    post_response = httpx.Response(201, headers={"x-restli-id": "urn:li:share:456"})
    client = FakeClient(init_response, post_response)
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.post_image(text="hello image", visibility="public", media_path=image_path)

    assert result.post_id == "urn:li:share:456"
    assert result.raw["request"]["media"] == {"image": "urn:li:image:abc"}
    assert client.calls[0]["url"] == IMAGES_INITIALIZE_URL
    assert client.calls[0]["json"] == {
        "initializeUploadRequest": {
            "owner": "urn:li:person:abc",
        }
    }
    assert client.put_calls[0]["url"] == "https://upload.example.test/image"
    assert client.put_calls[0]["content"] == b"png-bytes"
    assert client.put_calls[0]["headers"]["Content-Type"] == "image/png"
    assert client.calls[1]["url"] == POSTS_URL
    assert client.calls[1]["json"]["content"]["media"]["id"] == "urn:li:image:abc"


def test_build_article_payload() -> None:
    publisher = LinkedInPublisher(_oauth(), client=FakeClient(httpx.Response(201)))

    payload = publisher.build_article_payload(
        text=" article ",
        visibility="public",
        url="https://example.com/post",
        title="Example",
        description="Description",
        thumbnail="urn:li:image:abc",
    )

    assert payload["commentary"] == "article"
    assert payload["content"]["article"] == {
        "source": "https://example.com/post",
        "title": "Example",
        "description": "Description",
        "thumbnail": "urn:li:image:abc",
    }


def test_build_reshare_payload_normalizes_parent() -> None:
    publisher = LinkedInPublisher(_oauth(), client=FakeClient(httpx.Response(201)))

    payload = publisher.build_reshare_payload(text="reshare", visibility="public", parent="123")

    assert payload["reshareContext"] == {"parent": "urn:li:share:123"}


def test_update_post_success() -> None:
    client = FakeClient(httpx.Response(204))
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.update_post(post_id="urn:li:share:123", text="updated")

    assert result.post_id == "urn:li:share:123"
    assert result.raw["request"]["payload"] == {"patch": {"$set": {"commentary": "updated"}}}
    assert client.calls[0]["url"] == f"{REST_POSTS_URL}/urn%3Ali%3Ashare%3A123"
    assert client.calls[0]["headers"]["X-RestLi-Method"] == "PARTIAL_UPDATE"


def test_get_post_success() -> None:
    client = FakeClient(httpx.Response(200, json={"id": "urn:li:share:123", "commentary": "hello"}))
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.get_post(post_id="urn:li:share:123", view_context="AUTHOR")

    assert result.post_id == "urn:li:share:123"
    assert result.raw["commentary"] == "hello"
    assert client.get_calls[0]["url"] == f"{REST_POSTS_URL}/urn%3Ali%3Ashare%3A123?viewContext=AUTHOR"


def test_list_posts_by_author_success() -> None:
    response = httpx.Response(
        200,
        json={
            "elements": [{"id": "urn:li:share:123"}],
            "paging": {"count": 1, "start": 0},
        },
    )
    client = FakeClient(response)
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.list_posts_by_author(author_urn="urn:li:person:abc", count=1, start=0)

    assert result.elements == [{"id": "urn:li:share:123"}]
    assert "author=urn%3Ali%3Aperson%3Aabc" in client.get_calls[0]["url"]
    assert "q=author" in client.get_calls[0]["url"]
    assert client.get_calls[0]["headers"]["X-RestLi-Method"] == "FINDER"


def test_delete_post_success() -> None:
    client = FakeClient(httpx.Response(204))
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.delete_post(post_id="urn:li:share:123")

    assert result.post_id == "urn:li:share:123"
    assert result.raw["status_code"] == 204
    assert result.raw["request"] == {
        "api": "linkedin.posts.delete",
        "post_id": "urn:li:share:123",
    }
    assert client.delete_calls[0]["url"] == f"{REST_POSTS_URL}/urn%3Ali%3Ashare%3A123"
    assert client.delete_calls[0]["headers"]["Authorization"] == "Bearer token-123"
    assert client.delete_calls[0]["headers"]["LinkedIn-Version"] == "202605"
    assert client.delete_calls[0]["headers"]["X-RestLi-Method"] == "DELETE"


def test_delete_post_error_mapping() -> None:
    client = FakeClient(httpx.Response(403, json={"message": "denied"}))
    publisher = LinkedInPublisher(_oauth(), client=client)

    with pytest.raises(LinkedInPublishError) as error:
        publisher.delete_post(post_id="urn:li:share:123")

    assert error.value.code == "permission_denied"
    assert error.value.retryable is False
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("urn:li:share:123", "urn:li:share:123"),
        ("urn%3Ali%3Ashare%3A123", "urn:li:share:123"),
        ("urn:li:ugcPost:456", "urn:li:ugcPost:456"),
        ("123", "urn:li:share:123"),
        (
            "https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A123/",
            "urn:li:share:123",
        ),
    ],
)
def test_normalize_delete_post_id(value, expected) -> None:
    assert normalize_delete_post_id(value) == expected


def test_normalize_delete_post_id_rejects_activity_urn() -> None:
    with pytest.raises(LinkedInPublishError) as error:
        normalize_delete_post_id("urn:li:activity:123")

    assert error.value.code == "invalid_request"


def test_post_image_rejects_unsupported_file_type(tmp_path) -> None:
    media_path = tmp_path / "image.txt"
    media_path.write_text("not an image", encoding="utf-8")
    publisher = LinkedInPublisher(_oauth(), client=FakeClient(httpx.Response(201)))

    with pytest.raises(LinkedInPublishError) as error:
        publisher.post_image(text="hello", visibility="public", media_path=media_path)

    assert error.value.code == "media_invalid"
    assert error.value.retryable is False


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (400, "invalid_request", False),
        (401, "auth_expired", False),
        (403, "permission_denied", False),
        (404, "not_found", False),
        (429, "rate_limited", True),
        (500, "upstream_unavailable", True),
    ],
)
def test_post_text_error_mapping(status_code, expected_code, retryable) -> None:
    response = httpx.Response(status_code, json={"message": "rejected"})
    publisher = LinkedInPublisher(_oauth(), client=FakeClient(response))

    with pytest.raises(LinkedInPublishError) as error:
        publisher.post_text(text="hello", visibility="public")

    assert error.value.code == expected_code
    assert error.value.retryable is retryable
    assert error.value.status_code == status_code


def test_publisher_close_leaves_injected_client_open() -> None:
    # FakeClient has no .close(); an injected client is caller-owned, so close()
    # and the context manager must be no-ops (otherwise this raises AttributeError).
    publisher = LinkedInPublisher(_oauth(), client=FakeClient(httpx.Response(201)))
    publisher.close()
    with publisher:
        pass


def test_post_text_error_extracts_numeric_retry_after() -> None:
    response = httpx.Response(429, headers={"Retry-After": "30"}, json={"message": "rate"})
    publisher = LinkedInPublisher(_oauth(), client=FakeClient(response))

    with pytest.raises(LinkedInPublishError) as error:
        publisher.post_text(text="hello", visibility="public")

    assert error.value.details["retry_after_seconds"] == 30


def test_post_text_error_omits_non_numeric_retry_after() -> None:
    response = httpx.Response(
        429,
        headers={"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"},
        json={"message": "rate"},
    )
    publisher = LinkedInPublisher(_oauth(), client=FakeClient(response))

    with pytest.raises(LinkedInPublishError) as error:
        publisher.post_text(text="hello", visibility="public")

    # Non-numeric Retry-After must not surface as a null key (contract: integer or absent).
    assert "retry_after_seconds" not in error.value.details


def test_image_init_failure_is_retryable_media_upload_failed(tmp_path) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"png-bytes")
    init_response = httpx.Response(422, json={"message": "bad upload"})
    publisher = LinkedInPublisher(_oauth(), client=FakeClient(init_response))

    with pytest.raises(LinkedInPublishError) as error:
        publisher.post_image(text="hello", visibility="public", media_path=image_path)

    assert error.value.code == "media_upload_failed"
    assert error.value.retryable is True
