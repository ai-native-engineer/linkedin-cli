from __future__ import annotations

from dataclasses import dataclass
import json

from click.testing import CliRunner

from linkedin_cli.auth import AuthenticationError
from linkedin_cli.cli import cli
from linkedin_cli.models import Actor
from linkedin_cli.models import Comment
from linkedin_cli.models import Post
from linkedin_cli.models import Profile
from linkedin_cli.models import ReactionSummary
from linkedin_cli.models import SearchResult
from linkedin_cli.oauth import OAuthConfig
from linkedin_cli.oauth_flow import OAuthLoginResult
from linkedin_cli.publisher import CommentListResult
from linkedin_cli.publisher import CommentResult
from linkedin_cli.publisher import DeleteResult
from linkedin_cli.publisher import GetPostResult
from linkedin_cli.publisher import ListPostsResult
from linkedin_cli.publisher import OrganizationShareStatisticsResult
from linkedin_cli.publisher import PublishResult
from linkedin_cli.publisher import ReactionResult
from linkedin_cli.publisher import SocialActionResult
from linkedin_cli.publisher import SocialMetadataResult
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

    def get_comments(self, identifier, limit=None):
        return [
            Comment(
                urn="urn:li:comment:1",
                post_urn=identifier,
                author=Actor(name="Commenter", public_id="commenter"),
                text="Nice post",
                reactions=ReactionSummary(like=2),
                replies_count=1,
            )
        ]

    def get_reactions(self, identifier, limit=None):
        return [
            {
                "reactionType": "LIKE",
                "actor": {
                    "entityUrn": "urn:li:person:abc",
                    "name": {"text": "Jane Doe"},
                    "publicIdentifier": "jane-doe",
                    "navigationUrl": "https://www.linkedin.com/in/jane-doe/",
                },
            }
        ]

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


def test_read_feed_cursor_paginates_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class PaginationClient(FakeClient):
        def feed(self, limit=None):
            posts = [
                Post(urn=f"urn:li:activity:{index}", author=Actor(name="Jane Doe"), text=f"Post {index}")
                for index in range(1, 5)
            ]
            return posts[: limit or len(posts)]

    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: PaginationClient())

    first = runner.invoke(cli, ["read", "feed", "--limit", "2", "--json"])
    first_payload = json.loads(first.output)
    cursor = first_payload["data"]["paging"]["next_cursor"]
    second = runner.invoke(cli, ["read", "feed", "--limit", "2", "--cursor", cursor, "--json"])
    second_payload = json.loads(second.output)

    assert first.exit_code == 0
    assert first_payload["data"]["posts"][0]["id"] == "urn:li:activity:1"
    assert first_payload["data"]["paging"]["has_more"] is True
    assert cursor
    assert second.exit_code == 0
    assert second_payload["request"]["cursor"] == cursor
    assert second_payload["data"]["posts"][0]["id"] == "urn:li:activity:3"
    assert second_payload["data"]["paging"]["has_more"] is False


def test_read_feed_invalid_cursor_json_contract(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["read", "feed", "--limit", "2", "--cursor", "not-a-cursor", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["command"] == "read.feed"
    assert payload["error"]["code"] == "invalid_request"


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


def test_read_comments_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["read", "comments", "urn:li:activity:123456", "--limit", "5", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "read.comments"
    assert payload["source"] == "unofficial"
    assert payload["request"] == {
        "identifier": "urn:li:activity:123456",
        "limit": 5,
        "cursor": None,
        "dry_run": False,
    }
    assert payload["data"]["comments"][0]["text"] == "Nice post"
    assert payload["data"]["comments"][0]["metrics"]["likes"] == 2


def test_read_reactions_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["read", "reactions", "urn:li:activity:123456", "--limit", "5", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "read.reactions"
    assert payload["source"] == "unofficial"
    assert payload["data"]["reactions"][0]["type"] == "like"
    assert payload["data"]["reactions"][0]["actor"]["id"] == "urn:li:person:abc"


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


def test_auth_status_json_contract_duplicate_cookie_names(monkeypatch) -> None:
    runner = CliRunner()
    from requests.cookies import RequestsCookieJar

    from linkedin_cli.auth import AuthSession

    jar = RequestsCookieJar()
    jar.set("li_at", "SECRETVALUE", domain=".linkedin.com", path="/")
    jar.set("JSESSIONID", '"ajax:1"', domain=".linkedin.com", path="/")
    jar.set("JSESSIONID", '"ajax:2"', domain=".www.linkedin.com", path="/")
    monkeypatch.setattr(
        "linkedin_cli.cli.resolve_auth_session",
        lambda config: AuthSession(cookie_jar=jar, source="browser", browser="chrome"),
    )

    result = runner.invoke(cli, ["auth", "status", "--json"])

    assert result.exit_code == 0
    assert "SECRETVALUE" not in result.output
    payload = json.loads(result.output)
    auth = payload["data"]["auth"]
    assert auth["state"] == "ready"
    assert auth["required_missing"] == []
    assert auth["cookie_count"] == 3
    assert auth["cookie_names"] == ["JSESSIONID", "li_at"]


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


def test_auth_cookie_file_from_stdin_writes_file_without_printing_secret(tmp_path) -> None:
    runner = CliRunner()
    cookie_path = tmp_path / "cookies.env"

    result = runner.invoke(
        cli,
        ["auth", "cookie-file", "--path", str(cookie_path), "--from-stdin"],
        input='li_at=SECRETVALUE; JSESSIONID="ajax:1"; li_theme=light\n',
    )

    assert result.exit_code == 0
    assert "SECRETVALUE" not in result.output
    assert "cookies=3" in result.output
    assert "required_missing=none" in result.output
    assert cookie_path.exists()
    assert cookie_path.stat().st_mode & 0o777 == 0o600
    assert "SECRETVALUE" in cookie_path.read_text(encoding="utf-8")


def test_auth_cookie_file_rejects_missing_required_cookie(tmp_path) -> None:
    runner = CliRunner()
    cookie_path = tmp_path / "cookies.env"

    result = runner.invoke(
        cli,
        ["auth", "cookie-file", "--path", str(cookie_path), "--from-stdin"],
        input="li_at=SECRETVALUE\n",
    )

    assert result.exit_code == 1
    assert "JSESSIONID" in result.output
    assert "SECRETVALUE" not in result.output
    assert not cookie_path.exists()


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


def test_auth_oauth_login_missing_client_id_json_contract(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    monkeypatch.delenv("LINKEDIN_CLIENT_ID", raising=False)
    monkeypatch.delenv("LINKEDIN_CLIENT_SECRET", raising=False)
    output_path = tmp_path / "oauth-login-error.json"

    result = runner.invoke(cli, ["auth", "oauth-login", "--json", "--output", str(output_path)])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert json.loads(output_path.read_text()) == payload
    assert payload["ok"] is False
    assert payload["command"] == "auth.oauth_login"
    assert payload["source"] == "official"
    assert payload["error"]["code"] == "auth_missing"


def test_auth_oauth_login_json_contract(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "client-123")
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "secret-123")
    token_path = tmp_path / "oauth.json"
    output_path = tmp_path / "oauth-login.json"

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
        [
            "auth",
            "oauth-login",
            "--oauth-file",
            str(token_path),
            "--no-open",
            "--json",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    assert "secret-123" not in result.output
    payload = json.loads(result.output)
    assert json.loads(output_path.read_text()) == payload
    assert payload["ok"] is True
    assert payload["command"] == "auth.oauth_login"
    assert payload["data"]["oauth"]["token_saved"] is True
    assert payload["data"]["oauth"]["author_urn"] == "urn:li:person:abc123"


def test_auth_permission_check_json_contract(monkeypatch) -> None:
    runner = CliRunner()
    oauth = OAuthConfig(
        access_token="token-123",
        author_urn="urn:li:person:abc",
        linkedin_version="202605",
        source="test",
    )
    monkeypatch.setattr("linkedin_cli.cli.load_oauth_config", lambda *args, **kwargs: oauth)
    monkeypatch.setattr(
        "linkedin_cli.cli._probe_userinfo",
        lambda access_token, client: {"status_code": 200, "subject_present": True},
    )
    monkeypatch.setattr(
        "linkedin_cli.cli._probe_posts_author_list",
        lambda api, author_urn: {"author_urn": author_urn, "count": 1},
    )

    result = runner.invoke(cli, ["auth", "permission-check", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "auth.permission_check"
    assert payload["source"] == "official"
    assert payload["data"]["oauth"] == {
        "source": "test",
        "author_urn": "urn:li:person:abc",
        "linkedin_version": "202605",
    }
    assert [probe["name"] for probe in payload["data"]["probes"]] == [
        "openid.userinfo",
        "posts.author_list",
    ]
    assert payload["data"]["summary"] == {"ok": True, "passed": 2, "failed": 0}


def test_auth_permission_check_post_scoped_json_contract(monkeypatch) -> None:
    runner = CliRunner()
    oauth = OAuthConfig(
        access_token="token-123",
        author_urn="urn:li:person:abc",
        linkedin_version="202605",
        source="test",
    )
    monkeypatch.setattr("linkedin_cli.cli.load_oauth_config", lambda *args, **kwargs: oauth)
    monkeypatch.setattr("linkedin_cli.cli._probe_userinfo", lambda access_token, client: {})
    monkeypatch.setattr("linkedin_cli.cli._probe_posts_author_list", lambda api, author_urn: {})
    monkeypatch.setattr("linkedin_cli.cli._probe_post_get", lambda api, post_id: {"post_id": post_id})
    monkeypatch.setattr("linkedin_cli.cli._probe_social_metadata", lambda api, post_id: {"entity": post_id})
    monkeypatch.setattr("linkedin_cli.cli._probe_comments_list", lambda api, post_id: {"count": 0})
    monkeypatch.setattr("linkedin_cli.cli._probe_reactions_list", lambda api, post_id: {"count": 0})

    result = runner.invoke(
        cli,
        ["auth", "permission-check", "--post-id", "urn:li:ugcPost:123", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["request"]["post_id"] == "urn:li:ugcPost:123"
    assert [probe["name"] for probe in payload["data"]["probes"]] == [
        "openid.userinfo",
        "posts.author_list",
        "posts.get",
        "social.metadata",
        "comments.list",
        "reactions.list",
    ]


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

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["post", "text", "--text", "hello", "--json", "--output", "post-text-error.json"])

        assert result.exit_code == 2
        payload = json.loads(result.output)
        with open("post-text-error.json", encoding="utf-8") as fp:
            file_payload = json.load(fp)
        assert file_payload == payload
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


def test_post_multi_image_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "post",
            "multi-image",
            "--text",
            "hello images",
            "--media",
            "one.png",
            "--media",
            "two.jpg",
            "--alt-text",
            "one alt",
            "--alt-text",
            "two alt",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.multi_image"
    assert payload["source"] == "official"
    assert payload["request"]["media_count"] == 2
    assert payload["request"]["alt_text_count"] == 2
    assert payload["data"]["planned"]["api"] == "linkedin.posts+images"
    assert payload["data"]["planned"]["media_count"] == 2
    assert payload["data"]["planned"]["min_media_count"] == 2
    assert payload["data"]["planned"]["max_media_count"] == 20


def test_post_multi_image_rejects_single_image_json_contract() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "post",
            "multi-image",
            "--text",
            "hello images",
            "--media",
            "one.png",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["command"] == "post.multi_image"
    assert payload["error"]["code"] == "media_invalid"
    assert payload["error"]["details"]["min_media_count"] == 2


def test_post_multi_image_rejects_alt_text_mismatch_json_contract() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "post",
            "multi-image",
            "--text",
            "hello images",
            "--media",
            "one.png",
            "--media",
            "two.jpg",
            "--alt-text",
            "one alt",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["command"] == "post.multi_image"
    assert payload["error"]["code"] == "media_invalid"
    assert payload["error"]["details"] == {"alt_text_count": 1, "media_count": 2}


def test_post_multi_image_publish_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def create_multi_image_post(self, *, text, visibility, media_paths, alt_texts):
            assert text == "hello images"
            assert visibility == "public"
            assert media_paths == ["one.png", "two.jpg"]
            assert alt_texts == ("one alt", "two alt")
            return PublishResult(
                post_id="urn:li:share:multi",
                url="https://www.linkedin.com/feed/update/urn:li:share:multi/",
                created_at="2026-06-15T00:00:00Z",
                visibility="public",
                raw={
                    "status_code": 201,
                    "request": {
                        "media": {
                            "multiImage": [
                                {"id": "urn:li:image:one"},
                                {"id": "urn:li:image:two"},
                            ]
                        }
                    },
                },
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(
        cli,
        [
            "post",
            "multi-image",
            "--text",
            "hello images",
            "--media",
            "one.png",
            "--media",
            "two.jpg",
            "--alt-text",
            "one alt",
            "--alt-text",
            "two alt",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.multi_image"
    assert payload["data"]["post"]["id"] == "urn:li:share:multi"


def test_post_video_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "post",
            "video",
            "--text",
            "hello video",
            "--video",
            "clip.mp4",
            "--title",
            "Demo",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.video"
    assert payload["source"] == "official"
    assert payload["request"]["media_count"] == 1
    assert payload["request"]["video"] == "clip.mp4"
    assert payload["data"]["planned"]["api"] == "linkedin.posts+videos"
    assert payload["data"]["planned"]["media_path"].endswith("clip.mp4")
    assert payload["data"]["planned"]["title"] == "Demo"


def test_post_video_publish_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def create_video_post(self, *, text, visibility, media_path, title):
            assert text == "hello video"
            assert visibility == "public"
            assert media_path == "clip.mp4"
            assert title == "Demo"
            return PublishResult(
                post_id="urn:li:share:video",
                url="https://www.linkedin.com/feed/update/urn:li:share:video/",
                created_at="2026-06-15T00:00:00Z",
                visibility="public",
                raw={"status_code": 201, "request": {"media": {"video": "urn:li:video:abc"}}},
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(
        cli,
        [
            "post",
            "video",
            "--text",
            "hello video",
            "--video",
            "clip.mp4",
            "--title",
            "Demo",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.video"
    assert payload["data"]["post"]["id"] == "urn:li:share:video"


def test_post_document_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "post",
            "document",
            "--text",
            "hello document",
            "--document",
            "deck.pdf",
            "--title",
            "Deck",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.document"
    assert payload["source"] == "official"
    assert payload["request"]["media_count"] == 1
    assert payload["request"]["document"] == "deck.pdf"
    assert payload["data"]["planned"]["api"] == "linkedin.posts+documents"
    assert payload["data"]["planned"]["media_path"].endswith("deck.pdf")
    assert payload["data"]["planned"]["title"] == "Deck"


def test_post_document_publish_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def create_document_post(self, *, text, visibility, media_path, title):
            assert text == "hello document"
            assert visibility == "public"
            assert media_path == "deck.pdf"
            assert title == "Deck"
            return PublishResult(
                post_id="urn:li:share:document",
                url="https://www.linkedin.com/feed/update/urn:li:share:document/",
                created_at="2026-06-15T00:00:00Z",
                visibility="public",
                raw={"status_code": 201, "request": {"media": {"document": "urn:li:document:abc"}}},
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(
        cli,
        [
            "post",
            "document",
            "--text",
            "hello document",
            "--document",
            "deck.pdf",
            "--title",
            "Deck",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.document"
    assert payload["data"]["post"]["id"] == "urn:li:share:document"


def test_post_poll_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "post",
            "poll",
            "--text",
            "please vote",
            "--question",
            "Pick one",
            "--option",
            "Red",
            "--option",
            "Blue",
            "--duration",
            "seven-days",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.poll"
    assert payload["source"] == "official"
    assert payload["request"]["option_count"] == 2
    assert payload["data"]["planned"]["api"] == "linkedin.posts+polls"
    assert payload["data"]["planned"]["duration"] == "SEVEN_DAYS"
    assert payload["data"]["planned"]["option_count"] == 2


def test_post_poll_rejects_single_option_json_contract() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "post",
            "poll",
            "--text",
            "please vote",
            "--question",
            "Pick one",
            "--option",
            "Red",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["command"] == "post.poll"
    assert payload["error"]["code"] == "invalid_request"
    assert payload["error"]["details"]["min_option_count"] == 2


def test_post_poll_publish_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def create_poll_post(self, *, text, visibility, question, options, duration):
            assert text == "please vote"
            assert visibility == "public"
            assert question == "Pick one"
            assert options == ("Red", "Blue")
            assert duration == "three-days"
            return PublishResult(
                post_id="urn:li:share:poll",
                url="https://www.linkedin.com/feed/update/urn:li:share:poll/",
                created_at="2026-06-15T00:00:00Z",
                visibility="public",
                raw={"status_code": 201, "request": {"media": {"poll": {"question": "Pick one"}}}},
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(
        cli,
        [
            "post",
            "poll",
            "--text",
            "please vote",
            "--question",
            "Pick one",
            "--option",
            "Red",
            "--option",
            "Blue",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.poll"
    assert payload["data"]["post"]["id"] == "urn:li:share:poll"


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


def test_post_quote_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["post", "quote", "123", "--text", "quoting", "--dry-run", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.quote"
    assert payload["data"]["planned"]["parent"] == "urn:li:share:123"
    assert payload["data"]["planned"]["api"] == "linkedin.posts"


def test_post_repost_returns_unsupported_contract() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["post", "repost", "123", "--dry-run", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["command"] == "post.repost"
    assert payload["error"]["code"] == "unsupported"
    assert payload["error"]["details"]["use_commands"] == ["post quote", "post reshare"]


def test_official_mutation_dry_runs_can_write_output_file(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN", raising=False)

    commands = [
        ("saved-unsave.json", ["saved", "unsave", "urn:li:activity:123456", "--dry-run", "--json"], "saved.unsave", 0),
        ("post-text.json", ["post", "text", "--text", "hello", "--dry-run", "--json"], "post.text", 0),
        ("post-reply.json", ["post", "reply", "123", "--text", "hello", "--dry-run", "--json"], "post.reply", 0),
        ("post-media.json", ["post", "media", "--text", "hello", "--media", "photo.png", "--dry-run", "--json"], "post.media", 0),
        (
            "post-multi-image.json",
            [
                "post",
                "multi-image",
                "--text",
                "hello",
                "--media",
                "one.png",
                "--media",
                "two.jpg",
                "--dry-run",
                "--json",
            ],
            "post.multi_image",
            0,
        ),
        ("post-video.json", ["post", "video", "--text", "hello", "--video", "clip.mp4", "--dry-run", "--json"], "post.video", 0),
        (
            "post-document.json",
            ["post", "document", "--text", "hello", "--document", "deck.pdf", "--dry-run", "--json"],
            "post.document",
            0,
        ),
        (
            "post-poll.json",
            [
                "post",
                "poll",
                "--text",
                "vote",
                "--question",
                "Pick",
                "--option",
                "Red",
                "--option",
                "Blue",
                "--dry-run",
                "--json",
            ],
            "post.poll",
            0,
        ),
        (
            "post-article.json",
            ["post", "article", "--text", "hello", "--url", "https://example.com/post", "--dry-run", "--json"],
            "post.article",
            0,
        ),
        ("post-reshare.json", ["post", "reshare", "123", "--text", "reshare", "--dry-run", "--json"], "post.reshare", 0),
        ("post-quote.json", ["post", "quote", "123", "--text", "quote", "--dry-run", "--json"], "post.quote", 0),
        ("post-repost.json", ["post", "repost", "123", "--dry-run", "--json"], "post.repost", 2),
        ("post-update.json", ["post", "update", "123", "--text", "updated", "--dry-run", "--json"], "post.update", 0),
        ("post-delete.json", ["post", "delete", "123", "--dry-run", "--json"], "post.delete", 0),
        (
            "comment-create.json",
            ["comment", "create", "urn:li:ugcPost:1", "--text", "hello", "--dry-run", "--json"],
            "comment.create",
            0,
        ),
        (
            "comment-update.json",
            ["comment", "update", "urn:li:ugcPost:1", "comment-1", "--text", "updated", "--dry-run", "--json"],
            "comment.update",
            0,
        ),
        (
            "comment-delete.json",
            ["comment", "delete", "urn:li:ugcPost:1", "comment-1", "--dry-run", "--json"],
            "comment.delete",
            0,
        ),
        (
            "reaction-create.json",
            ["reaction", "create", "urn:li:ugcPost:1", "--type", "celebrate", "--dry-run", "--json"],
            "reaction.create",
            0,
        ),
        (
            "reaction-delete.json",
            ["reaction", "delete", "urn:li:ugcPost:1", "--dry-run", "--json"],
            "reaction.delete",
            0,
        ),
        (
            "social-comments-state.json",
            ["social", "comments-state", "urn:li:ugcPost:1", "--state", "closed", "--dry-run", "--json"],
            "social.comments_state",
            0,
        ),
    ]

    with runner.isolated_filesystem():
        for output_file, command, expected_command, expected_exit in commands:
            result = runner.invoke(cli, [*command, "--output", output_file])

            assert result.exit_code == expected_exit
            stdout_payload = json.loads(result.output)
            with open(output_file, encoding="utf-8") as fp:
                file_payload = json.load(fp)
            assert file_payload == stdout_payload
            assert file_payload["command"] == expected_command
            assert file_payload["request"]["dry_run"] is True


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


def test_post_list_accepts_limit_alias(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def list_posts_by_author(self, **kwargs):
            assert kwargs["count"] == 3
            return ListPostsResult(
                author_urn="urn:li:person:abc",
                elements=[{"id": "urn:li:share:1"}],
                paging={"count": 3, "start": 0},
                raw={"elements": [{"id": "urn:li:share:1"}]},
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(cli, ["post", "list", "--limit", "3", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["request"]["count"] == 3
    assert payload["command"] == "post.list"


def test_post_list_writes_output_file(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def list_posts_by_author(self, **kwargs):
            return ListPostsResult(
                author_urn="urn:li:person:abc",
                elements=[{"id": "urn:li:share:1"}],
                paging={"count": kwargs["count"], "start": kwargs["start"]},
                raw={"elements": [{"id": "urn:li:share:1"}]},
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["post", "list", "--limit", "2", "--json", "--output", "posts.json"])

        assert result.exit_code == 0
        stdout_payload = json.loads(result.output)
        with open("posts.json", encoding="utf-8") as fp:
            file_payload = json.load(fp)
        assert file_payload == stdout_payload
        assert file_payload["command"] == "post.list"


def test_comment_list_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def list_comments(self, *, entity, count, start):
            assert entity == "urn:li:ugcPost:1"
            assert count == 2
            return CommentListResult(
                entity_urn=entity,
                elements=[{"id": "comment-1"}],
                paging={"count": count, "start": start},
                raw={"elements": [{"id": "comment-1"}]},
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(cli, ["comment", "list", "urn:li:ugcPost:1", "--count", "2", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "comment.list"
    assert payload["source"] == "official"
    assert payload["data"]["comments"][0]["id"] == "comment-1"


def test_comment_get_writes_output_file(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def get_comment(self, *, entity, comment_id):
            return CommentResult(entity_urn=entity, comment_id=comment_id, raw={"id": comment_id})

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["comment", "get", "urn:li:ugcPost:1", "comment-1", "--json", "--output", "comment.json"],
        )

        assert result.exit_code == 0
        stdout_payload = json.loads(result.output)
        with open("comment.json", encoding="utf-8") as fp:
            file_payload = json.load(fp)
        assert file_payload == stdout_payload
        assert file_payload["command"] == "comment.get"


def test_comment_create_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def create_comment(self, *, entity, text, actor_urn=None, parent_comment=None):
            assert entity == "urn:li:ugcPost:1"
            assert text == "hello"
            assert actor_urn is None
            assert parent_comment is None
            return CommentResult(entity_urn=entity, comment_id="comment-1", raw={"id": "comment-1"})

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(cli, ["comment", "create", "urn:li:ugcPost:1", "--text", "hello", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "comment.create"
    assert payload["request"]["text_length"] == 5
    assert payload["data"]["comment"]["id"] == "comment-1"


def test_post_reply_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["post", "reply", "123", "--text", "hello", "--dry-run", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.reply"
    assert payload["source"] == "official"
    assert payload["request"]["reply_to"] == "123"
    assert payload["request"]["dry_run"] is True
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["planned"]["reply_to"] == "urn:li:share:123"
    assert payload["data"]["planned"]["api"] == "linkedin.comments"


def test_post_reply_publish_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def create_reply_post(self, *, reply_to, text, actor_urn=None, parent_comment=None):
            assert reply_to == "urn:li:ugcPost:1"
            assert text == "hello"
            assert actor_urn is None
            assert parent_comment is None
            return CommentResult(entity_urn=reply_to, comment_id="comment-1", raw={"id": "comment-1"})

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(cli, ["post", "reply", "urn:li:ugcPost:1", "--text", "hello", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "post.reply"
    assert payload["source"] == "official"
    assert payload["data"]["dry_run"] is False
    assert payload["data"]["post"]["id"] == "comment-1"
    assert payload["data"]["post"]["reply_to"] == "urn:li:ugcPost:1"


def test_comment_get_and_update_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def get_comment(self, *, entity, comment_id):
            return CommentResult(entity_urn=entity, comment_id=comment_id, raw={"id": comment_id})

        def update_comment(self, *, entity, comment_id, text, actor_urn=None):
            assert text == "updated"
            return SocialActionResult(
                action="comment.update",
                entity_urn=entity,
                completed_at="2026-06-15T00:00:00Z",
                raw={"status_code": 204},
            )

        def delete_comment(self, *, entity, comment_id, actor_urn=None):
            return SocialActionResult(
                action="comment.delete",
                entity_urn=entity,
                completed_at="2026-06-15T00:00:00Z",
                raw={"status_code": 204},
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    get_result = runner.invoke(cli, ["comment", "get", "urn:li:ugcPost:1", "comment-1", "--json"])
    update_result = runner.invoke(
        cli,
        ["comment", "update", "urn:li:ugcPost:1", "comment-1", "--text", "updated", "--json"],
    )
    delete_result = runner.invoke(cli, ["comment", "delete", "urn:li:ugcPost:1", "comment-1", "--json"])

    assert get_result.exit_code == 0
    assert json.loads(get_result.output)["command"] == "comment.get"
    assert update_result.exit_code == 0
    update_payload = json.loads(update_result.output)
    assert update_payload["command"] == "comment.update"
    assert update_payload["data"]["action"] == "comment.update"
    assert delete_result.exit_code == 0
    delete_payload = json.loads(delete_result.output)
    assert delete_payload["command"] == "comment.delete"
    assert delete_payload["data"]["action"] == "comment.delete"


def test_comment_mutation_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    create_result = runner.invoke(
        cli,
        ["comment", "create", "urn:li:ugcPost:1", "--text", "hello", "--dry-run", "--json"],
    )
    update_result = runner.invoke(
        cli,
        ["comment", "update", "urn:li:ugcPost:1", "comment-1", "--text", "updated", "--dry-run", "--json"],
    )
    delete_result = runner.invoke(
        cli,
        ["comment", "delete", "urn:li:ugcPost:1", "comment-1", "--dry-run", "--json"],
    )

    assert create_result.exit_code == 0
    create_payload = json.loads(create_result.output)
    assert create_payload["command"] == "comment.create"
    assert create_payload["request"]["dry_run"] is True
    assert create_payload["data"]["dry_run"] is True
    assert create_payload["data"]["comment"] is None
    assert create_payload["data"]["planned"]["entity"] == "urn:li:ugcPost:1"
    assert create_payload["data"]["planned"]["text_length"] == 5
    assert create_payload["data"]["planned"]["api"] == "linkedin.comments"

    assert update_result.exit_code == 0
    update_payload = json.loads(update_result.output)
    assert update_payload["command"] == "comment.update"
    assert update_payload["data"]["dry_run"] is True
    assert update_payload["data"]["action"] == "comment.update"
    assert update_payload["data"]["planned"]["comment_id"] == "comment-1"
    assert update_payload["data"]["planned"]["api"] == "linkedin.comments.update"

    assert delete_result.exit_code == 0
    delete_payload = json.loads(delete_result.output)
    assert delete_payload["command"] == "comment.delete"
    assert delete_payload["data"]["dry_run"] is True
    assert delete_payload["data"]["action"] == "comment.delete"
    assert delete_payload["data"]["planned"]["comment_id"] == "comment-1"
    assert delete_payload["data"]["planned"]["api"] == "linkedin.comments.delete"


def test_comment_legacy_route_still_works(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["comment", "urn:li:activity:123", "hello"])

    assert result.exit_code == 0
    assert "Comment posted" in result.output


def test_reaction_commands_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def list_reactions(self, *, entity, count, start):
            return CommentListResult(
                entity_urn=entity,
                elements=[{"id": "reaction-1"}],
                paging={"count": count, "start": start},
                raw={"elements": [{"id": "reaction-1"}]},
            )

        def get_reaction(self, *, entity, actor_urn=None):
            return ReactionResult(actor_urn="urn:li:person:abc", entity_urn=entity, raw={})

        def create_reaction(self, *, entity, reaction_type, actor_urn=None):
            assert reaction_type == "celebrate"
            return ReactionResult(actor_urn="urn:li:person:abc", entity_urn=entity, raw={})

        def delete_reaction(self, *, entity, actor_urn=None):
            return SocialActionResult(
                action="reaction.delete",
                entity_urn=entity,
                completed_at="2026-06-15T00:00:00Z",
                raw={"status_code": 204},
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    list_result = runner.invoke(cli, ["reaction", "list", "urn:li:ugcPost:1", "--json"])
    get_result = runner.invoke(cli, ["reaction", "get", "urn:li:ugcPost:1", "--json"])
    create_result = runner.invoke(
        cli,
        ["reaction", "create", "urn:li:ugcPost:1", "--type", "celebrate", "--json"],
    )
    delete_result = runner.invoke(cli, ["reaction", "delete", "urn:li:ugcPost:1", "--json"])

    assert list_result.exit_code == 0
    assert json.loads(list_result.output)["command"] == "reaction.list"
    assert get_result.exit_code == 0
    assert json.loads(get_result.output)["command"] == "reaction.get"
    assert create_result.exit_code == 0
    assert json.loads(create_result.output)["command"] == "reaction.create"
    assert delete_result.exit_code == 0
    assert json.loads(delete_result.output)["command"] == "reaction.delete"


def test_reaction_mutation_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    create_result = runner.invoke(
        cli,
        ["reaction", "create", "urn:li:ugcPost:1", "--type", "celebrate", "--dry-run", "--json"],
    )
    delete_result = runner.invoke(cli, ["reaction", "delete", "urn:li:ugcPost:1", "--dry-run", "--json"])

    assert create_result.exit_code == 0
    create_payload = json.loads(create_result.output)
    assert create_payload["command"] == "reaction.create"
    assert create_payload["request"]["dry_run"] is True
    assert create_payload["data"]["dry_run"] is True
    assert create_payload["data"]["reaction"] is None
    assert create_payload["data"]["planned"]["reaction_type"] == "PRAISE"
    assert create_payload["data"]["planned"]["api"] == "linkedin.reactions"

    assert delete_result.exit_code == 0
    delete_payload = json.loads(delete_result.output)
    assert delete_payload["command"] == "reaction.delete"
    assert delete_payload["data"]["dry_run"] is True
    assert delete_payload["data"]["action"] == "reaction.delete"
    assert delete_payload["data"]["planned"]["entity"] == "urn:li:ugcPost:1"
    assert delete_payload["data"]["planned"]["api"] == "linkedin.reactions.delete"


def test_social_commands_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def get_social_metadata(self, *, entity):
            return SocialMetadataResult(entity_urn=entity, raw={"commentsState": "OPEN"})

        def update_comments_state(self, *, entity, state, actor_urn=None):
            assert state == "closed"
            return SocialMetadataResult(entity_urn=entity, raw={"commentsState": "CLOSED"})

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    metadata_result = runner.invoke(cli, ["social", "metadata", "urn:li:ugcPost:1", "--json"])
    state_result = runner.invoke(
        cli,
        ["social", "comments-state", "urn:li:ugcPost:1", "--state", "closed", "--json"],
    )

    assert metadata_result.exit_code == 0
    metadata_payload = json.loads(metadata_result.output)
    assert metadata_payload["command"] == "social.metadata"
    assert metadata_payload["data"]["social_metadata"]["raw"]["commentsState"] == "OPEN"
    assert state_result.exit_code == 0
    state_payload = json.loads(state_result.output)
    assert state_payload["command"] == "social.comments_state"
    assert state_payload["data"]["social_metadata"]["raw"]["commentsState"] == "CLOSED"


def test_social_metadata_writes_output_file(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def get_social_metadata(self, *, entity):
            return SocialMetadataResult(entity_urn=entity, raw={"commentsState": "OPEN"})

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["social", "metadata", "urn:li:ugcPost:1", "--json", "--output", "social-metadata.json"],
        )

        assert result.exit_code == 0
        stdout_payload = json.loads(result.output)
        with open("social-metadata.json", encoding="utf-8") as fp:
            file_payload = json.load(fp)
        assert file_payload == stdout_payload
        assert file_payload["command"] == "social.metadata"


def test_social_comments_state_dry_run_json_contract_output() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["social", "comments-state", "urn:li:ugcPost:1", "--state", "closed", "--dry-run", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["command"] == "social.comments_state"
    assert payload["request"]["dry_run"] is True
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["social_metadata"] is None
    assert payload["data"]["planned"]["comments_state"] == "CLOSED"
    assert payload["data"]["planned"]["api"] == "linkedin.social_metadata.update"


def test_insights_media_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def get_social_metadata(self, *, entity):
            return SocialMetadataResult(
                entity_urn=entity,
                raw={
                    "likesSummary": {"totalLikes": 3},
                    "commentsSummary": {"aggregatedTotalComments": 2},
                    "reshareCount": 1,
                },
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(cli, ["insights", "media", "urn:li:ugcPost:1", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["command"] == "insights.media"
    assert payload["source"] == "official"
    assert payload["data"]["scope"] == "media"
    assert payload["data"]["metrics"] == {"likes": 3, "comments": 2, "reposts": 1, "views": None}
    assert payload["data"]["raw"]["entity"] == "urn:li:ugcPost:1"


def test_insights_media_writes_output_file(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def get_social_metadata(self, *, entity):
            return SocialMetadataResult(entity_urn=entity, raw={"likesSummary": {"totalLikes": 3}})

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["insights", "media", "urn:li:ugcPost:1", "--json", "--output", "insights.json"])

        assert result.exit_code == 0
        stdout_payload = json.loads(result.output)
        with open("insights.json", encoding="utf-8") as fp:
            file_payload = json.load(fp)
        assert file_payload == stdout_payload
        assert file_payload["command"] == "insights.media"


def test_insights_organization_json_contract_output(monkeypatch) -> None:
    runner = CliRunner()

    class FakeWriteAPI:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def get_organization_share_statistics(
            self,
            *,
            organization,
            shares,
            ugc_posts,
            time_granularity,
            time_start,
            time_end,
        ):
            assert organization == "123"
            assert shares == ("456",)
            assert ugc_posts == ("urn:li:ugcPost:789",)
            assert time_granularity == "day"
            assert time_start == 1710000000000
            assert time_end == 1710086400000
            return OrganizationShareStatisticsResult(
                organization_urn="urn:li:organization:123",
                elements=[
                    {
                        "organizationalEntity": "urn:li:organization:123",
                        "share": "urn:li:share:456",
                        "totalShareStatistics": {
                            "likeCount": 3,
                            "commentCount": 2,
                            "shareCount": 1,
                            "impressionCount": 10,
                        },
                    }
                ],
                paging={"count": 1},
                raw={"elements": []},
            )

    monkeypatch.setattr("linkedin_cli.cli._write_api_from_options", lambda **kwargs: FakeWriteAPI())

    result = runner.invoke(
        cli,
        [
            "insights",
            "organization",
            "123",
            "--share",
            "456",
            "--ugc-post",
            "urn:li:ugcPost:789",
            "--time-granularity",
            "day",
            "--time-start",
            "1710000000000",
            "--time-end",
            "1710086400000",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["command"] == "insights.organization"
    assert payload["source"] == "official"
    assert payload["request"]["organization"] == "123"
    assert payload["data"]["scope"] == "organization"
    assert payload["data"]["organization"]["id"] == "urn:li:organization:123"
    assert payload["data"]["metrics"]["likes"] == 3
    assert payload["data"]["entries"][0]["share"] == "urn:li:share:456"


def test_insights_user_returns_unsupported_contract() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["insights", "user", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["command"] == "insights.user"
    assert payload["error"]["code"] == "unsupported"
    assert payload["error"]["details"]["use_commands"] == ["insights media", "social metadata"]


def test_insights_user_writes_unsupported_output_file() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["insights", "user", "--json", "--output", "insights-user.json"])

        assert result.exit_code == 2
        stdout_payload = json.loads(result.output)
        with open("insights-user.json", encoding="utf-8") as fp:
            file_payload = json.load(fp)
        assert file_payload == stdout_payload
        assert file_payload["command"] == "insights.user"
        assert file_payload["error"]["code"] == "unsupported"


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

    dry_run = runner.invoke(cli, ["saved", "unsave", "urn:li:activity:123456", "--dry-run", "--json"])
    assert dry_run.exit_code == 0
    dry_payload = json.loads(dry_run.output)
    assert dry_payload["command"] == "saved.unsave"
    assert dry_payload["request"] == {"identifier": "urn:li:activity:123456", "dry_run": True}
    assert dry_payload["data"]["dry_run"] is True
    assert dry_payload["data"]["action"] == "unsave"
    assert dry_payload["data"]["target"]["id"] == "urn:li:activity:123456"
    assert dry_payload["data"]["result"] is None
    assert dry_payload["data"]["planned"]["api"] == "linkedin.saved.unsave"

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


def test_profile_json_output(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())
    output_path = tmp_path / "profile.json"

    result = runner.invoke(cli, ["profile", "jane-doe", "--json", "--output", str(output_path)])

    assert result.exit_code == 0
    assert json.loads(output_path.read_text()) == json.loads(result.output)
    assert '"public_id": "jane-doe"' in result.output


def test_activity_json_output(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())
    output_path = tmp_path / "activity.json"

    result = runner.invoke(cli, ["activity", "urn:li:activity:123456", "--json", "--output", str(output_path)])

    assert result.exit_code == 0
    assert json.loads(output_path.read_text()) == json.loads(result.output)
    assert '"urn": "urn:li:activity:123456"' in result.output


def test_search_json_output(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("linkedin_cli.cli._client_from_ctx", lambda ctx: FakeClient())

    result = runner.invoke(cli, ["search", "builder", "--json"])

    assert result.exit_code == 0
    assert '"title": "Jane Doe"' in result.output


def _make_browser_session():
    from linkedin_cli.auth import AuthSession
    from requests.cookies import RequestsCookieJar

    jar = RequestsCookieJar()
    jar.set("li_at", "AAA", domain=".linkedin.com", path="/")
    jar.set("JSESSIONID", '"ajax:123"', domain=".linkedin.com", path="/")
    return AuthSession(cookie_jar=jar, source="browser", browser="firefox")


def test_auth_login_writes_private_cookie_file(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    session = _make_browser_session()
    monkeypatch.setattr("linkedin_cli.cli.try_browser_login", lambda config: (session, []))
    monkeypatch.setattr(
        "linkedin_cli.cli.collect_auth_diagnostics",
        lambda config: {
            "ok": True,
            "source": "cookie-file",
            "browser": None,
            "cookie_count": 2,
            "validation": {"ok": True},
            "probes": {},
            "hint": "",
        },
    )
    target = tmp_path / "cookies.env"

    result = runner.invoke(cli, ["auth", "login", "--path", str(target)])

    assert result.exit_code == 0, result.output
    assert target.exists()
    assert (target.stat().st_mode & 0o777) == 0o600
    # cookie values must never leak into output
    assert "AAA" not in result.output
    assert "ajax:123" not in result.output


def test_auth_login_manual_fallback_on_failure(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    attempts = [{"browser": "chrome", "error": "chrome: macOS Keychain access was denied."}]
    monkeypatch.setattr("linkedin_cli.cli.try_browser_login", lambda config: (None, attempts))
    target = tmp_path / "cookies.env"

    result = runner.invoke(cli, ["auth", "login", "--path", str(target)])

    assert result.exit_code == 1
    assert "DevTools" in result.output
    assert not target.exists()


def test_auth_login_refuses_overwrite_without_force(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    target = tmp_path / "cookies.env"
    target.write_text("existing", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "linkedin_cli.cli.try_browser_login",
        lambda config: (calls.append(1), (None, []))[1],
    )

    result = runner.invoke(cli, ["auth", "login", "--path", str(target)])

    assert result.exit_code != 0
    assert not calls  # overwrite guard fires before any extraction
    assert target.read_text(encoding="utf-8") == "existing"


def test_describe_browser_error_maps_keychain_and_hides_values() -> None:
    from linkedin_cli.auth import _describe_browser_error

    keychain = _describe_browser_error("chrome", RuntimeError("Could not access Keychain"))
    assert "chrome" in keychain
    assert "firefox" in keychain  # points to the reliable fallback
    # generic fallback uses the class name only, never the raw message body
    generic = _describe_browser_error("edge", ValueError("secret-cookie-AAA"))
    assert "secret-cookie-AAA" not in generic
    assert "ValueError" in generic


def test_normalize_jsessionid_quotes_unquoted_value() -> None:
    from linkedin_cli.auth import _normalize_jsessionid

    assert _normalize_jsessionid("ajax:123") == '"ajax:123"'
    assert _normalize_jsessionid('"ajax:123"') == '"ajax:123"'  # idempotent


def test_cookie_file_roundtrip_full_header(tmp_path) -> None:
    from linkedin_cli.auth import _read_cookie_header_file, write_cookie_header_file

    # A realistic full jar (many cookies) must round-trip to a single-line Cookie header,
    # not the whole file (comment + LINKEDIN_COOKIE_HEADER= wrapper) which breaks transport.
    header = "; ".join(
        [f"c{i}=v{i}" for i in range(40)] + ["li_at=AQED_token", 'JSESSIONID="ajax:123"']
    )
    path = tmp_path / "cookies.env"
    write_cookie_header_file(path, header)
    restored = _read_cookie_header_file(path)

    assert "\n" not in restored  # single-line, valid as a Cookie header
    assert "LINKEDIN_COOKIE_HEADER" not in restored  # not the wrapper/comment lines
    assert "li_at=AQED_token" in restored
    assert 'JSESSIONID="ajax:123"' in restored


def test_sanitize_error_redacts_cookie_values() -> None:
    from linkedin_cli.auth import _sanitize_error

    leaky = ValueError("Invalid header value b'li_at=SECRET; JSESSIONID=ajax:1'")
    out = _sanitize_error(leaky)
    assert "SECRET" not in out
    assert "li_at=" not in out
    assert "ValueError" in out
    assert _sanitize_error(RuntimeError("network timeout")) == "network timeout"


def test_write_cookie_file_keeps_existing_parent(tmp_path) -> None:
    from linkedin_cli.auth import write_cookie_header_file

    # tmp_path already exists (and may be system-owned like /tmp); writing into it must not
    # fail trying to chmod a parent directory we did not create.
    path = tmp_path / "cookies.env"
    summary = write_cookie_header_file(path, 'li_at=AAA; JSESSIONID="ajax:1"')
    assert (path.stat().st_mode & 0o777) == 0o600
    assert summary["path"] == str(path)


def test_write_cookie_file_tightens_created_parent(tmp_path) -> None:
    from linkedin_cli.auth import write_cookie_header_file

    path = tmp_path / "newdir" / "cookies.env"  # newdir is created by the writer
    write_cookie_header_file(path, 'li_at=AAA; JSESSIONID="ajax:1"')
    assert (path.parent.stat().st_mode & 0o777) == 0o700
    assert (path.stat().st_mode & 0o777) == 0o600
