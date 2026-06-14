<h1 align="center">linkedin-cli</h1>

<p align="center">A LinkedIn CLI for AI agents — unofficial reads and official OAuth publishing, cleanly separated</p>

<p align="center">
  <a href="https://pypi.org/project/agent-linkedin/"><img src="https://img.shields.io/pypi/v/agent-linkedin.svg" alt="PyPI"></a>
  <a href="https://github.com/ai-native-engineer/linkedin-cli/actions/workflows/ci.yml"><img src="https://github.com/ai-native-engineer/linkedin-cli/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="license"></a>
  <img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="python">
</p>

<p align="center"><a href="./README.md">한국어</a> · <b>English</b></p>

---

`linkedin-cli` separates two surfaces clearly:

- `read.*`: unofficial read workflows that use your own authenticated LinkedIn web session.
- `post.*`: official write workflows that use LinkedIn OAuth and official LinkedIn APIs.

Tags: `linkedin`, `cli`, `sns-json-v1`, `unofficial-read`, `official-post`, `personal-workflow`

> This project is not affiliated with LinkedIn. Read commands use unofficial web behavior and may break when LinkedIn changes its internal endpoints. Review the terms that apply to your account.

## What It Does

Read:

- Read your home feed.
- Read saved posts.
- Fetch a profile.
- Search people and posts.
- Fetch posts from a profile.
- Inspect one activity.
- Emit `sns-json-v1` JSON for agents, scripts, and the SNS CLI ecosystem.

Write:

- Dry-run official post payloads before publishing.
- Publish text posts through the official LinkedIn Posts API.
- Publish one local image through LinkedIn Images + Posts APIs.
- Publish multi-image posts with 2-20 local images.
- Publish one local MP4 video through LinkedIn Videos + Posts APIs.
- Publish article/link posts.
- Reshare existing posts.
- Update post commentary.
- Retrieve one post or list posts by author when the token has the required read permission.
- Delete your own official posts by share/ugcPost URN, numeric share id, or feed update URL.
- Unsave saved posts.
- Keep legacy browser fallback commands for react, unreact, save, unsave, comment, and old-style posting.

## Install

```bash
pip install agent-linkedin
# or
uv tool install agent-linkedin
```

The `agent-linkedin` package provides the `linkedin-cli` command. (The PyPI name differs because `linkedin-cli` was already taken.)

From source:

```bash
git clone https://github.com/ai-native-engineer/linkedin-cli.git
cd linkedin-cli
uv sync --extra dev
```

Install Playwright only if you need browser fallback behavior:

```bash
uv run playwright install chromium
```

## Quick Start

Check the CLI:

```bash
linkedin-cli --help
```

Read commands need a LinkedIn web session. The most reliable option is a full cookie header copied from your logged-in browser:

```bash
export LINKEDIN_COOKIE_HEADER='li_at=...; JSESSIONID="ajax:..."; bcookie="..."; bscookie="..."; ...'
linkedin-cli auth-status
```

Then run read commands:

```bash
linkedin-cli read feed --limit 10 --json
linkedin-cli read saved --limit 10 --json
linkedin-cli read profile seungwon-aiden --json
linkedin-cli read profile-posts seungwon-aiden --limit 5 --json
linkedin-cli read activity urn:li:activity:1234567890 --json
linkedin-cli read search "AI engineer" --limit 10 --json
```

Write commands need an official OAuth token:

```bash
linkedin-cli post text --text "hello from linkedin-cli" --visibility public --dry-run --json
linkedin-cli post text --text "hello from linkedin-cli" --visibility public --json
linkedin-cli post media --text "hello with image" --media image.png --visibility public --json
linkedin-cli post multi-image --text "hello album" --media one.png --media two.jpg --dry-run --json
linkedin-cli post video --text "hello video" --video clip.mp4 --title "Demo" --dry-run --json
linkedin-cli post article --text "read this" --url https://example.com/post --dry-run --json
linkedin-cli post reshare urn:li:share:1234567890 --text "worth reading" --dry-run --json
linkedin-cli post update urn:li:share:1234567890 --text "updated text" --dry-run --json
linkedin-cli post get urn:li:share:1234567890 --json
linkedin-cli post list --count 10 --json
linkedin-cli post delete urn:li:share:1234567890 --dry-run --json
linkedin-cli post delete urn:li:share:1234567890 --json
```

For longer generated posts, prefer files:

```bash
linkedin-cli post text --text-file draft.md --visibility public --dry-run --json
linkedin-cli post text --text-file draft.md --visibility public --json
```

## Official OAuth Token Setup

Official `post.*` commands require a LinkedIn Developer app and an access token with `w_member_social`.

### 1. Create a LinkedIn Developer app

Open the LinkedIn Developer Portal:

```text
https://www.linkedin.com/developers/apps
```

Create an app and complete the required fields:

- App name
- LinkedIn Page
- Privacy policy URL
- App logo
- API Terms agreement

If you do not already have a LinkedIn Page, create or select the default Page LinkedIn allows for individual developers.

### 2. Enable the required products and scopes

In the app's Products/Auth settings, make sure the app can request:

- `openid`
- `profile`
- `email`
- `w_member_social`

The CLI uses `openid profile email` to identify the authenticated member and `w_member_social` to create, modify, and delete posts on that member's behalf.

### 3. Add redirect URLs

In the app's Auth tab, add the local callback URL used by the CLI:

```text
http://localhost:8787/callback
```

Optional extra callback if you want to override the host:

```text
http://127.0.0.1:8787/callback
```

The redirect URI must match exactly. If you pass `--redirect-uri` or set `LINKEDIN_REDIRECT_URI`, add that exact value to the app settings.

### 4. Provide Client ID and Client Secret

Copy the app credentials from the Auth tab.

Environment variable option:

```bash
export LINKEDIN_CLIENT_ID='...'
export LINKEDIN_CLIENT_SECRET='...'
```

### 5. Issue and save the token

Run the local OAuth flow:

```bash
linkedin-cli auth oauth-login
```

Useful options:

```bash
linkedin-cli auth oauth-login --json
linkedin-cli auth oauth-login --timeout 300
linkedin-cli auth oauth-login --no-open
linkedin-cli auth oauth-login --redirect-uri http://localhost:8787/callback
```

The command opens LinkedIn OAuth, validates the callback `state`, fetches the authenticated member, and writes:

```text
~/.config/linkedin/oauth.json
```

Token file shape:

```json
{
  "access_token": "...",
  "author_urn": "urn:li:person:...",
  "linkedin_version": "202605"
}
```

Keep this file private. The CLI expects it to be readable only by your user.

### 6. Validate before posting

Always dry-run first:

```bash
linkedin-cli post text --text "token smoke test" --visibility public --dry-run --json
```

Then publish only when the text is final:

```bash
linkedin-cli post text --text-file draft.md --visibility public --json
```

Delete by the returned post id:

```bash
linkedin-cli post delete urn:li:share:1234567890 --dry-run --json
linkedin-cli post delete urn:li:share:1234567890 --json
```

### OAuth Troubleshooting

`Oops. We can't verify the authenticity of your request because the state parameter was modified.`

- Restart `linkedin-cli auth oauth-login`.
- Do not reuse an old OAuth URL.
- Complete the flow in the browser tab opened by the CLI.
- Check that the redirect URI in the Developer Portal exactly matches the CLI redirect URI.
- If a stale localhost callback page is open, close it and retry.

`permission_denied` or missing `w_member_social`

- Confirm the app has the Share on LinkedIn / member social product enabled.
- Re-run `auth oauth-login` after the product/scope is enabled.
- Confirm the OAuth consent screen shows `w_member_social`.

`auth_expired`

- Re-run `linkedin-cli auth oauth-login`.

Official references:

- LinkedIn OAuth 2.0 Authorization Code Flow: https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow
- Share on LinkedIn: https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin
- LinkedIn Posts API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
- LinkedIn MultiImage Post API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/multiimage-post-api
- LinkedIn Videos API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/videos-api

## Read Authentication

Read authentication is separate from official write OAuth.

Resolution order:

1. `LINKEDIN_COOKIE_HEADER`
2. `LINKEDIN_LI_AT` + `LINKEDIN_JSESSIONID`
3. Browser cookie extraction from Chrome, Chromium, Brave, Edge, or Firefox

Full cookie header:

```bash
export LINKEDIN_COOKIE_HEADER='li_at=...; JSESSIONID="ajax:..."; ...'
linkedin-cli auth-status
```

Minimal cookie variables:

```bash
export LINKEDIN_LI_AT='AQ...'
export LINKEDIN_JSESSIONID='"ajax:123456789"'
```

Optional browser settings:

```bash
export LINKEDIN_BROWSER='chrome'
export LINKEDIN_HEADLESS='1'
export LINKEDIN_PROXY='http://127.0.0.1:7890'
export LINKEDIN_CONFIG="$PWD/config.yaml"
export LINKEDIN_BROWSER_STATE="$HOME/.config/linkedin-cli/browser-state.json"
```

## Command Reference

Canonical JSON commands:

```bash
linkedin-cli auth-status
linkedin-cli auth oauth-login

linkedin-cli read feed --limit 20 --json
linkedin-cli read saved --limit 20 --json
linkedin-cli read profile seungwon-aiden --json
linkedin-cli read profile-posts seungwon-aiden --limit 5 --json
linkedin-cli read activity urn:li:activity:1234567890 --json
linkedin-cli read search "product manager" --limit 10 --json

linkedin-cli saved list --limit 20 --json
linkedin-cli saved unsave urn:li:activity:123 --json

linkedin-cli post text --text "hello" --visibility public --dry-run --json
linkedin-cli post text --text-file draft.md --visibility public --json
linkedin-cli post media --text "hello with image" --media image.png --visibility public --json
linkedin-cli post multi-image --text "hello album" --media one.png --media two.jpg --json
linkedin-cli post video --text "hello video" --video clip.mp4 --title "Demo" --json
linkedin-cli post article --text "read this" --url https://example.com/post --json
linkedin-cli post reshare urn:li:share:1234567890 --text "worth reading" --json
linkedin-cli post update urn:li:share:1234567890 --text "updated text" --json
linkedin-cli post get urn:li:share:1234567890 --json
linkedin-cli post list --count 10 --json
linkedin-cli post delete urn:li:share:1234567890 --dry-run --json
linkedin-cli post delete urn:li:share:1234567890 --json
```

Legacy compatibility commands:

```bash
linkedin-cli search "product manager" --max 10
linkedin-cli profile seungwon-aiden --json
linkedin-cli profile-posts seungwon-aiden --max 20
linkedin-cli activity urn:li:activity:123
linkedin-cli post "hello from browser fallback"
linkedin-cli react urn:li:activity:123 --type like
linkedin-cli unreact urn:li:activity:123
linkedin-cli save urn:li:activity:123
linkedin-cli unsave urn:li:activity:123
linkedin-cli comment urn:li:activity:123 "nice post"
```

## JSON Contract

All canonical `--json` commands emit a single `sns-json-v1` envelope:

```json
{
  "schema_version": "sns-json-v1",
  "ok": true,
  "platform": "linkedin",
  "command": "post.text",
  "source": "official",
  "request": {},
  "data": {},
  "error": null,
  "warnings": [],
  "meta": {
    "cli_name": "linkedin-cli"
  }
}
```

Secrets are never written to `request`, `data`, `raw`, or logs.

## Python API

```python
from pathlib import Path

from linkedin_cli import LinkedInWriteAPI

api = LinkedInWriteAPI.from_config()

plan = api.plan_text_post(text=Path("draft.md").read_text(), visibility="public")
print(plan.to_dict())

result = api.create_text_post(text=Path("draft.md").read_text(), visibility="public")
print(result.url)

delete_plan = api.plan_delete_post(post_id=result.post_id)
print(delete_plan.to_dict())

delete_result = api.delete_post(post_id=result.post_id)
print(delete_result.deleted_at)
```

## Skills and Plugin

This repository ships three project-local skills. The source lives in [`.agents/skills/`](./.agents/skills); `skills/` and `.claude/skills/` are symlinks to it.

- [`linkedin-cli`](./.agents/skills/linkedin-cli) — setup, auth, read workflows, command selection
- [`linkedin-cli-auth`](./.agents/skills/linkedin-cli-auth) — session, cookie, and OAuth diagnostics
- [`linkedin-cli-write`](./.agents/skills/linkedin-cli-write) — posting and safe mutations

They also ship as a Claude plugin ([`.claude-plugin/plugin.json`](./.claude-plugin/plugin.json), [`marketplace.json`](./.claude-plugin/marketplace.json)).

## Development

```bash
uv sync --extra dev
uv run playwright install chromium
uv run ruff check .
uv run pytest -q
uv run python -m compileall linkedin_cli tests
```

Testing rules:

- Unit tests must not require a live LinkedIn session.
- Network-sensitive behavior should sit behind transport/browser abstractions.
- Live verification is useful before releases, but it should not be required for normal CI.

## Security

- Never commit cookies, OAuth tokens, HAR files, or browser storage state.
- Never paste `LINKEDIN_COOKIE_HEADER`, `li_at`, `JSESSIONID`, access tokens, client secrets, or token files into issues or pull requests.
- Sanitize screenshots, logs, and terminal transcripts before sharing.

See [SECURITY.md](.github/SECURITY.md).

## Contributing

Read:

- [CONTRIBUTING.md](.github/CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](.github/CODE_OF_CONDUCT.md)
- [SECURITY.md](.github/SECURITY.md)
- [CHANGELOG.md](./CHANGELOG.md)

## License

MIT. See [LICENSE](./LICENSE).

## Acknowledgments

`linkedin-cli` started from [`frizynn/linkedin-cli`](https://github.com/frizynn/linkedin-cli) by Juan Francisco Lebrero. This fork adds official LinkedIn OAuth publishing, a JSON contract layer, a Python write API, and packaged Codex/Claude skills. The original work is MIT-licensed, and its copyright is retained in [LICENSE](./LICENSE).
