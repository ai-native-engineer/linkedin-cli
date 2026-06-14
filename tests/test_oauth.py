from __future__ import annotations

import json

import pytest

from linkedin_cli.oauth import DEFAULT_LINKEDIN_VERSION
from linkedin_cli.oauth import OAuthConfigError
from linkedin_cli.oauth import load_oauth_config


def test_load_oauth_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "token-123")
    monkeypatch.setenv("LINKEDIN_AUTHOR_URN", "urn:li:person:abc")

    config = load_oauth_config()

    assert config.access_token == "token-123"
    assert config.author_urn == "urn:li:person:abc"
    assert config.linkedin_version == DEFAULT_LINKEDIN_VERSION
    assert config.source == "env"


def test_load_oauth_config_from_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN", raising=False)
    path = tmp_path / "oauth.json"
    path.write_text(
        json.dumps(
            {
                "access_token": "token-123",
                "author_urn": "urn:li:organization:123",
                "linkedin_version": "202605",
            }
        ),
        encoding="utf-8",
    )

    config = load_oauth_config(path)

    assert config.access_token == "token-123"
    assert config.author_urn == "urn:li:organization:123"
    assert config.linkedin_version == "202605"
    assert config.source == str(path)


def test_load_oauth_config_requires_author(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN", raising=False)
    path = tmp_path / "oauth.json"
    path.write_text(json.dumps({"access_token": "token-123"}), encoding="utf-8")

    with pytest.raises(OAuthConfigError, match="author URN"):
        load_oauth_config(path)
