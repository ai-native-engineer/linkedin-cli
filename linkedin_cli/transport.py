"""Low-level LinkedIn Voyager transport with redirect diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from linkedin_api.utils.helpers import get_list_posts_sorted_without_promoted
from linkedin_api.utils.helpers import parse_list_raw_posts
from linkedin_api.utils.helpers import parse_list_raw_urns

from .auth import AuthSession
from .config import AppConfig
from .constants import API_BASE_URL
from .constants import DEFAULT_HEADERS
from .constants import VOYAGER_API_BASE_URL
from .structmatch import find_first_key
from .structmatch import find_in_included
from .structmatch import safe_int
from .structmatch import type_matches


REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


@dataclass(frozen=True)
class RedirectDetails:
    """Normalized redirect diagnostics for a Voyager request."""

    status_code: int
    url: str
    location: str | None
    reason: str
    set_cookie: str | None = None


class LinkedInTransportError(RuntimeError):
    """Raised when the direct Voyager transport cannot complete a request."""


class LinkedInRedirectError(LinkedInTransportError):
    """Raised when LinkedIn redirects instead of returning data."""

    def __init__(self, message: str, details: RedirectDetails):
        super().__init__(message)
        self.details = details


class LinkedInTransport:
    """Browser-like transport for direct Voyager API access."""

    def __init__(self, session: AuthSession, config: AppConfig):
        self._auth_session = session
        self._config = config
        self._session = requests.Session()
        self._session.cookies.update(session.cookie_jar)
        self._session.headers.update(self._build_headers())
        if config.runtime.proxy:
            self._session.proxies.update(
                {
                    "http": config.runtime.proxy,
                    "https": config.runtime.proxy,
                }
            )

    def probe(
        self,
        resource: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Return structured diagnostics for a single request."""
        try:
            response = self._request(
                resource,
                params=params,
                headers=headers,
                allow_redirects=False,
            )
        except LinkedInRedirectError as exc:
            return {
                "ok": False,
                "status_code": exc.details.status_code,
                "url": exc.details.url,
                "location": exc.details.location,
                "reason": exc.details.reason,
                "set_cookie": exc.details.set_cookie,
            }
        except Exception as exc:  # pragma: no cover - network-dependent
            return {"ok": False, "error": str(exc)}
        if response.status_code >= 400:
            return {
                "ok": False,
                "status_code": response.status_code,
                "url": str(response.url),
                "reason": "http-error",
                "error": f"LinkedIn returned HTTP {response.status_code} for {response.url}",
            }
        return {
            "ok": True,
            "status_code": response.status_code,
            "url": str(response.url),
        }

    def probe_profile(self, public_id: str) -> dict[str, Any]:
        """Return diagnostics for the same HTML-backed profile path used by `profile`."""
        try:
            response = self._request_profile_page(public_id)
            payload = self._parse_profile_page(response.text, public_id)
        except LinkedInRedirectError as exc:
            return {
                "ok": False,
                "status_code": exc.details.status_code,
                "url": exc.details.url,
                "location": exc.details.location,
                "reason": exc.details.reason,
                "set_cookie": exc.details.set_cookie,
            }
        except Exception as exc:  # pragma: no cover - network-dependent
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "status_code": response.status_code,
            "url": str(response.url),
            "public_id": payload.get("publicIdentifier") or public_id,
        }

    def fetch_me(self) -> dict[str, Any]:
        return self._get_json("/me")

    def get_me(self) -> dict[str, Any]:
        return self.fetch_me()

    def fetch_profile(self, public_id: str) -> dict[str, Any]:
        response = self._request_profile_page(public_id)
        return self._parse_profile_page(response.text, public_id)

    def get_profile(self, public_id: str) -> dict[str, Any]:
        return self.fetch_profile(public_id)

    def fetch_feed_posts(self, count: int) -> list[dict[str, Any]]:
        payload = self._get_json(
            "/feed/updatesV2",
            params={"count": str(count), "q": "chronFeed", "start": "0"},
            headers={"accept": "application/vnd.linkedin.normalized+json+2.1"},
        )
        raw_posts = payload.get("included", [])
        posts = parse_list_raw_posts(raw_posts, API_BASE_URL)
        # Find the element-ref list wherever Voyager nests it instead of pinning the
        # fixed `data.*elements` chain, and never let one malformed ref (a bare urn
        # the vendored parser chokes on) crash the whole feed — fall back to the
        # unsorted posts, mirroring `_parse_feed_like_posts`.
        raw_urns = self._extract_element_refs(payload)
        if posts and raw_urns:
            try:
                urns = parse_list_raw_urns(raw_urns)
                sorted_posts = get_list_posts_sorted_without_promoted(urns, posts)
                if sorted_posts:
                    return sorted_posts
            except Exception:
                pass
        return posts

    def get_feed_posts(self, limit: int) -> list[dict[str, Any]]:
        return self.fetch_feed_posts(limit)

    def fetch_saved_posts(self, count: int) -> list[dict[str, Any]]:
        response = self._request_saved_posts_page()
        return self._parse_saved_posts_page(response.text, count)

    def get_saved_posts(self, limit: int) -> list[dict[str, Any]]:
        return self.fetch_saved_posts(limit)

    def _get_json(
        self,
        resource: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = self._request(resource, params=params, headers=headers, allow_redirects=False)
        if response.status_code >= 400:
            raise LinkedInTransportError(
                f"LinkedIn returned HTTP {response.status_code} for {response.url}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise LinkedInTransportError(
                f"LinkedIn returned non-JSON content for {response.url}"
            ) from exc

    def _request_profile_page(self, public_id: str) -> requests.Response:
        profile_url = f"{API_BASE_URL}/in/{public_id.strip('/')}/"
        response = self._request(
            profile_url,
            headers={
                "accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "referer": f"{API_BASE_URL}/feed/",
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "same-origin",
                "upgrade-insecure-requests": "1",
            },
            allow_redirects=False,
        )
        if response.status_code >= 400:
            raise LinkedInTransportError(
                f"LinkedIn returned HTTP {response.status_code} for {response.url}"
            )
        return response

    def _request_saved_posts_page(self) -> requests.Response:
        response = self._request(
            f"{API_BASE_URL}/my-items/saved-posts/",
            headers={
                "accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "referer": f"{API_BASE_URL}/feed/",
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "same-origin",
                "upgrade-insecure-requests": "1",
            },
            allow_redirects=False,
        )
        if response.status_code >= 400:
            raise LinkedInTransportError(
                f"LinkedIn returned HTTP {response.status_code} for {response.url}"
            )
        return response

    def _parse_profile_page(self, html: str, public_id: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        code_map = {
            tag.get("id"): tag.get_text()
            for tag in soup.find_all("code")
            if tag.get("id")
        }
        payload = self._find_profile_payload(code_map, public_id)
        included = payload.get("included", [])
        if not isinstance(included, list):
            raise LinkedInTransportError("LinkedIn profile payload returned an invalid included list.")

        entities_by_urn = {
            item.get("entityUrn"): item
            for item in included
            if isinstance(item, dict) and item.get("entityUrn")
        }
        # Anchor on the stable type tail and the `fsd_profile` URN family rather than
        # the byte-exact dash namespace, which LinkedIn versions aggressively. Prefer
        # the entry matching this public id when several profiles are embedded.
        profile = (
            find_in_included(
                included,
                lambda item: type_matches(item, ".profile.Profile")
                and item.get("publicIdentifier") == public_id,
            )
            or find_in_included(included, lambda item: type_matches(item, ".profile.Profile"))
            or find_in_included(
                included,
                lambda item: "fsd_profile" in str(item.get("entityUrn") or "")
                and bool(item.get("firstName")),
            )
        )
        if profile is None:
            raise LinkedInTransportError(
                f"LinkedIn profile page did not contain embedded profile data for {public_id}."
            )

        normalized = dict(profile)
        normalized["publicProfileUrl"] = f"{API_BASE_URL}/in/{public_id.strip('/')}/"

        geo_name = self._resolve_geo_name(profile.get("geoLocation"), entities_by_urn)
        if geo_name:
            normalized["geoLocationName"] = geo_name

        photo_url = self._extract_best_image_url(profile.get("profilePicture"))
        if photo_url:
            normalized["displayPictureUrl"] = photo_url

        return normalized

    def _parse_saved_posts_page(self, html: str, count: int) -> list[dict[str, Any]]:
        payloads = self._extract_json_payloads(html)
        posts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for payload in payloads:
            for post in self._extract_posts_from_payload(payload):
                urn = self._first_value(post, "entityUrn", "entity_urn", "urn", "id")
                url = self._first_value(post, "url", "navigationUrl", "permalink")
                key = str(urn or url or len(posts))
                if key in seen:
                    continue
                seen.add(key)
                post.setdefault("savedByViewer", True)
                posts.append(post)
                if len(posts) >= count:
                    return posts

        if not posts:
            raise LinkedInTransportError("LinkedIn saved posts page did not expose saved post data.")
        return posts[:count]

    def _extract_json_payloads(self, html: str) -> list[Any]:
        soup = BeautifulSoup(html, "lxml")
        payloads: list[Any] = []
        code_map = {
            tag.get("id"): tag.get_text()
            for tag in soup.find_all("code")
            if tag.get("id")
        }
        for text in code_map.values():
            payload = self._load_json_text(text)
            if payload is None:
                continue
            payloads.append(payload)
            if isinstance(payload, dict):
                # Follow ANY string value that points at another embedded <code>
                # block, not just the literal `body` key, so a renamed pointer still
                # resolves the hydration blob.
                for value in payload.values():
                    if isinstance(value, str) and value in code_map:
                        ref_payload = self._load_json_text(code_map[value])
                        if ref_payload is not None:
                            payloads.append(ref_payload)

        for tag in soup.find_all("script"):
            text = tag.get_text(strip=True)
            if not text:
                continue
            payload = self._load_json_text(text)
            if payload is None:
                continue
            # Include by data SHAPE (an included/data hydration blob) rather than the
            # brand word alone, so a payload moved into <script type="application/json">
            # or one that only carries urns is still picked up.
            if self._looks_like_hydration(payload) or "linkedin" in text.lower():
                payloads.append(payload)
        return payloads

    @staticmethod
    def _looks_like_hydration(payload: Any) -> bool:
        if isinstance(payload, dict):
            return any(key in payload for key in ("included", "data"))
        if isinstance(payload, list):
            return any(
                isinstance(item, dict) and any(key in item for key in ("included", "data"))
                for item in payload
            )
        return False

    def _extract_posts_from_payload(self, payload: Any) -> list[dict[str, Any]]:
        posts: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            included = payload.get("included")
            if isinstance(included, list):
                posts.extend(self._parse_feed_like_posts(payload, included))
            if self._looks_like_post(payload):
                posts.append(self._normalize_embedded_post(payload))
            for value in payload.values():
                posts.extend(self._extract_posts_from_payload(value))
        elif isinstance(payload, list):
            for item in payload:
                posts.extend(self._extract_posts_from_payload(item))
        return posts

    def _parse_feed_like_posts(self, payload: dict[str, Any], included: list[Any]) -> list[dict[str, Any]]:
        raw_posts = [item for item in included if isinstance(item, dict)]
        try:
            parsed_posts = parse_list_raw_posts(raw_posts, API_BASE_URL)
        except Exception:
            parsed_posts = []
        parsed_posts = [
            post for post in parsed_posts if isinstance(post, dict) and (post.get("url") or post.get("entityUrn"))
        ]
        raw_urns = self._extract_element_refs(payload)
        if parsed_posts and raw_urns:
            try:
                urns = parse_list_raw_urns(raw_urns)
                sorted_posts = get_list_posts_sorted_without_promoted(urns, parsed_posts)
                if sorted_posts:
                    return sorted_posts
            except Exception:
                pass
        return parsed_posts

    def _extract_element_refs(self, payload: Any) -> list[str]:
        refs: list[str] = []
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key == "*elements" and isinstance(value, list):
                    refs.extend(str(item) for item in value if isinstance(item, str))
                else:
                    refs.extend(self._extract_element_refs(value))
        elif isinstance(payload, list):
            for item in payload:
                refs.extend(self._extract_element_refs(item))
        return refs

    def _looks_like_post(self, payload: dict[str, Any]) -> bool:
        urn = self._first_value(payload, "entityUrn", "entity_urn", "urn", "id")
        url = self._first_value(payload, "url", "navigationUrl", "permalink")
        if isinstance(url, str) and "/feed/update/" in url:
            return True
        if isinstance(urn, str) and ("activity" in urn or "share" in urn):
            return any(key in payload for key in ("commentary", "content", "text", "actor", "author"))
        return False

    def _normalize_embedded_post(self, payload: dict[str, Any]) -> dict[str, Any]:
        urn = self._first_value(payload, "entityUrn", "entity_urn", "urn", "id") or ""
        url = self._first_value(payload, "url", "navigationUrl", "permalink") or ""
        if not url and isinstance(urn, str) and urn.startswith("urn:li:"):
            url = f"{API_BASE_URL}/feed/update/{urn}/"

        actor = payload.get("actor") or payload.get("author") or {}
        author_profile = self._first_value(actor, "navigationUrl", "profileUrl", "url")
        author_name = (
            self._extract_text(actor.get("name")) if isinstance(actor, dict) else ""
        ) or self._extract_text(payload.get("author_name"))
        if isinstance(actor, dict) and not author_profile:
            public_id = self._first_value(actor, "publicIdentifier", "public_id")
            if public_id:
                author_profile = f"{API_BASE_URL}/in/{str(public_id).strip('/')}/"

        return {
            "entityUrn": urn,
            "url": url,
            "commentary": self._extract_text(
                self._first_value(payload, "commentary", "content", "text", "body")
            ),
            "author_name": author_name,
            "author_profile": author_profile or "",
            "actor": actor if isinstance(actor, dict) else {},
            "createdAt": self._first_value(payload, "createdAt", "created_at", "publishedAt") or "",
            "reactionCount": self._first_value(payload, "reactionCount", "likes") or 0,
            "commentCount": self._first_value(payload, "commentCount", "comments") or 0,
            "shareCount": self._first_value(payload, "shareCount", "reposts", "shares") or 0,
            "savedByViewer": True,
        }

    def _load_json_text(self, text: str) -> Any:
        try:
            return json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return None

    def _first_value(self, payload: Any, *keys: str) -> Any:
        if not isinstance(payload, dict):
            return None
        for key in keys:
            value = payload.get(key)
            if value not in (None, "", [], {}):
                return value
        return None

    def _extract_text(self, raw: Any) -> str:
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, dict):
            for key in ("text", "string", "title", "value"):
                text = self._extract_text(raw.get(key))
                if text:
                    return text
            for value in raw.values():
                text = self._extract_text(value)
                if text:
                    return text
        if isinstance(raw, list):
            return " ".join(part for part in (self._extract_text(item) for item in raw) if part).strip()
        return str(raw).strip()

    def _find_profile_payload(self, code_map: dict[str, str], public_id: str) -> dict[str, Any]:
        resource_re = re.compile(r"identitydashprofiles", re.I)
        vanity_re = re.compile(rf"vanityName(:|%3A){re.escape(public_id)}", re.I)
        # 1) Precise path: a metadata block naming the profiles resource for this
        #    vanity. Substring/regex (not an exact token) so a versioned resource
        #    name (`...ProfilesV2`) still matches, and one regex covers both
        #    `vanityName:` and the url-encoded `vanityName%3A`.
        for code_text in code_map.values():
            if not resource_re.search(code_text) or not vanity_re.search(code_text):
                continue
            payload = self._resolve_code_body(code_map, code_text)
            if isinstance(payload, dict):
                return payload
        # 2) Shape-driven fallback: any metadata->body pair whose body actually
        #    carries a Profile-typed / fsd_profile item, regardless of the resource
        #    string. Survives a wholesale resource rename.
        for code_text in code_map.values():
            payload = self._resolve_code_body(code_map, code_text)
            if isinstance(payload, dict) and self._payload_has_profile(payload):
                return payload
        raise LinkedInTransportError(
            f"LinkedIn profile page did not expose an embedded profile payload for {public_id}."
        )

    def _resolve_code_body(self, code_map: dict[str, str], code_text: str) -> Any:
        """Parse a metadata <code> block and follow its body pointer to the sibling
        <code> block that holds the actual payload. Returns None on any miss."""
        try:
            metadata = json.loads(code_text)
        except json.JSONDecodeError:
            return None
        if not isinstance(metadata, dict):
            return None
        body_id = metadata.get("body")
        body_text = code_map.get(body_id) if isinstance(body_id, str) else None
        if not body_text:
            return None
        return self._load_json_text(body_text)

    @staticmethod
    def _payload_has_profile(payload: dict[str, Any]) -> bool:
        included = payload.get("included")
        if not isinstance(included, list):
            return False
        return (
            find_in_included(
                included,
                lambda item: type_matches(item, ".profile.Profile")
                or "fsd_profile" in str(item.get("entityUrn") or ""),
            )
            is not None
        )

    def _resolve_geo_name(
        self,
        geo_location: Any,
        entities_by_urn: dict[str, dict[str, Any]],
    ) -> str:
        geo_urn = self._geo_pointer(geo_location)
        if not geo_urn:
            return ""
        geo = entities_by_urn.get(geo_urn) or self._entity_by_urn_suffix(geo_urn, entities_by_urn)
        if not isinstance(geo, dict):
            return ""
        return (
            geo.get("defaultLocalizedNameWithoutCountryName")
            or geo.get("defaultLocalizedName")
            or find_first_key(geo, "localizedName", "name", max_depth=3)
            or ""
        )

    @staticmethod
    def _geo_pointer(geo_location: Any) -> str:
        """Resolve the geo reference URN without pinning the `*geo` key — take the
        first `*`-prefixed reference value so a renamed pointer (`*geoLocation`) still
        resolves."""
        if isinstance(geo_location, str):
            return geo_location
        if isinstance(geo_location, dict):
            direct = geo_location.get("*geo")
            if isinstance(direct, str) and direct:
                return direct
            for key, value in geo_location.items():
                if isinstance(key, str) and key.startswith("*") and isinstance(value, str) and value:
                    return value
        return ""

    @staticmethod
    def _entity_by_urn_suffix(
        geo_urn: str,
        entities_by_urn: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        last_segment = geo_urn.rsplit(":", 1)[-1]
        if not last_segment:
            return None
        for urn, entity in entities_by_urn.items():
            if isinstance(urn, str) and urn.rsplit(":", 1)[-1] == last_segment:
                return entity
        return None

    def _extract_best_image_url(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""

        candidates = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                root_url = node.get("rootUrl")
                artifacts = node.get("artifacts")
                if isinstance(root_url, str) and isinstance(artifacts, list):
                    for artifact in artifacts:
                        if not isinstance(artifact, dict):
                            continue
                        segment = artifact.get("fileIdentifyingUrlPathSegment")
                        if isinstance(segment, str) and segment:
                            # safe_int so a non-numeric width ('800px') degrades to 0
                            # instead of crashing the entire profile read.
                            candidates.append((safe_int(artifact.get("width")), f"{root_url}{segment}"))
                            continue
                        direct = (
                            artifact.get("url")
                            or artifact.get("expiringUrl")
                            or artifact.get("displayImageUrl")
                        )
                        if isinstance(direct, str) and direct:
                            candidates.append((safe_int(artifact.get("width")), direct))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        if not candidates:
            return ""
        return max(candidates, key=lambda item: item[0])[1]

    def _request(
        self,
        resource: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        allow_redirects: bool = False,
    ) -> requests.Response:
        url = resource if resource.startswith("http") else f"{VOYAGER_API_BASE_URL}{resource}"
        response = self._session.get(
            url,
            params=params,
            headers=headers,
            allow_redirects=allow_redirects,
            timeout=self._config.rate_limit.timeout,
        )
        if response.status_code in REDIRECT_STATUS_CODES:
            details = RedirectDetails(
                status_code=response.status_code,
                url=str(response.url),
                location=response.headers.get("location"),
                reason=_classify_redirect(response),
                set_cookie=response.headers.get("set-cookie"),
            )
            classification = "session-rejected" if details.reason in {
                "self-redirect-loop",
                "login",
                "checkpoint",
                "authwall",
                "challenge",
            } else details.reason
            raise LinkedInRedirectError(
                f"LinkedIn redirected {classification} for {url}",
                details,
            )
        return response

    def _build_headers(self) -> dict[str, str]:
        headers = dict(DEFAULT_HEADERS)
        headers.update(
            {
                "accept-language": "en-US,en;q=0.9",
                "cache-control": "no-cache",
                "pragma": "no-cache",
                "referer": f"{API_BASE_URL}/feed/",
                "sec-ch-ua": '"Google Chrome";v="145", "Chromium";v="145", "Not.A/Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "x-li-lang": "en_US",
                "x-restli-protocol-version": "2.0.0",
                "csrf-token": self._auth_session.jsessionid,
            }
        )
        return headers


def _classify_redirect(response: requests.Response) -> str:
    location = response.headers.get("location") or ""
    if not location:
        return "empty-redirect"
    # Resolve relative `Location: /checkpoint/...` against the request URL so a
    # self-redirect or auth path is detected regardless of absolute/relative form,
    # and classify on the path alone so tokens in a query string never false-match.
    absolute = urljoin(str(response.url), location)
    if absolute == str(response.url):
        return "self-redirect-loop"
    path = urlparse(absolute).path.lower()
    if "checkpoint" in path:
        return "checkpoint"
    if "login" in path:  # also covers /uas/login
        return "login"
    if "authwall" in path:
        return "authwall"
    if "challenge" in path or "/security" in path:
        return "challenge"
    return "redirect"


LinkedInVoyagerTransport = LinkedInTransport
