from __future__ import annotations

import json

from requests import Response
from requests.cookies import RequestsCookieJar

from linkedin_cli.auth import AuthSession
from linkedin_cli.config import load_config
from linkedin_cli.transport import LinkedInVoyagerTransport
from linkedin_cli.transport import _classify_redirect


def _response(status_code: int, *, url: str, location: str | None = None, set_cookie: str = "") -> Response:
    response = Response()
    response.status_code = status_code
    response.url = url
    if location is not None:
        response.headers["location"] = location
    if set_cookie:
        response.headers["set-cookie"] = set_cookie
    return response


def _html_response(url: str, html: str) -> Response:
    response = Response()
    response.status_code = 200
    response.url = url
    response.encoding = "utf-8"
    response._content = html.encode("utf-8")
    return response


def test_classify_redirect_marks_session_rejected() -> None:
    response = _response(
        302,
        url="https://www.linkedin.com/voyager/api/feed/updatesV2",
        location="https://www.linkedin.com/voyager/api/feed/updatesV2",
        set_cookie="li_at=delete me; Domain=.linkedin.com; Path=/",
    )

    assert _classify_redirect(response) == "self-redirect-loop"


def test_classify_redirect_handles_relative_and_synonym_paths() -> None:
    base = "https://www.linkedin.com/voyager/api/feed/updatesV2"
    # relative Location resolved against the request URL
    assert _classify_redirect(_response(302, url=base, location="/checkpoint/lg/login")) == "checkpoint"
    assert _classify_redirect(_response(302, url=base, location="/uas/login")) == "login"
    assert _classify_redirect(_response(302, url=base, location="/security/challenge")) == "challenge"
    # tokens that only appear in a query string must not false-match the path
    assert _classify_redirect(_response(302, url=base, location="/feed/?from=login")) == "redirect"


def _transport() -> LinkedInVoyagerTransport:
    config = load_config()
    jar = RequestsCookieJar()
    jar.set("JSESSIONID", '"ajax:123"', domain=".linkedin.com", path="/")
    return LinkedInVoyagerTransport(AuthSession(cookie_jar=jar, source="env"), config)


def test_extract_best_image_url_tolerates_non_numeric_width() -> None:
    transport = _transport()
    picture = {
        "vectorImage": {
            "rootUrl": "https://media.licdn.com/",
            "artifacts": [
                {"width": "100px", "fileIdentifyingUrlPathSegment": "small.jpg"},
                {"width": "400px", "fileIdentifyingUrlPathSegment": "large.jpg"},
            ],
        }
    }

    # A non-numeric width must degrade to a 0-width candidate, never raise.
    assert transport._extract_best_image_url(picture) == "https://media.licdn.com/large.jpg"


def test_resolve_geo_name_tolerates_renamed_geo_pointer() -> None:
    transport = _transport()
    entities = {
        "urn:li:fsd_geo:1": {
            "entityUrn": "urn:li:fsd_geo:1",
            "defaultLocalizedNameWithoutCountryName": "Seoul",
        }
    }

    # A renamed reference pointer (`*geoLocation` instead of `*geo`) still resolves.
    assert transport._resolve_geo_name({"*geoLocation": "urn:li:fsd_geo:1"}, entities) == "Seoul"
    # And a URN-namespace shift falls back to a last-segment match.
    assert transport._resolve_geo_name({"*geo": "urn:li:geo:1"}, entities) == "Seoul"


def test_fetch_feed_posts_falls_back_when_sorting_raises(monkeypatch) -> None:
    transport = _transport()
    payload = {
        "included": [
            {
                "entityUrn": "urn:li:activity:1",
                "url": "https://www.linkedin.com/feed/update/urn:li:activity:1/",
            }
        ],
        "data": {"*elements": ["urn:li:activity:1"]},
    }
    monkeypatch.setattr(transport, "_get_json", lambda *a, **k: payload)
    monkeypatch.setattr(
        "linkedin_cli.transport.parse_list_raw_posts",
        lambda raw, base: [{"entityUrn": "urn:li:activity:1", "url": "u"}],
    )

    def boom(_refs):
        raise IndexError("malformed ref")

    monkeypatch.setattr("linkedin_cli.transport.parse_list_raw_urns", boom)

    # One malformed ref must not crash the feed; fall back to the unsorted posts.
    posts = transport.fetch_feed_posts(10)
    assert posts == [{"entityUrn": "urn:li:activity:1", "url": "u"}]


def test_fetch_profile_matches_renamed_dash_namespace(monkeypatch) -> None:
    transport = _transport()
    body = {
        "data": {"data": {}},
        "included": [
            {
                "$type": "com.linkedin.voyager.dash.identity.profileV2.Profile",
                "entityUrn": "urn:li:fsd_profile:123",
                "publicIdentifier": "jane-doe",
                "firstName": "Jane",
                "lastName": "Doe",
            }
        ],
    }
    html = (
        "<html><body>"
        '<code id="datalet-bpr-guid-1">'
        + json.dumps(
            {
                "request": (
                    "/voyager/api/graphql?variables=(vanityName:jane-doe)"
                    "&queryId=voyagerIdentityDashProfiles.hash"
                ),
                "body": "bpr-guid-1",
            }
        )
        + "</code>"
        + '<code id="bpr-guid-1">'
        + json.dumps(body)
        + "</code>"
        + "</body></html>"
    )
    monkeypatch.setattr(
        transport,
        "_request_profile_page",
        lambda public_id: _html_response("https://www.linkedin.com/in/jane-doe/", html),
    )

    # A versioned `profileV2` namespace still resolves via the fsd_profile predicate.
    payload = transport.fetch_profile("jane-doe")
    assert payload["firstName"] == "Jane"
    assert payload["publicIdentifier"] == "jane-doe"


def test_fetch_profile_falls_back_when_resource_string_renamed(monkeypatch) -> None:
    transport = _transport()
    body = {
        "included": [
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
                "entityUrn": "urn:li:fsd_profile:777",
                "publicIdentifier": "jane-doe",
                "firstName": "Jane",
                "lastName": "Doe",
            }
        ]
    }
    # The metadata block names a different resource (no `identitydashprofiles`),
    # so only the data-shape fallback can locate the profile body.
    html = (
        "<html><body>"
        '<code id="meta-1">'
        + json.dumps({"request": "/voyager/api/graphql?queryId=someOtherResource.hash", "body": "body-1"})
        + "</code>"
        + '<code id="body-1">'
        + json.dumps(body)
        + "</code>"
        + "</body></html>"
    )
    monkeypatch.setattr(
        transport,
        "_request_profile_page",
        lambda public_id: _html_response("https://www.linkedin.com/in/jane-doe/", html),
    )

    payload = transport.fetch_profile("jane-doe")
    assert payload["firstName"] == "Jane"
    assert payload["publicIdentifier"] == "jane-doe"


def test_fetch_saved_posts_reads_script_application_json(monkeypatch) -> None:
    transport = _transport()
    body = {
        "included": [
            {
                "entityUrn": "urn:li:activity:888",
                "url": "https://www.linkedin.com/feed/update/urn:li:activity:888/",
                "commentary": {"text": "Saved via script tag"},
                "actor": {
                    "name": {"text": "Jane Doe"},
                    "navigationUrl": "https://www.linkedin.com/in/jane-doe/",
                },
            }
        ]
    }
    # Hydration blob lives in <script type="application/json">, not <code id>.
    html = (
        "<html><body>"
        '<script type="application/json">'
        + json.dumps(body)
        + "</script>"
        + "</body></html>"
    )
    monkeypatch.setattr(
        transport,
        "_request_saved_posts_page",
        lambda: _html_response("https://www.linkedin.com/my-items/saved-posts/", html),
    )

    posts = transport.fetch_saved_posts(10)
    assert any(post.get("entityUrn") == "urn:li:activity:888" for post in posts)


def test_build_headers_includes_csrf_token() -> None:
    config = load_config()
    jar = RequestsCookieJar()
    jar.set("JSESSIONID", '"ajax:123"', domain=".linkedin.com", path="/")
    session = AuthSession(cookie_jar=jar, source="env")
    transport = LinkedInVoyagerTransport(session, config)

    headers = transport._build_headers()

    assert headers["csrf-token"] == "ajax:123"
    assert headers["x-restli-protocol-version"] == "2.0.0"
    assert "cookie" not in headers


def test_probe_marks_http_errors_unhealthy(monkeypatch) -> None:
    config = load_config()
    jar = RequestsCookieJar()
    jar.set("JSESSIONID", '"ajax:123"', domain=".linkedin.com", path="/")
    session = AuthSession(cookie_jar=jar, source="env")
    transport = LinkedInVoyagerTransport(session, config)
    calls = {}

    def fake_request(resource, *, params=None, headers=None, allow_redirects=False):
        calls["resource"] = resource
        calls["params"] = params
        calls["headers"] = headers
        calls["allow_redirects"] = allow_redirects
        return _response(410, url="https://www.linkedin.com/voyager/api/identity/profiles/jane-doe/profileView")

    monkeypatch.setattr(transport, "_request", fake_request)

    result = transport.probe(
        "/identity/profiles/jane-doe/profileView",
        headers={"accept": "application/vnd.linkedin.normalized+json+2.1"},
    )

    assert result["ok"] is False
    assert result["status_code"] == 410
    assert result["reason"] == "http-error"
    assert calls["headers"] == {"accept": "application/vnd.linkedin.normalized+json+2.1"}


def test_fetch_profile_parses_embedded_profile_payload(monkeypatch) -> None:
    config = load_config()
    jar = RequestsCookieJar()
    jar.set("JSESSIONID", '"ajax:123"', domain=".linkedin.com", path="/")
    session = AuthSession(cookie_jar=jar, source="env")
    transport = LinkedInVoyagerTransport(session, config)
    body = {
        "data": {"data": {"identityDashProfilesByMemberIdentity": {"*elements": ["urn:li:fsd_profile:123"]}}},
        "included": [
            {
                "$type": "com.linkedin.voyager.dash.common.Geo",
                "entityUrn": "urn:li:fsd_geo:1",
                "defaultLocalizedNameWithoutCountryName": "Buenos Aires",
                "defaultLocalizedName": "Buenos Aires, Argentina",
            },
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
                "entityUrn": "urn:li:fsd_profile:123",
                "publicIdentifier": "jane-doe",
                "firstName": "Jane",
                "lastName": "Doe",
                "headline": "Builder",
                "premium": True,
                "creator": False,
                "geoLocation": {"*geo": "urn:li:fsd_geo:1"},
                "profilePicture": {
                    "displayImageReferenceResolutionResult": {
                        "vectorImage": {
                            "rootUrl": "https://media.licdn.com/dms/image/v2/",
                            "artifacts": [
                                {"width": 100, "fileIdentifyingUrlPathSegment": "small.jpg"},
                                {"width": 400, "fileIdentifyingUrlPathSegment": "large.jpg"},
                            ],
                        }
                    }
                },
            },
        ],
    }
    html = (
        "<html><body>"
        '<code id="datalet-bpr-guid-1">'
        + json.dumps(
            {
                "request": (
                    "/voyager/api/graphql?includeWebMetadata=true&variables="
                    "(vanityName:jane-doe)&queryId=voyagerIdentityDashProfiles.hash"
                ),
                "status": 200,
                "body": "bpr-guid-1",
                "method": "GET",
            }
        )
        + "</code>"
        + '<code id="bpr-guid-1">'
        + json.dumps(body)
        + "</code>"
        + "</body></html>"
    )

    monkeypatch.setattr(
        transport,
        "_request_profile_page",
        lambda public_id: _html_response("https://www.linkedin.com/in/jane-doe/", html),
    )

    payload = transport.fetch_profile("jane-doe")

    assert payload["publicIdentifier"] == "jane-doe"
    assert payload["firstName"] == "Jane"
    assert payload["lastName"] == "Doe"
    assert payload["geoLocationName"] == "Buenos Aires"
    assert payload["publicProfileUrl"] == "https://www.linkedin.com/in/jane-doe/"
    assert payload["displayPictureUrl"] == "https://media.licdn.com/dms/image/v2/large.jpg"


def test_normalize_embedded_post_builds_url_for_share_urn() -> None:
    config = load_config()
    jar = RequestsCookieJar()
    jar.set("JSESSIONID", '"ajax:123"', domain=".linkedin.com", path="/")
    session = AuthSession(cookie_jar=jar, source="env")
    transport = LinkedInVoyagerTransport(session, config)

    post = transport._normalize_embedded_post(
        {
            "entityUrn": "urn:li:share:777",
            "commentary": "Shared body",
            "author": {"name": {"text": "Jane Doe"}},
        }
    )

    assert post["url"] == "https://www.linkedin.com/feed/update/urn:li:share:777/"

    activity_post = transport._normalize_embedded_post(
        {"entityUrn": "urn:li:activity:999", "commentary": "Body"}
    )

    assert activity_post["url"] == "https://www.linkedin.com/feed/update/urn:li:activity:999/"


def test_fetch_saved_posts_parses_embedded_saved_payload(monkeypatch) -> None:
    config = load_config()
    jar = RequestsCookieJar()
    jar.set("JSESSIONID", '"ajax:123"', domain=".linkedin.com", path="/")
    session = AuthSession(cookie_jar=jar, source="env")
    transport = LinkedInVoyagerTransport(session, config)
    body = {
        "included": [
            {
                "entityUrn": "urn:li:activity:999",
                "url": "https://www.linkedin.com/feed/update/urn:li:activity:999/",
                "commentary": {"text": "Saved post body"},
                "actor": {
                    "name": {"text": "Jane Doe"},
                    "publicIdentifier": "jane-doe",
                    "navigationUrl": "https://www.linkedin.com/in/jane-doe/",
                },
                "createdAt": 1760000000000,
                "reactionCount": 3,
                "commentCount": 2,
                "shareCount": 1,
            }
        ]
    }
    html = (
        "<html><body>"
        '<code id="datalet-bpr-guid-1">'
        + json.dumps({"body": "bpr-guid-1"})
        + "</code>"
        + '<code id="bpr-guid-1">'
        + json.dumps(body)
        + "</code>"
        + "</body></html>"
    )

    monkeypatch.setattr(
        transport,
        "_request_saved_posts_page",
        lambda: _html_response("https://www.linkedin.com/my-items/saved-posts/", html),
    )

    posts = transport.fetch_saved_posts(10)

    assert posts == [
        {
            "entityUrn": "urn:li:activity:999",
            "url": "https://www.linkedin.com/feed/update/urn:li:activity:999/",
            "commentary": "Saved post body",
            "author_name": "Jane Doe",
            "author_profile": "https://www.linkedin.com/in/jane-doe/",
            "actor": {
                "name": {"text": "Jane Doe"},
                "publicIdentifier": "jane-doe",
                "navigationUrl": "https://www.linkedin.com/in/jane-doe/",
            },
            "createdAt": 1760000000000,
            "reactionCount": 3,
            "commentCount": 2,
            "shareCount": 1,
            "savedByViewer": True,
        }
    ]
