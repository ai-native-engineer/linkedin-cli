# Initial Setup

Use this when `linkedin-cli` is not installed, OAuth is missing, or the user is setting up a new machine.

## 1. Enter The Project (clone path)

If you cloned the repo, work from its root. Skill/plugin users without a clone can skip to step 2.

```bash
cd linkedin-cli
```

This directory holds the LinkedIn CLI and its project-local skills.

## 2. Install The CLI

**From a clone (development):** install dependencies and run via `uv run`.

```bash
uv sync --extra dev
uv run linkedin-cli --help
```

**As a global command (skill/plugin users):** when `command -v linkedin-cli` is empty, the skill installs the CLI for you. You can also run the installer directly — it is idempotent and never uses sudo, but it needs `uv` or `pipx` already installed. Run the `scripts/ensure-cli.sh` that ships in the skill's own directory (from a clone, that path is `.agents/skills/linkedin-cli/scripts/ensure-cli.sh`):

```bash
bash .agents/skills/linkedin-cli/scripts/ensure-cli.sh
linkedin-cli --help
```

The PyPI package is `agent-linkedin`; it provides the `linkedin-cli` command. Browser fallback flows use Playwright; install it only when a command asks for a browser binary:

```bash
uv run playwright install chromium
```

## 3. Set Up And Verify Read Auth

Read commands are unofficial and use the user's own LinkedIn web session.

Capture cookies automatically from a logged-in browser, then verify:

```bash
uv run linkedin-cli auth login
uv run linkedin-cli auth-status
```

`auth login` extracts the session and writes `~/.config/linkedin/cookies.env` (mode `600`) without printing values. If automatic extraction fails (on macOS, Chrome/Brave/Edge may prompt for Keychain access — `--browser firefox` is the most reliable), it prints DevTools steps to capture the cookie manually and save it with `auth cookie-file --from-stdin` (paste the full `Cookie` request header, then `Ctrl-D`):

```bash
uv run linkedin-cli auth cookie-file --from-stdin
uv run linkedin-cli auth-status
```

If automatic extraction succeeds but LinkedIn Voyager still rejects the session with self-redirect/authwall behavior, capture a fresh session through a Playwright browser window:

```bash
uv run linkedin-cli auth login --via-browser --browser chrome
uv run linkedin-cli auth login --via-browser --browser firefox
```

Firefox requires the Playwright Firefox build first (`uv run playwright install firefox`).

This lets the user complete login/2FA/checkpoints in the window, then stores the full LinkedIn cookie jar and Playwright browser state privately without printing values. `read feed` uses that browser state for GraphQL fetch; `auth-status` still probes the direct HTTP transport.

The command writes `~/.config/linkedin/cookies.env` with `600` permissions and never prints cookie values. Override the path only when needed:

```bash
uv run linkedin-cli auth cookie-file --path ~/.config/linkedin/work.cookies.env --from-stdin
LINKEDIN_COOKIE_FILE=~/.config/linkedin/work.cookies.env uv run linkedin-cli auth-status
```

One-shot environment fallback:

```bash
export LINKEDIN_COOKIE_HEADER='li_at=...; JSESSIONID="ajax:..."; ...'
uv run linkedin-cli auth-status
```

Minimal environment fallback:

```bash
export LINKEDIN_LI_AT='...'
export LINKEDIN_JSESSIONID='"ajax:..."'
uv run linkedin-cli auth-status
```

Prefer the full Cookie header when feed/profile probes redirect or return authwall/checkpoint behavior.

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
uv run linkedin-cli auth permission-check --json
uv run linkedin-cli read feed --limit 3 --json
uv run linkedin-cli read saved --limit 3 --json
uv run linkedin-cli read comments urn:li:activity:123 --limit 3 --json
uv run linkedin-cli read reactions urn:li:activity:123 --limit 3 --json
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

Media posts support one local image, 2-20 local images, one local MP4 video, or one local document:

```bash
uv run linkedin-cli post media --text-file post.md --media image.png --visibility public --dry-run --json
uv run linkedin-cli post media --text-file post.md --media image.png --visibility public --json
uv run linkedin-cli post multi-image --text-file post.md --media one.png --media two.jpg --dry-run --json
uv run linkedin-cli post video --text-file post.md --video clip.mp4 --title "Demo" --dry-run --json
uv run linkedin-cli post document --text-file post.md --document deck.pdf --title "Deck" --dry-run --json
uv run linkedin-cli post poll --text-file post.md --question "Pick one" --option Red --option Blue --dry-run --json
```

Article, reshare, update, and official read commands:

```bash
uv run linkedin-cli post article --text-file post.md --url https://example.com/post --dry-run --json
uv run linkedin-cli post reshare urn:li:share:123 --text-file post.md --dry-run --json
uv run linkedin-cli post update urn:li:share:123 --text-file post.md --dry-run --json
uv run linkedin-cli post get urn:li:share:123 --json
uv run linkedin-cli post list --limit 10 --json
```

Official comment, reaction, and social metadata commands may need additional social feed permissions:

```bash
uv run linkedin-cli comment list urn:li:ugcPost:123 --json
uv run linkedin-cli comment create urn:li:ugcPost:123 --text-file comment.md --dry-run --json
uv run linkedin-cli comment delete urn:li:ugcPost:123 987654321 --dry-run --json
uv run linkedin-cli reaction get urn:li:ugcPost:123 --json
uv run linkedin-cli reaction create urn:li:ugcPost:123 --type like --dry-run --json
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
