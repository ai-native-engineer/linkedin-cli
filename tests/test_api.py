from __future__ import annotations

import json
from pathlib import Path

from linkedin_cli.api import DRY_RUN_IMAGE_URN
from linkedin_cli.api import LinkedInWriteAPI
from linkedin_cli.oauth import OAuthConfig
from linkedin_cli.publisher import DeleteResult
from linkedin_cli.publisher import PublishResult


class FakePublisher:
    def __init__(self) -> None:
        self.text_calls = []
        self.image_calls = []
        self.delete_calls = []

    def build_text_payload(self, *, text, visibility):
        body = text.strip()
        return {
            "author": "urn:li:person:abc",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": body},
                },
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": visibility.upper(),
            },
        }

    def build_media_payload(self, *, text, visibility, image_urn):
        payload = self.build_text_payload(text=text, visibility=visibility)
        payload["content"] = {"media": {"id": image_urn}}
        return payload

    def post_text(self, *, text, visibility):
        self.text_calls.append({"text": text, "visibility": visibility})
        return PublishResult(
            post_id="urn:li:share:123",
            url="https://www.linkedin.com/feed/update/urn:li:share:123/",
            created_at="2026-06-15T00:00:00Z",
            visibility=visibility,
            raw={},
        )

    def post_image(self, *, text, visibility, media_path):
        self.image_calls.append({"text": text, "visibility": visibility, "media_path": media_path})
        return PublishResult(
            post_id="urn:li:share:456",
            url="https://www.linkedin.com/feed/update/urn:li:share:456/",
            created_at="2026-06-15T00:00:00Z",
            visibility=visibility,
            raw={},
        )

    def normalize_delete_post_id(self, post_id):
        if post_id.isdigit():
            return f"urn:li:share:{post_id}"
        return post_id

    def delete_post(self, *, post_id):
        self.delete_calls.append({"post_id": post_id})
        return DeleteResult(
            post_id="urn:li:share:789",
            deleted_at="2026-06-15T00:00:00Z",
            raw={},
        )


def _api(fake: FakePublisher) -> LinkedInWriteAPI:
    return LinkedInWriteAPI(
        OAuthConfig(
            access_token="token-123",
            author_urn="urn:li:person:abc",
            linkedin_version="202605",
            source="test",
        ),
        publisher=fake,
    )


def test_plan_text_post_returns_programmatic_payload() -> None:
    api = _api(FakePublisher())

    plan = api.plan_text_post(text=" hello ", visibility="public")

    assert plan.command == "post.text"
    assert plan.api == "linkedin.ugcPosts"
    assert plan.text_length == 5
    assert plan.media_count == 0
    assert plan.author_urn == "urn:li:person:abc"
    assert plan.linkedin_version == "202605"
    assert plan.payload["specificContent"]["com.linkedin.ugc.ShareContent"]["shareCommentary"] == {
        "text": "hello"
    }
    assert plan.to_dict()["media_paths"] == []


def test_plan_image_post_uses_dry_run_image_placeholder() -> None:
    api = _api(FakePublisher())

    plan = api.plan_image_post(text=" hello image ", media_path="~/image.png", visibility="public")

    assert plan.command == "post.media"
    assert plan.api == "linkedin.ugcPosts+assets"
    assert plan.text_length == 11
    assert plan.media_count == 1
    assert plan.payload["content"]["media"]["id"] == DRY_RUN_IMAGE_URN
    assert plan.media_paths == (str(Path("~/image.png").expanduser()),)


def test_create_text_post_delegates_to_publisher() -> None:
    fake = FakePublisher()
    api = _api(fake)

    result = api.create_text_post(text="hello", visibility="connections")

    assert result.post_id == "urn:li:share:123"
    assert fake.text_calls == [{"text": "hello", "visibility": "connections"}]


def test_create_image_post_delegates_to_publisher() -> None:
    fake = FakePublisher()
    api = _api(fake)

    result = api.create_image_post(text="hello", media_path="image.png", visibility="public")

    assert result.post_id == "urn:li:share:456"
    assert fake.image_calls == [
        {"text": "hello", "visibility": "public", "media_path": Path("image.png")}
    ]


def test_plan_delete_post_returns_programmatic_payload() -> None:
    api = _api(FakePublisher())

    plan = api.plan_delete_post(post_id="789")

    assert plan.command == "post.delete"
    assert plan.api == "linkedin.posts.delete"
    assert plan.post_id == "urn:li:share:789"
    assert plan.author_urn == "urn:li:person:abc"
    assert plan.linkedin_version == "202605"
    assert plan.to_dict()["post_id"] == "urn:li:share:789"


def test_delete_post_delegates_to_publisher() -> None:
    fake = FakePublisher()
    api = _api(fake)

    result = api.delete_post(post_id="urn:li:share:789")

    assert result.post_id == "urn:li:share:789"
    assert fake.delete_calls == [{"post_id": "urn:li:share:789"}]


def test_from_config_accepts_string_path(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN", raising=False)
    token_path = tmp_path / "oauth.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "token-123",
                "author_urn": "urn:li:person:abc",
                "linkedin_version": "202605",
            }
        ),
        encoding="utf-8",
    )

    api = LinkedInWriteAPI.from_config(str(token_path))

    assert api.oauth.access_token == "token-123"
    assert api.oauth.author_urn == "urn:li:person:abc"
