from __future__ import annotations

from dataclasses import dataclass
import json

from click.testing import CliRunner

from linkedin_cli.auth import AuthenticationError
from linkedin_cli.cli import cli
from linkedin_cli.models import Actor
from linkedin_cli.models import Post
from linkedin_cli.models import Profile
from linkedin_cli.models import SearchResult
from linkedin_cli.oauth_flow import OAuthLoginResult
from linkedin_cli.publisher import DeleteResult
from linkedin_cli.publisher import GetPostResult
from linkedin_cli.publisher import ListPostsResult
from linkedin_cli.publisher import PublishResult
from linkedin_cli.publisher import UpdateResult


@dataclass
class FakeClient:
    def auth_status(self):
        return {
            "source": "env",
            "browser": None,
            "public_id": "john-doe",
            "full_name": "John Doe",
        }

    def feed(self, limit=None):
        return [
            Post(
                urn="urn:li:activity:123456",
                author=Actor(name="Jane Doe", public_id="jane-doe"),
                text="Hello feed",
                url="https://www.linkedin.com/feed/update/urn:li:activity:123456/",
            )
        ]

    def get_saved_posts(self, limit=None):
        post = self.feed(limit=limit)[0]
        post.saved_by_viewer = True
        return [post]

    def search(self, query, limit=None):
        return [
            SearchResult(
                kind="profile",
                title="Jane Doe",
                subtitle="Builder",
                snippet=f"query={query}",
                url="https://www.linkedin.com/in/jane-doe/",
                profile=Profile(
                    public_id="jane-doe",
                    full_name="Jane Doe",
                    headline="Builder",
                    profile_url="https://www.linkedin.com/in/jane-doe/",
                ),
            )
        ]

    def get_profile(self, identifier):
        return Profile(
            public_id=identifier,
            full_name="Jane Doe",
            headline="Builder",
            profile_url=f"https://www.linkedin.com/in/{identifier}/",
        )

    def get_profile_posts(self, identifier, limit=None):
        return self.feed(limit=limit)

    def get_activity(self, identifier):
        return self.feed()[0]

    def post(self, text, visibility="connections"):
        return f"posted {visibility}: {text}"

    def react(self, identifier, reaction_type):
        return f"reacted {reaction_type} -> {identifier}"

    def unreact(self, identifier):
        return f"unreacted -> {identifier}"

    def save(self, identifier):
        return f"saved -> {identifier}"

    def unsave(self, identifier):
        return f"unsaved -> {identifier}"

    def comment(self, identifier, text):
        return f"commented -> {identifier}: {text}"


def test_cli_help_renders() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "LinkedIn CLI" in result.output or "linkedin" in result.output


def test_feed_json_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["feed", "--json"])

    assert result.exit_code == 0
    assert '"text": "Hello feed"' in result.output


def test_read_feed_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["read", "feed", "--limit", "5", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "sns-json-v1"
    assert payload["ok"] is True
    assert payload["command"] == "read.feed"
    assert payload["source"] == "unofficial"
    assert payload["request"] == {"limit": 5, "cursor": None, "dry_run": False}
    assert payload["data"]["posts"][0]["text"] == "Hello feed"
    assert payload["data"]["posts"][0]["author"]["name"] == "Jane Doe"
    assert payload["data"]["paging"] == {
        "cursor": None,
        "next_cursor": None,
        "has_more": False,
    }


def test_read_saved_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["read", "saved", "--limit", "5", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "sns-json-v1"
    assert payload["ok"] is True
    assert payload["command"] == "read.saved"
    assert payload["source"] == "unofficial"
    assert payload["request"] == {"limit": 5, "cursor": None, "dry_run": False}
    assert payload["data"]["posts"][0]["id"] == "urn:li:activity:123456"
    assert payload["data"]["posts"][0]["raw"]["saved_by_viewer"] is True


def test_saved_list_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["saved", "list", "--limit", "5", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "sns-json-v1"
    assert payload["command"] == "read.saved"
    assert payload["data"]["posts"][0]["raw"]["saved_by_viewer"] is True


def test_read_profile_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["read", "profile", "jane-doe", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "sns-json-v1"
    assert payload["ok"] is True
    assert payload["command"] == "read.profile"
    assert payload["request"] == {"identifier": "jane-doe", "dry_run": False}
    assert payload["data"]["profile"]["handle"] == "jane-doe"
    assert payload["data"]["profile"]["name"] == "Jane Doe"
    assert payload["data"]["profile"]["source"] == "unofficial"


def test_read_search_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["read", "search", "builder", "--limit", "5", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "sns-json-v1"
    assert payload["ok"] is True
    assert payload["command"] == "read.search"
    assert payload["request"] == {
        "query": "builder",
        "limit": 5,
        "cursor": None,
        "dry_run": False,
    }
    assert payload["data"]["results"][0]["type"] == "profile"
    assert payload["data"]["results"][0]["title"] == "Jane Doe"


def test_read_feed_json_contract_auth_error(monkeypatch) -> None:
    runner = CliRunner()

    def raise_auth_error(ctx):
        raise AuthenticationError("No LinkedIn cookies found.")

    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", raise_auth_error)

    result = runner.invoke(cli, ["read", "feed", "--limit", "5", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["schema_version"] == "sns-json-v1"
    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "auth_missing"
    assert payload["error"]["details"] == {"auth_kind": "cookie_session"}


def test_read_feed_json_contract_cookie_conflict(monkeypatch) -> None:
    runner = CliRunner()

    def raise_cookie_conflict(ctx):
        raise RuntimeError("There are multiple cookies with name, 'JSESSIONID'")

    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", raise_cookie_conflict)

    result = runner.invoke(cli, ["read", "feed", "--limit", "5", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "auth_expired"
    assert payload["error"]["details"] == {"auth_kind": "cookie_session"}


def test_read_activity_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["read", "activity", "urn:li:activity:123456", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "read.activity"
    assert payload["source"] == "unofficial"
    assert payload["request"] == {"identifier": "urn:li:activity:123456", "dry_run": False}
    assert payload["data"]["post"]["id"] == "urn:li:activity:123456"


def test_read_profile_posts_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["read", "profile-posts", "jane-doe", "--limit", "5", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "read.profile_posts"
    assert payload["source"] == "unofficial"
    assert payload["request"] == {
        "identifier": "jane-doe",
        "limit": 5,
        "cursor": None,
        "dry_run": False,
    }
    assert payload["data"]["posts"][0]["id"] == "urn:li:activity:123456"


def test_read_feed_session_rejected_maps_to_auth_expired(monkeypatch) -> None:
    runner = CliRunner()
    from linkedin_cli.client import LinkedInClientError

    class _RejectingClient:
        def feed(self, limit=None):
            raise LinkedInClientError(
                "feed failed: LinkedIn redirected session-rejected for https://www.linkedin.com/x"
            )

    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: _RejectingClient())

    result = runner.invoke(cli, ["read", "feed", "--limit", "5", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "auth_expired"
    assert payload["error"]["retryable"] is False
    assert payload["error"]["details"] == {"auth_kind": "cookie_session"}


def test_read_profile_and_unsave_auth_errors(monkeypatch) -> None:
    runner = CliRunner()

    def raise_auth_error(ctx):
        raise AuthenticationError("No LinkedIn cookies found.")

    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", raise_auth_error)

    profile_result = runner.invoke(cli, ["read", "profile", "jane-doe", "--json"])
    assert profile_result.exit_code == 2
    profile_payload = json.loads(profile_result.output)
    assert profile_payload["command"] == "read.profile"
    assert profile_payload["error"]["code"] == "auth_missing"

    unsave_result = runner.invoke(cli, ["saved", "unsave", "urn:li:activity:1", "--json"])
    assert unsave_result.exit_code == 2
    unsave_payload = json.loads(unsave_result.output)
    assert unsave_payload["command"] == "saved.unsave"
    assert unsave_payload["error"]["code"] == "auth_missing"


def test_exit_codes_match_contract_buckets() -> None:
    from linkedin_cli.cli import _exit_code_for_error

    for code in ("auth_missing", "auth_expired", "invalid_request", "media_invalid",
                 "not_found", "permission_denied", "post_rejected", "unsupported"):
        assert _exit_code_for_error(code) == 2, code
    for code in ("rate_limited", "upstream_unavailable", "upstream_changed", "media_upload_failed"):
        assert _exit_code_for_error(code) == 3, code
    for code in ("contract_error", "internal_error", "definitely_unknown"):
        assert _exit_code_for_error(code) == 4, code


def test_classify_session_rejected_client_error() -> None:
    from linkedin_cli.cli import _classify_contract_error
    from linkedin_cli.client import LinkedInClientError

    code, retryable, details = _classify_contract_error(
        LinkedInClientError("feed failed: LinkedIn redirected session-rejected for https://x")
    )

    assert code == "auth_expired"
    assert retryable is False
    assert details == {"auth_kind": "cookie_session"}


def test_auth_status_json_contract_ready(monkeypatch) -> None:
    runner = CliRunner()
    from requests.cookies import RequestsCookieJar

    from linkedin_cli.auth import AuthSession

    jar = RequestsCookieJar()
    jar.set("li_at", "SECRETVALUE", domain=".linkedin.com", path="/")
    jar.set("JSESSIONID", '"ajax:1"', domain=".linkedin.com", path="/")
    monkeypatch.setattr(
        "linkedin_cli.cli.resolve_auth_session",
        lambda config: AuthSession(cookie_jar=jar, source="env"),
    )

    result = runner.invoke(cli, ["auth", "status", "--json"])

    assert result.exit_code == 0
    assert "SECRETVALUE" not in result.output  # cookie values never leak
    payload = json.loads(result.output)
    assert payload["command"] == "auth.status"
    assert payload["source"] == "unofficial"
    auth = payload["data"]["auth"]
    assert auth["state"] == "ready"
    assert auth["required_missing"] == []
    assert "li_at" in auth["cookie_names"]


def test_auth_status_json_contract_missing(monkeypatch) -> None:
    runner = CliRunner()

    def raise_missing(config):
        raise AuthenticationError("No LinkedIn cookies found.")

    monkeypatch.setattr("linkedin_cli.cli.resolve_auth_session", raise_missing)

    result = runner.invoke(cli, ["auth", "status", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["data"]["auth"]["state"] == "missing"
    assert payload["data"]["auth"]["cookie_count"] == 0


def test_post_text_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["post", "text", "--text", "hello", "--visibility", "public", "--dry-run", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "sns-json-v1"
    assert payload["ok"] is True
    assert payload["command"] == "post.text"
    assert payload["source"] == "official"
    assert payload["request"] == {
        "visibility": "public",
        "dry_run": True,
        "media_count": 0,
        "text_length": 5,
        "author": None,
    }
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["post"] is None
    assert payload["data"]["planned"]["api"] == "linkedin.posts"


def test_auth_oauth_login_missing_client_id_json_contract(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.delenv("LINKEDIN_CLIENT_ID", raising=False)
    monkeypatch.delenv("LINKEDIN_CLIENT_SECRET", raising=False)

    result = runner.invoke(cli, ["auth", "oauth-login", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["command"] == "auth.oauth_login"
    assert payload["source"] == "official"
    assert payload["error"]["code"] == "auth_missing"


def test_auth_oauth_login_json_contract(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "client-123")
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "secret-123")
    token_path = tmp_path / "oauth.json"

    def fake_run_oauth_login(**kwargs):
        assert kwargs["client_id"] == "client-123"
        assert kwargs["client_secret"] == "secret-123"
        assert kwargs["redirect_uri"] == "http://localhost:8787/callback"
        assert kwargs["token_path"] == token_path
        assert kwargs["open_browser"] is False
        return OAuthLoginResult(
            token_path=str(token_path),
            author_urn="urn:li:person:abc123",
            scopes=("openid", "w_member_social"),
            expires_in=5184000,
            created_at="2026-06-15T00:00:00Z",
        )

    monkeypatch.setattr("linkedin_cli.cli.run_oauth_login", fake_run_oauth_login)

    result = runner.invoke(
        cli,
        ["auth", "oauth-login", "--oauth-file", str(token_path), "--no-open", "--json"],
    )

    assert result.exit_code == 0
    assert "secret-123" not in result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "auth.oauth_login"
    assert payload["data"]["oauth"]["token_saved"] is True
    assert payload["data"]["oauth"]["author_urn"] == "urn:li:person:abc123"


def test_post_text_dry_run_reads_text_file_json_contract(tmp_path) -> None:
    runner = CliRunner()
    text_path = tmp_path / "post.md"
    text_path.write_text(" hello from file\n", encoding="utf-8")

    result = runner.invoke(
        cli,
        ["post", "text", "--text-file", str(text_path), "--dry-run", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["request"]["text_length"] == 15
    assert payload["data"]["planned"]["text_length"] == 15


def test_post_text_rejects_ambiguous_text_inputs_json_contract(tmp_path) -> None:
    runner = CliRunner()
    text_path = tmp_path / "post.md"
    text_path.write_text("hello", encoding="utf-8")

    result = runner.invoke(
        cli,
        ["post", "text", "--text", "hello", "--text-file", str(text_path), "--json"],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["command"] == "post.text"
    assert payload["error"]["code"] == "invalid_request"
    assert payload["request"]["text_length"] is None


def test_post_text_without_oauth_returns_contract_error(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("LINKEDIN_OAUTH_FILE", str(tmp_path / "missing-oauth.json"))

    result = runner.invoke(cli, ["post", "text", "--text", "hello", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["command"] == "post.text"
    assert payload["source"] == "official"
    assert payload["error"]["code"] == "auth_missing"
    assert payload["error"]["details"] == {"auth_kind": "oauth"}


def test_post_text_publish_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def create_text_post(self, *, text, visibility):
            assert text == "hello"
            assert visibility == "public"
            return PublishResult(
                post_id="urn:li:share:123",
                url="https://www.linkedin.com/feed/update/urn:li:share:123/",
                created_at="2026-06-12T00:00:00Z",
                visibility="public",
                raw={"status_code": 201, "headers": {"x-restli-id": "urn:li:share:123"}},
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(cli, ["post", "text", "--text", "hello", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.text"
    assert payload["source"] == "official"
    assert payload["data"]["dry_run"] is False
    assert payload["data"]["post"]["id"] == "urn:li:share:123"
    assert payload["data"]["post"]["source"] == "official"
    assert payload["data"]["planned"] is None


def test_post_media_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "post",
            "media",
            "--text",
            "hello",
            "--media",
            "photo.png",
            "--visibility",
            "public",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "sns-json-v1"
    assert payload["ok"] is True
    assert payload["command"] == "post.media"
    assert payload["source"] == "official"
    assert payload["request"] == {
        "visibility": "public",
        "dry_run": True,
        "media_count": 1,
        "text_length": 5,
        "author": None,
    }
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["planned"]["api"] == "linkedin.posts+images"


def test_post_media_dry_run_reads_stdin_json_contract() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "post",
            "media",
            "--text-file",
            "-",
            "--media",
            "photo.png",
            "--dry-run",
            "--json",
        ],
        input="hello stdin\n",
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["request"]["text_length"] == 11
    assert payload["data"]["planned"]["text_length"] == 11
    assert payload["data"]["planned"]["media_count"] == 1


def test_post_media_rejects_multiple_media_json_contract() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "post",
            "media",
            "--text",
            "hello",
            "--media",
            "one.png",
            "--media",
            "two.png",
            "--json",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["command"] == "post.media"
    assert payload["error"]["code"] == "media_invalid"
    assert payload["error"]["details"] == {"media_count": 2}


def test_post_media_publish_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def create_image_post(self, *, text, visibility, media_path):
            assert text == "hello"
            assert visibility == "public"
            assert str(media_path) == "photo.png"
            return PublishResult(
                post_id="urn:li:share:456",
                url="https://www.linkedin.com/feed/update/urn:li:share:456/",
                created_at="2026-06-12T00:00:00Z",
                visibility="public",
                raw={
                    "status_code": 201,
                    "headers": {"x-restli-id": "urn:li:share:456"},
                    "request": {"media": {"image": "urn:li:image:abc"}},
                },
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(
        cli,
        ["post", "media", "--text", "hello", "--media", "photo.png", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.media"
    assert payload["source"] == "official"
    assert payload["data"]["post"]["id"] == "urn:li:share:456"
    assert payload["data"]["post"]["raw"]["request"]["media"] == {"image": "urn:li:image:abc"}


def test_post_article_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "post",
            "article",
            "--text",
            "hello article",
            "--url",
            "https://example.com/post",
            "--title",
            "Example",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.article"
    assert payload["source"] == "official"
    assert payload["data"]["planned"]["api"] == "linkedin.posts"
    assert payload["data"]["planned"]["url"] == "https://example.com/post"


def test_post_article_publish_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def create_article_post(self, **kwargs):
            assert kwargs["url"] == "https://example.com/post"
            return PublishResult(
                post_id="urn:li:share:article",
                url="https://www.linkedin.com/feed/update/urn:li:share:article/",
                created_at="2026-06-15T00:00:00Z",
                visibility="public",
                raw={"request": {"api": "linkedin.posts"}},
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(
        cli,
        [
            "post",
            "article",
            "--text",
            "hello article",
            "--url",
            "https://example.com/post",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.article"
    assert payload["data"]["post"]["id"] == "urn:li:share:article"


def test_post_reshare_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["post", "reshare", "123", "--text", "resharing", "--dry-run", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.reshare"
    assert payload["data"]["planned"]["parent"] == "urn:li:share:123"


def test_post_update_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["post", "update", "123", "--text", "updated", "--dry-run", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.update"
    assert payload["data"]["planned"] == {
        "id": "urn:li:share:123",
        "text_length": 7,
        "api": "linkedin.posts.update",
    }


def test_post_update_publish_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def update_post(self, *, post_id, text):
            assert post_id == "urn:li:share:789"
            assert text == "updated"
            return UpdateResult(
                post_id="urn:li:share:789",
                updated_at="2026-06-15T00:00:00Z",
                raw={"status_code": 204},
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(cli, ["post", "update", "urn:li:share:789", "--text", "updated", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.update"
    assert payload["data"]["post"]["updated"] is True


def test_post_get_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def get_post(self, *, post_id, view_context):
            assert view_context == "AUTHOR"
            return GetPostResult(post_id=post_id, raw={"id": post_id, "commentary": "hello"})

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(cli, ["post", "get", "urn:li:share:789", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.get"
    assert payload["data"]["post"]["raw"]["commentary"] == "hello"


def test_post_list_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def list_posts_by_author(self, **kwargs):
            assert kwargs["count"] == 2
            return ListPostsResult(
                author_urn="urn:li:person:abc",
                elements=[{"id": "urn:li:share:1"}],
                paging={"count": 2, "start": 0},
                raw={"elements": [{"id": "urn:li:share:1"}]},
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(cli, ["post", "list", "--count", "2", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.list"
    assert payload["data"]["posts"][0]["id"] == "urn:li:share:1"


def test_post_delete_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["post", "delete", "https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A789/", "--dry-run", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "sns-json-v1"
    assert payload["ok"] is True
    assert payload["command"] == "post.delete"
    assert payload["source"] == "official"
    assert payload["request"] == {
        "id": "https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A789/",
        "dry_run": True,
        "author": None,
    }
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["post"] is None
    assert payload["data"]["planned"] == {
        "id": "urn:li:share:789",
        "api": "linkedin.posts.delete",
    }


def test_post_delete_publish_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def delete_post(self, *, post_id):
            assert post_id == "urn:li:share:789"
            return DeleteResult(
                post_id="urn:li:share:789",
                deleted_at="2026-06-15T00:00:00Z",
                raw={
                    "status_code": 204,
                    "request": {
                        "api": "linkedin.posts.delete",
                        "post_id": "urn:li:share:789",
                    },
                },
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(cli, ["post", "delete", "urn:li:share:789", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.delete"
    assert payload["source"] == "official"
    assert payload["data"]["dry_run"] is False
    assert payload["data"]["post"]["id"] == "urn:li:share:789"
    assert payload["data"]["post"]["deleted"] is True
    assert payload["data"]["post"]["source"] == "official"
    assert payload["data"]["planned"] is None


def test_post_delete_rejects_activity_urn_json_contract() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["post", "delete", "urn:li:activity:789", "--dry-run", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["command"] == "post.delete"
    assert payload["source"] == "official"
    assert payload["error"]["code"] == "invalid_request"


def test_saved_unsave_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["saved", "unsave", "urn:li:activity:123456", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "sns-json-v1"
    assert payload["ok"] is True
    assert payload["command"] == "saved.unsave"
    assert payload["source"] == "unofficial"
    assert payload["request"] == {"identifier": "urn:li:activity:123456", "dry_run": False}
    assert payload["data"]["action"] == "unsave"
    assert payload["data"]["target"]["id"] == "urn:li:activity:123456"
    assert "unsaved" in payload["data"]["result"]["detail"]


def test_auth_status_includes_probe_summary(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(
        "linkedin_cli.cli.collect_auth_diagnostics",
        lambda config: {
            "ok": False,
            "source": "env",
            "public_id": "jane-doe",
            "cookie_count": 7,
            "validation": {
                "ok": False,
                "kind": "self-redirect-loop",
                "status_code": 302,
                "location": "https://www.linkedin.com/voyager/api/me",
            },
            "probes": {
                "voyager_me": {"ok": False, "reason": "self-redirect-loop", "status_code": 302},
                "voyager_feed": {"ok": False, "reason": "redirect", "status_code": 302},
            },
            "hint": "Need a fuller cookie jar.",
        },
    )

    result = runner.invoke(cli, ["auth-status"])

    assert result.exit_code == 1
    assert "cookies=7" in result.output
    assert "basic-probe=self-redirect-loop:302" in result.output
    assert "voyager_feed=redirect:302" in result.output
    assert "Need a fuller cookie jar." in result.output


def test_auth_status_success(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(
        "linkedin_cli.cli.collect_auth_diagnostics",
        lambda config: {
            "ok": True,
            "source": "browser",
            "browser": "chrome",
            "public_id": "jane-doe",
            "cookie_count": 9,
            "validation": {"ok": True, "kind": "profile-read"},
            "probes": {
                "voyager_me": {"ok": True, "status_code": 200},
                "voyager_feed": {"ok": True, "status_code": 200},
            },
            "hint": "",
        },
    )

    result = runner.invoke(cli, ["auth-status"])

    assert result.exit_code == 0
    assert "source=browser" in result.output
    assert "basic-probe=ok" in result.output
    assert "voyager_feed=ok:200" in result.output


def test_profile_json_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["profile", "jane-doe", "--json"])

    assert result.exit_code == 0
    assert '"public_id": "jane-doe"' in result.output


def test_search_json_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["search", "builder", "--json"])

    assert result.exit_code == 0
    assert '"title": "Jane Doe"' in result.output
