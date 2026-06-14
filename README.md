# linkedin-cli

`linkedin-cli` is a terminal-first CLI for personal LinkedIn workflows.

It separates unofficial read workflows from official publishing workflows:

- Reads use your own authenticated LinkedIn web session and unofficial LinkedIn web endpoints.
- Canonical post commands use official LinkedIn publishing APIs with OAuth access tokens.
- Python callers can use `linkedin_cli.LinkedInWriteAPI` for the same official write surface.
- Legacy browser-based write commands are kept for compatibility, but they are not the canonical SNS ecosystem interface.

## Status

This repository is usable today, but it is still early-stage software.

Verified end-to-end against a live authenticated session:
- `linkedin auth-status`
- `linkedin feed`
- `linkedin profile`

Implemented and covered by tests, but less battle-tested against live LinkedIn sessions:
- `linkedin-cli read feed --limit 5 --json` (`sns-json-v1`)
- `linkedin-cli read saved --limit 5 --json` (`sns-json-v1`)
- `linkedin-cli read profile <identifier> --json` (`sns-json-v1`)
- `linkedin-cli read search "..." --limit 10 --json` (`sns-json-v1`)
- `linkedin-cli saved unsave <activity>` (`sns-json-v1` with `--json`)
- `linkedin-cli post text --text "..." --visibility public --dry-run --json` (`sns-json-v1`)
- `linkedin-cli post text --text-file post.md --visibility public --dry-run --json` (`sns-json-v1`)
- `linkedin-cli post text --text "..." --visibility public --json` (`sns-json-v1`)
- `linkedin-cli post media --text "..." --media image.png --visibility public --json` (`sns-json-v1`)
- `linkedin-cli post delete <post-id-or-url> --json` (`sns-json-v1`)
- `linkedin search`
- `linkedin profile-posts`
- `linkedin activity`
- `linkedin post "..."` legacy browser fallback
- `linkedin react`
- `linkedin unreact`
- `linkedin save`
- `linkedin unsave`
- `linkedin comment`

## What It Does

Read operations:
- Inspect your authenticated home feed
- Inspect posts saved by the authenticated account
- Fetch a profile by public identifier or LinkedIn profile URL
- Search people and posts
- Fetch posts from a profile
- Inspect activity details
- Emit `sns-json-v1` machine-readable JSON for ecosystem consumers

Write operations:
- Validate official LinkedIn publishing payloads with dry-run
- Publish official text posts through Share on LinkedIn / UGC Posts API
- Upload one local JPG/GIF/PNG image through LinkedIn Assets API and publish it through UGC Posts API
- Delete official posts by share/ugcPost URN, numeric share id, or feed update URL
- Remove one activity from saved posts through the authenticated web session
- Preserve legacy browser automation fallback for existing users
- React or unreact to an activity
- Save or unsave an activity
- Comment on an activity

Auth and runtime support:
- Full `LINKEDIN_COOKIE_HEADER` support
- Minimal `LINKEDIN_LI_AT` and `LINKEDIN_JSESSIONID` support
- Local OAuth authorization-code login with state validation
- Official publish token loading from `LINKEDIN_ACCESS_TOKEN`/`LINKEDIN_AUTHOR_URN` or `~/.config/linkedin/oauth.json`
- Browser cookie extraction from Chrome, Chromium, Brave, Edge, or Firefox
- Optional Playwright browser fallback for fragile write flows
- Proxy support

## Important Notes

- This project is not affiliated with LinkedIn.
- Read commands are unofficial and rely on LinkedIn web session behavior. Review the terms that apply to your account.
- Canonical post commands are designed around official LinkedIn publishing APIs.
- LinkedIn can change internal web endpoints without notice. A command that works today may need adjustment later.
- Session cookies are credentials. Treat them like passwords.
- Do not use this project for spam, bulk scraping, engagement loops, or anything that violates the platform rules that apply to your account.

## Installation

### Install from source

```bash
git clone https://github.com/ai-native-engineer/linkedin-cli.git
cd linkedin-cli
uv sync
```

### Install as a tool

```bash
uv tool install .
```

Alternative:

```bash
pipx install .
```

Install Playwright browsers if you want browser fallback support for write actions:

```bash
uv run playwright install chromium
```

## Quick Start

### 1. Export your LinkedIn session

The most reliable option is the full cookie header from a logged-in browser session.

```bash
export LINKEDIN_COOKIE_HEADER='li_at=...; JSESSIONID="ajax:..."; bcookie="..."; bscookie="..."; ...'
```

Then verify auth:

```bash
linkedin-cli auth-status
```

Expected outcome for a healthy session:
- `basic-probe=ok`
- `voyager_me=ok:200`
- `voyager_feed=ok:200`
- `voyager_profile=ok:200`

### 2. Read your feed

```bash
linkedin-cli read feed --limit 10
linkedin-cli read feed --limit 10 --json
linkedin-cli read saved --limit 10 --json
```

### 3. Inspect a profile

```bash
linkedin-cli read profile lebrero-juan-francisco
linkedin-cli read profile https://www.linkedin.com/in/lebrero-juan-francisco/ --json
```

### 4. Search

```bash
linkedin-cli read search "AI engineer" --limit 10
linkedin-cli read search "MercadoLibre" --limit 10 --json
```

### 5. Configure official publishing auth

Canonical `post` commands use Share on LinkedIn / UGC Posts API and require an OAuth access token with `w_member_social` for the selected author.

Interactive OAuth option:

```bash
linkedin-cli auth oauth-login
```

This opens LinkedIn OAuth in the browser, validates the callback `state`, fetches the authenticated user, and writes `~/.config/linkedin/oauth.json`.

Environment variable option:

```bash
export LINKEDIN_ACCESS_TOKEN='...'
export LINKEDIN_AUTHOR_URN='urn:li:person:...' # or urn:li:organization:...
```

File option:

```bash
mkdir -p ~/.config/linkedin
cat > ~/.config/linkedin/oauth.json <<'JSON'
{
  "access_token": "...",
  "author_urn": "urn:li:person:...",
  "linkedin_version": "202605"
}
JSON
```

### 6. Validate or publish a post

```bash
linkedin-cli post text --text "hello from linkedin-cli" --visibility public --dry-run --json
linkedin-cli post text --text-file post.md --visibility public --dry-run --json
linkedin-cli post text --text "hello from linkedin-cli" --visibility public --json
linkedin-cli post media --text "hello from linkedin-cli" --media image.png --visibility public --json
linkedin-cli post delete urn:li:share:1234567890 --dry-run --json
linkedin-cli post delete urn:li:share:1234567890 --json
```

For longer generated posts, prefer `--text-file` over shell-quoted inline text:

```bash
linkedin-cli post text --text-file draft.md --visibility public --json
linkedin-cli post media --text-file draft.md --media image.png --visibility public --json
```

## Authentication

Read authentication is resolved in this order:

1. `LINKEDIN_COOKIE_HEADER`
2. `LINKEDIN_LI_AT` + `LINKEDIN_JSESSIONID`
3. Browser cookie extraction from a supported local browser

Official post authentication is resolved separately:

1. `LINKEDIN_ACCESS_TOKEN` + `LINKEDIN_AUTHOR_URN`
2. `LINKEDIN_OAUTH_FILE`
3. `~/.config/linkedin/oauth.json`

Optional official post overrides:

```bash
export LINKEDIN_VERSION='202605'
linkedin-cli post text --text "hello" --author urn:li:person:... --linkedin-version 202605 --json
linkedin-cli post delete urn:li:share:... --author urn:li:person:... --linkedin-version 202605 --json
```

### Python write API

Use the same official publishing implementation from Python:

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

Supported write API methods:

- `plan_text_post(...)` validates and builds a no-side-effect UGC Posts API plan.
- `create_text_post(...)` publishes through the official Share on LinkedIn / UGC Posts API.
- `plan_image_post(...)` validates the planned one-image post shape.
- `create_image_post(...)` uploads one local JPG/GIF/PNG image, then publishes through the official UGC Posts API.
- `plan_delete_post(...)` validates a no-side-effect official post deletion target.
- `delete_post(...)` deletes a post through LinkedIn's official Posts API.

### Recommended: full cookie header

This is the most reliable option for authenticated reads.

One practical way to obtain it:
1. Log into `https://www.linkedin.com` in your browser.
2. Open developer tools.
3. Open the Network tab and reload the page.
4. Select a request to `www.linkedin.com`.
5. Copy the `cookie` request header value.
6. Export it as `LINKEDIN_COOKIE_HEADER`.

```bash
export LINKEDIN_COOKIE_HEADER='li_at=...; JSESSIONID="ajax:..."; ...'
linkedin-cli auth-status
```

### Minimal environment variables

This can be enough for some flows, but it is less reliable than the full cookie jar.

```bash
export LINKEDIN_LI_AT='AQ...'
export LINKEDIN_JSESSIONID='"ajax:123456789"'
```

### Browser cookie extraction

If you are logged into LinkedIn locally, the CLI can try to extract cookies from:
- Chrome
- Chromium
- Brave
- Edge
- Firefox

Optional environment variables:

```bash
export LINKEDIN_BROWSER='chrome'
export LINKEDIN_HEADLESS='1'
export LINKEDIN_PROXY='http://127.0.0.1:7890'
export LINKEDIN_CONFIG="$PWD/config.yaml"
export LINKEDIN_BROWSER_STATE="$HOME/.config/linkedin-cli/browser-state.json"
```

When browser cookie extraction is present but LinkedIn renders a logged-out page, browser fallback
commands can recover the session non-interactively:

1. Reuse LinkedIn's own "stay on this page to sign in" browser flow when available.
2. Use `LINKEDIN_USERNAME` + `LINKEDIN_PASSWORD` when both are set.
3. On macOS with Chrome selected, use the local Chrome Password Manager through Keychain without
   printing or persisting the password.

Successful browser fallback sessions are saved as Playwright storage state at
`~/.config/linkedin-cli/browser-state.json` by default. Override it with `LINKEDIN_BROWSER_STATE`.
Delete that file to force a fresh browser login recovery.

## Commands

```bash
linkedin-cli auth-status
linkedin-cli read feed --limit 20 --json
linkedin-cli read saved --limit 20 --json
linkedin-cli saved list --limit 20 --json
linkedin-cli saved unsave urn:li:activity:123 --json
linkedin-cli read search "product manager" --limit 10 --json
linkedin-cli read profile satyanadella --json
linkedin-cli search "product manager" --max 10
linkedin-cli profile satyanadella --json
linkedin-cli profile-posts satyanadella --max 20
linkedin-cli activity urn:li:activity:123
linkedin-cli post text --text "hello from linkedin-cli" --visibility public --dry-run --json
linkedin-cli post text --text "hello from linkedin-cli" --visibility public --json
linkedin-cli post media --text "hello with image" --media image.png --visibility public --json
linkedin-cli post delete urn:li:share:1234567890 --dry-run --json
linkedin-cli post delete urn:li:share:1234567890 --json
linkedin-cli react urn:li:activity:123 --type like
linkedin-cli unreact urn:li:activity:123
linkedin-cli save urn:li:activity:123
linkedin-cli unsave urn:li:activity:123
linkedin-cli comment urn:li:activity:123 "nice post"
```

## Codex Skills

This repository ships public Codex skills in [`skills/`](./skills/):

- `linkedin-cli` for general command selection, read workflows, and JSON export
- `linkedin-cli-auth` for cookies, auth diagnostics, browser extraction, and config
- `linkedin-cli-write` for posting, reacting, saving, unsaving, and commenting

These skills are intended to stay in-repo so anyone cloning the project can reuse the same operational guidance.

## Configuration

The repository includes a sample [`config.yaml`](./config.yaml). The default shape is:

```yaml
fetch:
  count: 20

filter:
  enabled: false
  mode: "recent"

browser:
  preferred: "chrome"
  fallback_enabled: true
  headless: true

rate_limit:
  request_delay: 1.25
  max_retries: 3
  retry_base_delay: 3.0
  write_delay_min: 1.5
  write_delay_max: 4.0
  timeout: 20.0
```

## Development

Set up a local development environment:

```bash
uv sync --extra dev
uv run playwright install chromium
```

Run checks:

```bash
uv run ruff check .
uv run pytest -q
uv run python -m compileall linkedin_cli tests
```

## Testing Philosophy

- Unit tests should not depend on a live LinkedIn session.
- Network-sensitive behavior should be isolated behind transport or browser abstractions and mocked in tests.
- Live-session verification is still useful before releases, especially for auth, feed, and profile flows.

## Security and Privacy

- Never commit cookies, tokens, HAR files, or browser state exports.
- Never paste live `LINKEDIN_COOKIE_HEADER`, `li_at`, or `JSESSIONID` values into issues or pull requests.
- Sanitize screenshots, logs, and terminal transcripts before sharing.

See [`SECURITY.md`](./SECURITY.md) for reporting guidance.

## Contributing

Contributions are welcome. Before opening a pull request, read:
- [`CONTRIBUTING.md`](./CONTRIBUTING.md)
- [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)
- [`SECURITY.md`](./SECURITY.md)
- [`CHANGELOG.md`](./CHANGELOG.md)

## License

This project is released under the [MIT License](./LICENSE).

## Acknowledgments

`linkedin-cli` started from [`frizynn/linkedin-cli`](https://github.com/frizynn/linkedin-cli) by Juan Francisco Lebrero. This fork extends it for the SNS ecosystem with official LinkedIn OAuth publishing, a JSON contract layer, a Python write API, and packaged Codex/Claude skills. The original work is MIT-licensed, and its copyright is retained in [`LICENSE`](./LICENSE).
