from __future__ import annotations

from requests import exceptions as requests_exceptions

from linkedin_cli.client import LinkedInClient
from linkedin_cli.client import LinkedInClientError
from linkedin_cli.config import load_config
from linkedin_cli.transport import LinkedInTransportError


class _Session:
    cookie_count = 2
    source = "env"
    browser = None


def test_retry_turns_redirect_loop_into_actionable_error(monkeypatch) -> None:
    client = object.__new__(LinkedInClient)
    client.config = load_config()
    client.session = _Session()
    client._auth_payload = {
        "firstName": "Jane",
        "lastName": "Doe",
        "miniProfile": {"publicIdentifier": "jane-doe"},
    }

    monkeypatch.setattr(
        "linkedin_cli.client.probe_read_access",
        lambda session, config, public_id=None: {
            "voyager_feed": {"ok": False, "status_code": 302},
        },
    )
    monkeypatch.setattr(
        LinkedInClient,
        "_sleep_request_delay",
        lambda self: None,
    )

    try:
        client._retry("feed", lambda: (_ for _ in ()).throw(requests_exceptions.TooManyRedirects()))
    except LinkedInClientError as exc:
        message = str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected LinkedInClientError")

    assert "redirect loop" in message
    assert "LINKEDIN_COOKIE_HEADER" in message
    assert "voyager_feed=302" in message


def test_public_id_from_url_handles_subpaths() -> None:
    client = object.__new__(LinkedInClient)

    assert client._public_id_from_url("https://www.linkedin.com/in/jane-doe/") == "jane-doe"
    assert (
        client._public_id_from_url("https://www.linkedin.com/in/jane-doe/recent-activity/all/")
        == "jane-doe"
    )
    assert client._public_id_from_url("https://www.linkedin.com/feed/") == ""


def test_normalize_activity_urn_accepts_share_and_ugcpost() -> None:
    client = object.__new__(LinkedInClient)

    assert client.normalize_activity_urn("urn:li:share:123") == "urn:li:share:123"
    assert client.normalize_activity_urn("urn:li:ugcPost:456") == "urn:li:ugcPost:456"
    assert client.normalize_activity_urn("urn:li:activity:789") == "urn:li:activity:789"
    assert client.normalize_activity_urn("999") == "urn:li:activity:999"
    assert (
        client.normalize_activity_urn("https://www.linkedin.com/feed/update/urn:li:share:123/")
        == "urn:li:share:123"
    )


def test_activity_url_preserves_urn_type() -> None:
    client = object.__new__(LinkedInClient)

    assert (
        client.activity_url("urn:li:share:123")
        == "https://www.linkedin.com/feed/update/urn:li:share:123/"
    )
    assert (
        client.activity_url("urn:li:activity:789")
        == "https://www.linkedin.com/feed/update/urn:li:activity:789/"
    )


def test_react_requires_activity_urn() -> None:
    client = object.__new__(LinkedInClient)

    try:
        client.react("urn:li:share:123", "like")
    except LinkedInClientError as exc:
        assert "activity URN" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected LinkedInClientError for a non-activity URN")


def test_get_comments_fetches_unofficial_activity_comments(monkeypatch) -> None:
    client = object.__new__(LinkedInClient)
    client.config = load_config()

    class FakeAPI:
        def get_post_comments(self, activity_id, comment_count):
            assert activity_id == "123"
            assert comment_count == 2
            return [
                {
                    "entityUrn": "urn:li:comment:1",
                    "commentary": {"text": "Nice post"},
                    "commenter": {"name": "Commenter", "publicIdentifier": "commenter"},
                }
            ]

    client.api = FakeAPI()
    monkeypatch.setattr(LinkedInClient, "_sleep_request_delay", lambda self: None)

    comments = client.get_comments("urn:li:activity:123", limit=2)

    assert comments[0].urn == "urn:li:comment:1"
    assert comments[0].text == "Nice post"
    assert comments[0].post_urn == "urn:li:activity:123"


def test_get_reactions_fetches_unofficial_activity_reactions(monkeypatch) -> None:
    client = object.__new__(LinkedInClient)
    client.config = load_config()

    class FakeAPI:
        def get_post_reactions(self, activity_urn, max_results):
            assert activity_urn == "urn:li:activity:123"
            assert max_results == 2
            return [{"reactionType": "LIKE"}, "bad"]

    client.api = FakeAPI()
    monkeypatch.setattr(LinkedInClient, "_sleep_request_delay", lambda self: None)

    reactions = client.get_reactions("urn:li:activity:123", limit=2)

    assert reactions == [{"reactionType": "LIKE"}]


def test_profile_summary_does_not_fall_back_to_headline() -> None:
    client = object.__new__(LinkedInClient)

    profile = client._normalize_profile(
        {"publicIdentifier": "jane-doe", "firstName": "Jane", "headline": "Builder"}
    )

    assert profile.headline == "Builder"
    assert profile.summary == ""


def test_saved_posts_falls_back_to_browser_when_transport_rejects_session(monkeypatch) -> None:
    client = object.__new__(LinkedInClient)
    client.config = load_config()
    client.session = _Session()

    class FakeTransport:
        def get_saved_posts(self, limit):
            raise LinkedInTransportError("LinkedIn redirected session-rejected")

    class FakeBrowser:
        def get_saved_posts(self, count):
            assert count == 3
            return [
                {
                    "entityUrn": "urn:li:activity:999",
                    "url": "https://www.linkedin.com/feed/update/urn:li:activity:999/",
                    "commentary": "Saved from browser",
                    "author_name": "Jane Doe",
                    "author_profile": "https://www.linkedin.com/in/jane-doe/",
                    "savedByViewer": True,
                }
            ]

    client.transport = FakeTransport()
    client.browser = FakeBrowser()
    monkeypatch.setattr(LinkedInClient, "_sleep_request_delay", lambda self: None)

    posts = client.get_saved_posts(limit=3)

    assert len(posts) == 1
    assert posts[0].urn == "urn:li:activity:999"
    assert posts[0].author.name == "Jane Doe"
    assert posts[0].saved_by_viewer is True
