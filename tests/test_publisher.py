from __future__ import annotations

import httpx
import pytest

from linkedin_cli.oauth import OAuthConfig
from linkedin_cli.publisher import IMAGES_INITIALIZE_URL
from linkedin_cli.publisher import LinkedInPublishError
from linkedin_cli.publisher import LinkedInPublisher
from linkedin_cli.publisher import POSTS_URL
from linkedin_cli.publisher import REACTIONS_URL
from linkedin_cli.publisher import REST_POSTS_URL
from linkedin_cli.publisher import SOCIAL_ACTIONS_URL
from linkedin_cli.publisher import SOCIAL_METADATA_URL
from linkedin_cli.publisher import VIDEOS_FINALIZE_URL
from linkedin_cli.publisher import VIDEOS_INITIALIZE_URL
from linkedin_cli.publisher import normalize_reaction_type
from linkedin_cli.publisher import normalize_social_entity_id
from linkedin_cli.publisher import normalize_delete_post_id


class FakeClient:
    def __init__(
        self,
        *post_responses: httpx.Response,
        put_response: httpx.Response | None = None,
        put_responses: list[httpx.Response] | None = None,
    ) -> None:
        self.post_responses = list(post_responses)
        self.put_response = put_response or httpx.Response(201)
        self.put_responses = list(put_responses or [])
        self.calls = []
        self.delete_calls = []
        self.get_calls = []
        self.put_calls = []

    def post(self, url, *, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.post_responses.pop(0)

    def put(self, url, *, content, headers):
        self.put_calls.append({"url": url, "content": content, "headers": headers})
        if self.put_responses:
            return self.put_responses.pop(0)
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


def test_post_multi_image_success(tmp_path) -> None:
    first_path = tmp_path / "one.png"
    second_path = tmp_path / "two.jpg"
    first_path.write_bytes(b"one")
    second_path.write_bytes(b"two")
    first_init_response = httpx.Response(
        200,
        json={
            "value": {
                "uploadUrl": "https://upload.example.test/one",
                "image": "urn:li:image:one",
            }
        },
    )
    second_init_response = httpx.Response(
        200,
        json={
            "value": {
                "uploadUrl": "https://upload.example.test/two",
                "image": "urn:li:image:two",
            }
        },
    )
    post_response = httpx.Response(201, headers={"x-restli-id": "urn:li:share:multi"})
    client = FakeClient(first_init_response, second_init_response, post_response)
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.post_multi_image(
        text="hello images",
        visibility="public",
        media_paths=[first_path, second_path],
        alt_texts=("one alt", "two alt"),
    )

    assert result.post_id == "urn:li:share:multi"
    assert client.calls[0]["url"] == IMAGES_INITIALIZE_URL
    assert client.calls[1]["url"] == IMAGES_INITIALIZE_URL
    assert client.put_calls[0]["content"] == b"one"
    assert client.put_calls[1]["content"] == b"two"
    assert client.calls[2]["url"] == POSTS_URL
    assert client.calls[2]["json"]["content"]["multiImage"]["images"] == [
        {"id": "urn:li:image:one", "altText": "one alt"},
        {"id": "urn:li:image:two", "altText": "two alt"},
    ]
    assert result.raw["request"]["media"] == {
        "multiImage": [
            {"id": "urn:li:image:one", "altText": "one alt"},
            {"id": "urn:li:image:two", "altText": "two alt"},
        ]
    }


def test_build_multi_image_payload_rejects_single_image() -> None:
    publisher = LinkedInPublisher(_oauth(), client=FakeClient(httpx.Response(201)))

    with pytest.raises(LinkedInPublishError) as error:
        publisher.build_multi_image_payload(
            text="hello",
            visibility="public",
            images=[{"id": "urn:li:image:one"}],
        )

    assert error.value.code == "media_invalid"
    assert error.value.details["min_media_count"] == 2


def test_build_video_payload() -> None:
    publisher = LinkedInPublisher(_oauth(), client=FakeClient(httpx.Response(201)))

    payload = publisher.build_video_payload(
        text=" video ",
        visibility="public",
        video_urn="urn:li:video:abc",
        title="Demo",
    )

    assert payload["commentary"] == "video"
    assert payload["content"]["media"] == {
        "id": "urn:li:video:abc",
        "title": "Demo",
    }


def test_post_video_success(tmp_path) -> None:
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"0123456789")
    init_response = httpx.Response(
        200,
        json={
            "value": {
                "video": "urn:li:video:abc",
                "uploadToken": "token-456",
                "uploadInstructions": [
                    {
                        "uploadUrl": "https://upload.example.test/video/part-1",
                        "firstByte": 0,
                        "lastByte": 4,
                    },
                    {
                        "uploadUrl": "https://upload.example.test/video/part-2",
                        "firstByte": 5,
                        "lastByte": 9,
                    },
                ],
            }
        },
    )
    finalize_response = httpx.Response(200, json={"value": {"status": "AVAILABLE"}})
    post_response = httpx.Response(201, headers={"x-restli-id": "urn:li:share:video"})
    client = FakeClient(
        init_response,
        finalize_response,
        post_response,
        put_responses=[
            httpx.Response(200, headers={"ETag": '"part-one"'}),
            httpx.Response(200, headers={"ETag": "part-two"}),
        ],
    )
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.post_video(
        text="hello video",
        visibility="public",
        media_path=video_path,
        title="Demo video",
    )

    assert result.post_id == "urn:li:share:video"
    assert client.calls[0]["url"] == VIDEOS_INITIALIZE_URL
    assert client.calls[0]["json"]["initializeUploadRequest"]["fileSizeBytes"] == 10
    assert client.put_calls[0]["content"] == b"01234"
    assert client.put_calls[1]["content"] == b"56789"
    assert client.put_calls[0]["headers"]["Content-Type"] == "application/octet-stream"
    assert client.calls[1]["url"] == VIDEOS_FINALIZE_URL
    assert client.calls[1]["json"]["finalizeUploadRequest"] == {
        "video": "urn:li:video:abc",
        "uploadToken": "token-456",
        "uploadedPartIds": ["part-one", "part-two"],
    }
    assert client.calls[2]["url"] == POSTS_URL
    assert client.calls[2]["json"]["content"]["media"] == {
        "id": "urn:li:video:abc",
        "title": "Demo video",
    }
    assert result.raw["request"]["media"] == {"video": "urn:li:video:abc"}


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


def test_create_comment_success() -> None:
    response = httpx.Response(201, json={"id": "comment-1", "message": {"text": "hello"}})
    client = FakeClient(response)
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.create_comment(entity="urn:li:ugcPost:123", text=" hello ")

    assert result.comment_id == "comment-1"
    assert result.entity_urn == "urn:li:ugcPost:123"
    assert client.calls[0]["url"] == f"{SOCIAL_ACTIONS_URL}/urn%3Ali%3AugcPost%3A123/comments"
    assert client.calls[0]["json"] == {
        "actor": "urn:li:person:abc",
        "object": "urn:li:ugcPost:123",
        "message": {"text": "hello"},
    }


def test_list_comments_success() -> None:
    response = httpx.Response(
        200,
        json={"elements": [{"id": "comment-1"}], "paging": {"count": 1, "start": 0}},
    )
    client = FakeClient(response)
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.list_comments(entity="urn:li:ugcPost:123", count=1, start=0)

    assert result.elements == [{"id": "comment-1"}]
    assert client.get_calls[0]["url"] == (
        f"{SOCIAL_ACTIONS_URL}/urn%3Ali%3AugcPost%3A123/comments?count=1&start=0"
    )


def test_get_comment_success() -> None:
    response = httpx.Response(200, json={"id": "comment-1"})
    client = FakeClient(response)
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.get_comment(entity="urn:li:ugcPost:123", comment_id="comment-1")

    assert result.comment_id == "comment-1"
    assert client.get_calls[0]["url"] == (
        f"{SOCIAL_ACTIONS_URL}/urn%3Ali%3AugcPost%3A123/comments/comment-1"
    )


def test_update_comment_success() -> None:
    response = httpx.Response(204)
    client = FakeClient(response)
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.update_comment(
        entity="urn:li:ugcPost:123",
        comment_id="comment-1",
        text=" updated ",
    )

    assert result.action == "comment.update"
    assert client.calls[0]["url"] == (
        f"{SOCIAL_ACTIONS_URL}/urn%3Ali%3AugcPost%3A123/comments/comment-1?"
        "actor=urn%3Ali%3Aperson%3Aabc"
    )
    assert client.calls[0]["headers"]["X-RestLi-Method"] == "PARTIAL_UPDATE"
    assert client.calls[0]["json"] == {
        "patch": {"message": {"$set": {"text": "updated"}}}
    }


def test_create_reaction_success() -> None:
    response = httpx.Response(201, json={"id": "reaction-1", "reactionType": "PRAISE"})
    client = FakeClient(response)
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.create_reaction(entity="urn:li:ugcPost:123", reaction_type="celebrate")

    assert result.raw["reactionType"] == "PRAISE"
    assert client.calls[0]["url"] == f"{REACTIONS_URL}?actor=urn%3Ali%3Aperson%3Aabc"
    assert client.calls[0]["json"] == {
        "root": "urn:li:ugcPost:123",
        "reactionType": "PRAISE",
    }


def test_list_reactions_success() -> None:
    response = httpx.Response(
        200,
        json={"elements": [{"id": "reaction-1"}], "paging": {"count": 1, "start": 0}},
    )
    client = FakeClient(response)
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.list_reactions(entity="urn:li:ugcPost:123", count=1, start=0)

    assert result.elements == [{"id": "reaction-1"}]
    assert client.get_calls[0]["url"].startswith(
        f"{REACTIONS_URL}/(entity:urn%3Ali%3AugcPost%3A123)?"
    )
    assert "q=entity" in client.get_calls[0]["url"]


def test_get_reaction_success() -> None:
    response = httpx.Response(200, json={"reactionType": "LIKE"})
    client = FakeClient(response)
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.get_reaction(entity="urn:li:ugcPost:123")

    assert result.raw["reactionType"] == "LIKE"
    assert client.get_calls[0]["url"] == (
        f"{REACTIONS_URL}/"
        "(actor:urn%3Ali%3Aperson%3Aabc,entity:urn%3Ali%3AugcPost%3A123)"
    )


def test_delete_reaction_success() -> None:
    client = FakeClient(httpx.Response(204))
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.delete_reaction(entity="urn:li:ugcPost:123")

    assert result.action == "reaction.delete"
    assert client.delete_calls[0]["url"] == (
        f"{REACTIONS_URL}/"
        "(actor:urn%3Ali%3Aperson%3Aabc,entity:urn%3Ali%3AugcPost%3A123)"
    )


def test_get_social_metadata_success() -> None:
    response = httpx.Response(200, json={"entity": "urn:li:ugcPost:123", "commentsState": "OPEN"})
    client = FakeClient(response)
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.get_social_metadata(entity="urn:li:ugcPost:123")

    assert result.raw["commentsState"] == "OPEN"
    assert client.get_calls[0]["url"] == f"{SOCIAL_METADATA_URL}/urn%3Ali%3AugcPost%3A123"


def test_update_comments_state_success() -> None:
    client = FakeClient(httpx.Response(202))
    publisher = LinkedInPublisher(_oauth(), client=client)

    result = publisher.update_comments_state(entity="urn:li:ugcPost:123", state="closed")

    assert result.entity_urn == "urn:li:ugcPost:123"
    assert client.calls[0]["url"] == (
        f"{SOCIAL_METADATA_URL}/urn%3Ali%3AugcPost%3A123?"
        "actor=urn%3Ali%3Aperson%3Aabc"
    )
    assert client.calls[0]["headers"]["X-RestLi-Method"] == "PARTIAL_UPDATE"
    assert client.calls[0]["json"] == {"patch": {"$set": {"commentsState": "CLOSED"}}}


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


def test_normalize_social_entity_id_accepts_feed_update_url() -> None:
    assert (
        normalize_social_entity_id(
            "https://www.linkedin.com/feed/update/urn%3Ali%3AugcPost%3A123/"
        )
        == "urn:li:ugcPost:123"
    )


def test_normalize_reaction_type_maps_ui_names() -> None:
    assert normalize_reaction_type("celebrate") == "PRAISE"
    assert normalize_reaction_type("support") == "APPRECIATION"
    assert normalize_reaction_type("funny") == "ENTERTAINMENT"


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
