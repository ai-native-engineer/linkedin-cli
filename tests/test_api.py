from __future__ import annotations

import json
from pathlib import Path

from linkedin_cli.api import DRY_RUN_IMAGE_URN
from linkedin_cli.api import DRY_RUN_VIDEO_URN
from linkedin_cli.api import LinkedInWriteAPI
from linkedin_cli.oauth import OAuthConfig
from linkedin_cli.publisher import DeleteResult
from linkedin_cli.publisher import GetPostResult
from linkedin_cli.publisher import ListPostsResult
from linkedin_cli.publisher import PublishResult
from linkedin_cli.publisher import UpdateResult


class FakePublisher:
    def __init__(self) -> None:
        self.text_calls = []
        self.image_calls = []
        self.multi_image_calls = []
        self.video_calls = []
        self.delete_calls = []
        self.article_calls = []
        self.reshare_calls = []
        self.update_calls = []

    def build_text_payload(self, *, text, visibility):
        body = text.strip()
        return {
            "author": "urn:li:person:abc",
            "commentary": body,
            "visibility": visibility.upper(),
        }

    def build_media_payload(self, *, text, visibility, image_urn):
        payload = self.build_text_payload(text=text, visibility=visibility)
        payload["content"] = {"media": {"id": image_urn}}
        return payload

    def build_multi_image_payload(self, *, text, visibility, images):
        payload = self.build_text_payload(text=text, visibility=visibility)
        payload["content"] = {"multiImage": {"images": images}}
        return payload

    def build_video_payload(self, *, text, visibility, video_urn, title=None):
        payload = self.build_text_payload(text=text, visibility=visibility)
        media = {"id": video_urn}
        if title:
            media["title"] = title
        payload["content"] = {"media": media}
        return payload

    def build_article_payload(self, *, text, visibility, url, title=None, description=None, thumbnail=None):
        payload = self.build_text_payload(text=text, visibility=visibility)
        payload["content"] = {"article": {"source": url}}
        if title:
            payload["content"]["article"]["title"] = title
        return payload

    def build_reshare_payload(self, *, text, visibility, parent):
        payload = self.build_text_payload(text=text, visibility=visibility)
        payload["reshareContext"] = {"parent": parent}
        return payload

    def build_update_payload(self, *, text):
        return {"patch": {"$set": {"commentary": text.strip()}}}

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

    def post_multi_image(self, *, text, visibility, media_paths, alt_texts=()):
        self.multi_image_calls.append(
            {
                "text": text,
                "visibility": visibility,
                "media_paths": media_paths,
                "alt_texts": alt_texts,
            }
        )
        return PublishResult(
            post_id="urn:li:share:multi",
            url="https://www.linkedin.com/feed/update/urn:li:share:multi/",
            created_at="2026-06-15T00:00:00Z",
            visibility=visibility,
            raw={},
        )

    def post_video(self, *, text, visibility, media_path, title=None):
        self.video_calls.append(
            {
                "text": text,
                "visibility": visibility,
                "media_path": media_path,
                "title": title,
            }
        )
        return PublishResult(
            post_id="urn:li:share:video",
            url="https://www.linkedin.com/feed/update/urn:li:share:video/",
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

    def post_article(self, *, text, visibility, url, title=None, description=None, thumbnail=None):
        self.article_calls.append(
            {
                "text": text,
                "visibility": visibility,
                "url": url,
                "title": title,
                "description": description,
                "thumbnail": thumbnail,
            }
        )
        return PublishResult(
            post_id="urn:li:share:article",
            url="https://www.linkedin.com/feed/update/urn:li:share:article/",
            created_at="2026-06-15T00:00:00Z",
            visibility=visibility,
            raw={},
        )

    def post_reshare(self, *, text, visibility, parent):
        self.reshare_calls.append({"text": text, "visibility": visibility, "parent": parent})
        return PublishResult(
            post_id="urn:li:share:reshare",
            url="https://www.linkedin.com/feed/update/urn:li:share:reshare/",
            created_at="2026-06-15T00:00:00Z",
            visibility=visibility,
            raw={},
        )

    def normalize_post_id(self, post_id):
        return self.normalize_delete_post_id(post_id)

    def update_post(self, *, post_id, text):
        self.update_calls.append({"post_id": post_id, "text": text})
        return UpdateResult(post_id="urn:li:share:789", updated_at="2026-06-15T00:00:00Z", raw={})

    def get_post(self, *, post_id, view_context):
        return GetPostResult(post_id=post_id, raw={"id": post_id, "viewContext": view_context})

    def list_posts_by_author(self, *, author_urn=None, count=10, start=0, sort_by="LAST_MODIFIED", view_context="AUTHOR"):
        author = author_urn or "urn:li:person:abc"
        return ListPostsResult(
            author_urn=author,
            elements=[{"id": "urn:li:share:1"}],
            paging={"count": count, "start": start},
            raw={"elements": [{"id": "urn:li:share:1"}]},
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
    assert plan.api == "linkedin.posts"
    assert plan.text_length == 5
    assert plan.media_count == 0
    assert plan.author_urn == "urn:li:person:abc"
    assert plan.linkedin_version == "202605"
    assert plan.payload["commentary"] == "hello"
    assert plan.to_dict()["media_paths"] == []


def test_plan_image_post_uses_dry_run_image_placeholder() -> None:
    api = _api(FakePublisher())

    plan = api.plan_image_post(text=" hello image ", media_path="~/image.png", visibility="public")

    assert plan.command == "post.media"
    assert plan.api == "linkedin.posts+images"
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


def test_plan_multi_image_post_uses_dry_run_image_placeholders() -> None:
    api = _api(FakePublisher())

    plan = api.plan_multi_image_post(
        text=" hello images ",
        media_paths=["one.png", "two.jpg"],
        alt_texts=("one", "two"),
        visibility="public",
    )

    assert plan.command == "post.multi_image"
    assert plan.api == "linkedin.posts+images"
    assert plan.text_length == 12
    assert plan.media_count == 2
    assert plan.payload["content"]["multiImage"]["images"] == [
        {"id": "urn:li:image:DRY_RUN_1", "altText": "one"},
        {"id": "urn:li:image:DRY_RUN_2", "altText": "two"},
    ]
    assert plan.media_paths == (str(Path("one.png").expanduser()), str(Path("two.jpg").expanduser()))


def test_create_multi_image_post_delegates_to_publisher() -> None:
    fake = FakePublisher()
    api = _api(fake)

    result = api.create_multi_image_post(
        text="hello",
        media_paths=["one.png", "two.jpg"],
        alt_texts=("one", "two"),
        visibility="public",
    )

    assert result.post_id == "urn:li:share:multi"
    assert fake.multi_image_calls == [
        {
            "text": "hello",
            "visibility": "public",
            "media_paths": [Path("one.png"), Path("two.jpg")],
            "alt_texts": ("one", "two"),
        }
    ]


def test_plan_video_post_uses_dry_run_video_placeholder() -> None:
    api = _api(FakePublisher())

    plan = api.plan_video_post(
        text=" hello video ",
        media_path="clip.mp4",
        visibility="public",
        title="Demo",
    )

    assert plan.command == "post.video"
    assert plan.api == "linkedin.posts+videos"
    assert plan.text_length == 11
    assert plan.media_count == 1
    assert plan.payload["content"]["media"] == {
        "id": DRY_RUN_VIDEO_URN,
        "title": "Demo",
    }
    assert plan.media_paths == (str(Path("clip.mp4").expanduser()),)


def test_create_video_post_delegates_to_publisher() -> None:
    fake = FakePublisher()
    api = _api(fake)

    result = api.create_video_post(
        text="hello",
        media_path="clip.mp4",
        visibility="public",
        title="Demo",
    )

    assert result.post_id == "urn:li:share:video"
    assert fake.video_calls == [
        {
            "text": "hello",
            "visibility": "public",
            "media_path": Path("clip.mp4"),
            "title": "Demo",
        }
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


def test_plan_article_post_returns_programmatic_payload() -> None:
    api = _api(FakePublisher())

    plan = api.plan_article_post(
        text=" article ",
        url="https://example.com/post",
        title="Example",
        visibility="public",
    )

    assert plan.command == "post.article"
    assert plan.api == "linkedin.posts"
    assert plan.text_length == 7
    assert plan.payload["content"]["article"] == {
        "source": "https://example.com/post",
        "title": "Example",
    }


def test_create_article_post_delegates_to_publisher() -> None:
    fake = FakePublisher()
    api = _api(fake)

    result = api.create_article_post(text="hello", url="https://example.com/post", visibility="public")

    assert result.post_id == "urn:li:share:article"
    assert fake.article_calls[0]["url"] == "https://example.com/post"


def test_plan_reshare_post_returns_programmatic_payload() -> None:
    api = _api(FakePublisher())

    plan = api.plan_reshare_post(text=" share ", parent="urn:li:share:1", visibility="public")

    assert plan.command == "post.reshare"
    assert plan.api == "linkedin.posts"
    assert plan.text_length == 5
    assert plan.payload["reshareContext"] == {"parent": "urn:li:share:1"}


def test_update_post_delegates_to_publisher() -> None:
    fake = FakePublisher()
    api = _api(fake)

    result = api.update_post(post_id="urn:li:share:789", text="updated")

    assert result.updated_at == "2026-06-15T00:00:00Z"
    assert fake.update_calls == [{"post_id": "urn:li:share:789", "text": "updated"}]


def test_get_and_list_posts_delegate_to_publisher() -> None:
    api = _api(FakePublisher())

    post = api.get_post(post_id="urn:li:share:1", view_context="AUTHOR")
    posts = api.list_posts_by_author(author_urn="urn:li:person:abc", count=1, start=0)

    assert post.raw["id"] == "urn:li:share:1"
    assert posts.elements == [{"id": "urn:li:share:1"}]


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
