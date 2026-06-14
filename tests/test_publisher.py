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
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": "hello"},
                "shareMediaCategory": "NONE",
            },
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
        },
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
    assert "Linkedin-Version" not in client.calls[0]["headers"]
    assert client.calls[0]["json"]["specificContent"]["com.linkedin.ugc.ShareContent"][
        "shareCommentary"
    ] == {"text": "hello"}


def test_post_image_success(tmp_path) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"png-bytes")
    init_response = httpx.Response(
        200,
        json={
            "value": {
                "uploadMechanism": {
                    "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest": {
                        "uploadUrl": "https://upload.example.test/image",
                    }
                },
                "asset": "urn:li:digitalmediaAsset:abc",
            }
        },
    )
    post_response = httpx.Response(201, headers={"x-restli-id": "urn:li:share:456"})
    client = FakeClient(init_response, post_response)
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.post_image(text="hello image", visibility="public", media_path=image_path)

    assert result.post_id == "urn:li:share:456"
    assert result.raw["request"]["media"] == {"image": "urn:li:digitalmediaAsset:abc"}
    assert client.calls[0]["url"] == IMAGES_INITIALIZE_URL
    assert client.calls[0]["json"] == {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": "urn:li:person:abc",
            "serviceRelationships": [
                {
                    "relationshipType": "OWNER",
                    "identifier": "urn:li:userGeneratedContent",
                }
            ],
        }
    }
    assert client.put_calls[0]["url"] == "https://upload.example.test/image"
    assert client.put_calls[0]["content"] == b"png-bytes"
    assert client.put_calls[0]["headers"]["Content-Type"] == "image/png"
    assert client.calls[1]["url"] == POSTS_URL
    share_content = client.calls[1]["json"]["specificContent"]["com.linkedin.ugc.ShareContent"]
    assert share_content["shareMediaCategory"] == "IMAGE"
    assert share_content["media"][0]["media"] == "urn:li:digitalmediaAsset:abc"


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
