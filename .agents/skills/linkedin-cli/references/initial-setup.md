# Initial Setup

Use this when `linkedin-cli` is not installed, OAuth is missing, or the user is setting up a new machine.

## 1. Enter The Project

Work from the repository root:

```bash
cd linkedin-cli
```

This directory holds the LinkedIn CLI and its project-local skills.

## 2. Install Dependencies

```bash
uv sync --extra dev
uv run linkedin-cli --help
```

Browser fallback flows use Playwright. If a command asks for a browser binary, install it from this directory:

```bash
uv run playwright install chromium
```

## 3. Verify Read Auth

Read commands are unofficial and use the user's own LinkedIn web session.

Start with:

```bash
uv run linkedin-cli auth-status
```

If cookie auth is missing or degraded, use one of these:

```bash
export LINKEDIN_COOKIE_HEADER='li_at=...; JSESSIONID="ajax:..."; ...'
export LINKEDIN_LI_AT='...'
export LINKEDIN_JSESSIONID='"ajax:..."'
```

Prefer the full `LINKEDIN_COOKIE_HEADER` when feed/profile probes redirect or return authwall/checkpoint behavior.

## 4. Set Up Official Posting OAuth

Official posting uses LinkedIn Posts API. The LinkedIn developer app must have:

- Product: `Share on LinkedIn`
- Scope: `w_member_social`
- Redirect URL: `http://localhost:8787/callback`
- Optional redirect URL: `http://127.0.0.1:8787/callback`

Set `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET`, then issue and save the token:

```bash
export LINKEDIN_CLIENT_ID='...'
export LINKEDIN_CLIENT_SECRET='...'
uv run linkedin-cli auth oauth-login
```

The command opens LinkedIn OAuth, validates `state`, exchanges the code, fetches userinfo, and writes:

```text
~/.config/linkedin/oauth.json
```

That file must stay private and is expected to have `600` permissions. Never print its token contents.

## 5. Smoke Test The Contract

After setup, run safe checks:

```bash
uv run linkedin-cli read feed --limit 3 --json
uv run linkedin-cli read saved --limit 3 --json
uv run linkedin-cli post text --text "hello from linkedin-cli" --visibility public --dry-run --json
uv run linkedin-cli post delete urn:li:share:123 --dry-run --json
```

Dry-run output for text posts should include:

```json
{
  "ok": true,
  "command": "post.text",
  "source": "official",
  "data": {
    "planned": {
      "api": "linkedin.posts"
    }
  }
}
```

## 6. Live Publishing Rule

Do not run live publishing unless the user provides or confirms the exact final text/media and understands it will create a public LinkedIn side effect.

Preferred long-post flow:

```bash
uv run linkedin-cli post text --text-file post.md --visibility public --dry-run --json
uv run linkedin-cli post text --text-file post.md --visibility public --json
```

Media posts support one local image, 2-20 local images, or one local MP4 video:

```bash
uv run linkedin-cli post media --text-file post.md --media image.png --visibility public --dry-run --json
uv run linkedin-cli post media --text-file post.md --media image.png --visibility public --json
uv run linkedin-cli post multi-image --text-file post.md --media one.png --media two.jpg --dry-run --json
uv run linkedin-cli post video --text-file post.md --video clip.mp4 --title "Demo" --dry-run --json
```

Article, reshare, update, and official read commands:

```bash
uv run linkedin-cli post article --text-file post.md --url https://example.com/post --dry-run --json
uv run linkedin-cli post reshare urn:li:share:123 --text-file post.md --dry-run --json
uv run linkedin-cli post update urn:li:share:123 --text-file post.md --dry-run --json
uv run linkedin-cli post get urn:li:share:123 --json
uv run linkedin-cli post list --count 10 --json
```

Official comment, reaction, and social metadata commands may need additional social feed permissions:

```bash
uv run linkedin-cli comment list urn:li:ugcPost:123 --json
uv run linkedin-cli comment create urn:li:ugcPost:123 --text-file comment.md --json
uv run linkedin-cli reaction get urn:li:ugcPost:123 --json
uv run linkedin-cli reaction create urn:li:ugcPost:123 --type like --json
uv run linkedin-cli social metadata urn:li:ugcPost:123 --json
```

Post deletion accepts the id returned by `post text`/`post media`:

```bash
uv run linkedin-cli post delete urn:li:share:123 --dry-run --json
uv run linkedin-cli post delete urn:li:share:123 --json
```

## 7. Verification Before Handoff

For code changes:

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
```

For live credentials, verify without printing secrets:

```bash
ls -l ~/.config/linkedin/oauth.json
uv run python -c 'from linkedin_cli.oauth import load_oauth_config; c=load_oauth_config(); print(c.source); print(c.author_urn); print(c.linkedin_version)'
```
