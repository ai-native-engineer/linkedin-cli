# Command Cookbook

## Contents

1. Runtime entry points
2. Preflight
3. Setup commands
4. Read commands
5. Write commands
6. Output modes
7. Identifier handling
8. Examples
9. Stability notes

## Runtime Entry Points

From the repository root, prefer:

```bash
uv run linkedin-cli ...
```

If the project is already installed as a tool, use:

```bash
linkedin-cli ...
```

If the repository has a local virtual environment but `uv` is not available, use:

```bash
.venv/bin/linkedin-cli ...
```

## Preflight

Always start with:

```bash
uv run linkedin-cli auth status --json
uv run linkedin-cli auth-status
```

Treat a degraded result as a blocker for read commands and browser/session fallback mutations until the session is repaired.

Healthy output usually contains:

- `basic-probe=ok`
- `voyager_me=ok:200`
- `voyager_feed=ok:200`
- `voyager_profile=ok:200`

## Setup Commands

Install and inspect the CLI from the project-local repo:

```bash
uv sync --extra dev
uv run linkedin-cli --help
```

Capture the read-session cookies automatically from a logged-in browser (recommended):

```bash
uv run linkedin-cli auth login
uv run linkedin-cli auth-status
```

If automatic capture finds cookies but LinkedIn rejects the session, capture a fresh browser session:

```bash
uv run linkedin-cli auth login --via-browser --browser chrome
uv run linkedin-cli auth login --via-browser --browser firefox
```

Firefox requires the Playwright Firefox build first (`uv run playwright install firefox`).
`read feed` uses the saved Playwright browser state and GraphQL fetch; saved-post browser fallback uses the persisted browser profile. `auth-status` still checks the direct HTTP transport.

If automatic capture fails, save a full Cookie header manually without printing it:

```bash
uv run linkedin-cli auth cookie-file --from-stdin
uv run linkedin-cli auth-status
```

Issue and save official publishing OAuth:

```bash
export LINKEDIN_CLIENT_ID='...'
export LINKEDIN_CLIENT_SECRET='...'
uv run linkedin-cli auth oauth-login --json --output tmp/linkedin-auth-oauth-login.json
```

Check official OAuth permissions without mutating LinkedIn:

```bash
uv run linkedin-cli auth permission-check --json
uv run linkedin-cli auth permission-check --post-id urn:li:ugcPost:123 --json
```

Verify the saved token without printing it:

```bash
ls -l ~/.config/linkedin/oauth.json
uv run python -c 'from linkedin_cli.oauth import load_oauth_config; c=load_oauth_config(); print(c.source); print(c.author_urn); print(c.linkedin_version)'
```

## Read Commands

Fetch the authenticated feed:

```bash
uv run linkedin-cli read feed --limit 10
uv run linkedin-cli read feed --limit 10 --json
uv run linkedin-cli read feed --limit 10 --comments 1 --json
uv run linkedin-cli read feed --limit 10 --json --output tmp/feed.json
```

Fetch saved posts:

```bash
uv run linkedin-cli read saved --limit 10
uv run linkedin-cli read saved --limit 10 --json
uv run linkedin-cli saved list --limit 10 --json --output tmp/saved.json
```

Search people and posts:

```bash
uv run linkedin-cli read search "staff software engineer" --limit 10
uv run linkedin-cli read search "MercadoLibre" --limit 10 --json
uv run linkedin-cli read search "AI engineer" --limit 10 --json --output tmp/search.json
```

Fetch a profile by public identifier or URL:

```bash
uv run linkedin-cli read profile your-handle
uv run linkedin-cli read profile https://www.linkedin.com/in/your-handle/ --json
```

Fetch posts from a profile:

```bash
uv run linkedin profile-posts your-handle --max 10
uv run linkedin profile-posts your-handle --max 10 --json
uv run linkedin profile-posts your-handle --max 10 --json --output tmp/posts.json
```

Inspect one activity:

```bash
uv run linkedin-cli read activity urn:li:activity:123 --json
uv run linkedin activity urn:li:activity:123 --json --output tmp/linkedin-activity.json
uv run linkedin activity 123 --json --output tmp/linkedin-activity.json
uv run linkedin activity https://www.linkedin.com/feed/update/urn:li:activity:123/ --json --output tmp/linkedin-activity.json
```

Read comments and reactions for one activity through the unofficial fallback:

```bash
uv run linkedin-cli read comments urn:li:activity:123 --limit 20 --json
uv run linkedin-cli read reactions urn:li:activity:123 --limit 20 --json
```

## Write Commands

Official text publishing uses LinkedIn Posts API:

```bash
uv run linkedin-cli post text --text "hello from linkedin-cli" --visibility public --dry-run --json
uv run linkedin-cli post text --text-file post.md --visibility public --dry-run --json
uv run linkedin-cli post text --text-file post.md --visibility public --dry-run --json --output tmp/linkedin-post-text-dry-run.json
uv run linkedin-cli post text --text-file post.md --visibility public --json
```

Official image publishing registers one local image asset, uploads it, then publishes a post:

```bash
uv run linkedin-cli post media --text-file post.md --media image.png --visibility public --dry-run --json
uv run linkedin-cli post media --text-file post.md --media image.png --visibility public --json
```

Official multi-image publishing uploads 2-20 local images, then publishes a multi-image post:

```bash
uv run linkedin-cli post multi-image --text-file post.md --media one.png --media two.jpg --dry-run --json
uv run linkedin-cli post multi-image --text-file post.md --media one.png --media two.jpg --alt-text "First image" --alt-text "Second image" --json
```

Official video publishing initializes a Videos API upload, uploads the local MP4, finalizes it, then publishes a post:

```bash
uv run linkedin-cli post video --text-file post.md --video clip.mp4 --title "Demo" --dry-run --json
uv run linkedin-cli post video --text-file post.md --video clip.mp4 --title "Demo" --json
```

Official document publishing initializes a Documents API upload, uploads one PDF/DOC/DOCX/PPT/PPTX, then publishes a post:

```bash
uv run linkedin-cli post document --text-file post.md --document deck.pdf --title "Deck" --dry-run --json
uv run linkedin-cli post document --text-file post.md --document deck.pdf --title "Deck" --json
```

Official poll publishing creates a non-sponsored poll with 2-4 options:

```bash
uv run linkedin-cli post poll --text-file post.md --question "Pick one" --option Red --option Blue --duration three-days --dry-run --json
uv run linkedin-cli post poll --text-file post.md --question "Pick one" --option Red --option Blue --json
```

Official article, reshare/quote, update, get, and list commands:

```bash
uv run linkedin-cli post article --text-file post.md --url https://example.com/post --dry-run --json
uv run linkedin-cli post article --text-file post.md --url https://example.com/post --json
uv run linkedin-cli post reshare urn:li:share:123 --text-file post.md --dry-run --json
uv run linkedin-cli post quote urn:li:share:123 --text-file post.md --dry-run --json
uv run linkedin-cli post reply urn:li:ugcPost:123 --text-file reply.md --dry-run --json
uv run linkedin-cli post repost urn:li:share:123 --dry-run --json
uv run linkedin-cli post update urn:li:share:123 --text-file post.md --dry-run --json
uv run linkedin-cli post get urn:li:share:123 --json
uv run linkedin-cli post list --limit 10 --json
uv run linkedin-cli post list --limit 10 --json --output tmp/linkedin-posts.json
```

`post quote` is a command alias for LinkedIn's official reshare payload with commentary. `post reply` is a command alias for LinkedIn's official Comments API. `post repost` is intentionally an `unsupported` contract boundary until commentary-free repost is implemented safely.

Official post deletion removes a post by share/ugcPost URN, numeric share id, or feed update URL:

```bash
uv run linkedin-cli post delete urn:li:share:123 --dry-run --json
uv run linkedin-cli post delete urn:li:share:123 --json
```

Official comments, reactions, and social metadata commands:

```bash
uv run linkedin-cli comment list urn:li:ugcPost:123 --json
uv run linkedin-cli comment get urn:li:ugcPost:123 987654321 --json
uv run linkedin-cli comment get urn:li:ugcPost:123 987654321 --json --output tmp/linkedin-comment.json
uv run linkedin-cli comment create urn:li:ugcPost:123 --text-file comment.md --dry-run --json
uv run linkedin-cli comment create urn:li:ugcPost:123 --text-file comment.md --dry-run --json --output tmp/linkedin-comment-create-dry-run.json
uv run linkedin-cli comment update urn:li:ugcPost:123 987654321 --text "updated comment" --dry-run --json
uv run linkedin-cli comment delete urn:li:ugcPost:123 987654321 --dry-run --json
uv run linkedin-cli reaction list urn:li:ugcPost:123 --json
uv run linkedin-cli reaction get urn:li:ugcPost:123 --json
uv run linkedin-cli reaction list urn:li:ugcPost:123 --json --output tmp/linkedin-reactions.json
uv run linkedin-cli reaction create urn:li:ugcPost:123 --type like --dry-run --json
uv run linkedin-cli reaction create urn:li:ugcPost:123 --type like --dry-run --json --output tmp/linkedin-reaction-create-dry-run.json
uv run linkedin-cli reaction delete urn:li:ugcPost:123 --dry-run --json
uv run linkedin-cli social metadata urn:li:ugcPost:123 --json
uv run linkedin-cli social metadata urn:li:ugcPost:123 --json --output tmp/linkedin-social-metadata.json
uv run linkedin-cli social comments-state urn:li:ugcPost:123 --state closed --dry-run --json
uv run linkedin-cli social comments-state urn:li:ugcPost:123 --state closed --dry-run --json --output tmp/linkedin-comments-state-dry-run.json
uv run linkedin-cli insights media urn:li:ugcPost:123 --json
uv run linkedin-cli insights media urn:li:ugcPost:123 --json --output tmp/linkedin-insights.json
uv run linkedin-cli insights organization urn:li:organization:123 --json
uv run linkedin-cli insights user --json
uv run linkedin-cli insights user --json --output tmp/linkedin-insights-user.json
```

`insights media` returns the Social Metadata API response in the common `insights.media` envelope. `insights organization` returns Organization Share Statistics API output in `insights.organization`. `insights user` is an `unsupported` contract boundary for personal account-level analytics.

Legacy browser/session mutations:

```bash
uv run linkedin react urn:li:activity:123 --type like
uv run linkedin unreact urn:li:activity:123
uv run linkedin save urn:li:activity:123
uv run linkedin unsave urn:li:activity:123
uv run linkedin comment urn:li:activity:123 "nice post"
```

## Output Modes

Use the human-readable output when the user wants a quick answer in the terminal.

Use `--json` when:

- another tool will parse the result
- the user wants filtering, ranking, or persistence
- the output will be summarized into a report

Use `--output <file>` only on commands that implement it:

- `auth status`
- `auth permission-check`
- `read feed`
- `read saved`
- `saved list`
- `read search`
- `read profile`
- `read activity`
- `read comments`
- `read reactions`
- `read profile-posts`
- `profile-posts`
- `post get`
- `post list`
- `comment list`
- `comment get`
- `reaction list`
- `reaction get`
- `social metadata`
- `insights media`
- `insights organization`
- `insights user`

For the contract commands (`auth status`, `auth permission-check`, `read feed`, `read saved`, `read search`, `read profile`, `read activity`, `read comments`, `read reactions`, `read profile-posts`, `saved list`, `post get`, `post list`, `comment list`, `comment get`, `reaction list`, `reaction get`, `social metadata`, `insights media`, `insights organization`, `insights user`), `--output` only writes a file when `--json` is also passed — the file contains the contract envelope, so always pair `--output` with `--json`. The flat commands (`feed`, `search`, `profile-posts`) write the file regardless of `--json`.

Do not assume legacy `profile` or `activity` support `--output`; use canonical `read profile` or `read activity` when a contract file is needed.

## Identifier Handling

Profile commands accept:

- a public id like `your-handle`
- a full profile URL like `https://www.linkedin.com/in/your-handle/`

Activity-aware commands accept:

- a full URN like `urn:li:activity:123`
- a numeric id like `123`
- a full activity URL

When a user gives a profile URL, pass it directly or extract the final path segment.

When a user gives an activity URL, pass it directly or normalize it to the URN form.

## Examples

Read the latest 20 feed items as JSON:

```bash
uv run linkedin-cli read feed --limit 20 --json
uv run linkedin-cli read feed --limit 20 --comments 1 --json
```

Read saved posts and remove one saved item:

```bash
uv run linkedin-cli read saved --limit 20 --json
uv run linkedin-cli saved unsave urn:li:activity:7323456789012345678 --dry-run --json
```

Validate a text post against the official publishing surface without side effects:

```bash
uv run linkedin-cli post text --text "hello from linkedin-cli" --visibility public --dry-run --json
uv run linkedin-cli post text --text-file post.md --visibility public --dry-run --json
```

Publish through official LinkedIn APIs:

```bash
uv run linkedin-cli post text --text-file post.md --visibility public --json
uv run linkedin-cli post media --text "hello with image" --media image.png --visibility public --json
uv run linkedin-cli post multi-image --text "hello album" --media one.png --media two.jpg --json
uv run linkedin-cli post video --text "hello video" --video clip.mp4 --title "Demo" --json
uv run linkedin-cli post document --text "hello deck" --document deck.pdf --title "Deck" --json
uv run linkedin-cli post poll --text "vote" --question "Pick one" --option Red --option Blue --json
uv run linkedin-cli post article --text "read this" --url https://example.com/post --json
uv run linkedin-cli post reshare urn:li:share:7323456789012345678 --text "worth reading" --json
uv run linkedin-cli post quote urn:li:share:7323456789012345678 --text "worth reading" --json
uv run linkedin-cli post reply urn:li:ugcPost:7323456789012345678 --text "great post" --json
uv run linkedin-cli post repost urn:li:share:7323456789012345678 --dry-run --json
```

Delete a post through official LinkedIn APIs:

```bash
uv run linkedin-cli post delete urn:li:share:7323456789012345678 --dry-run --json
uv run linkedin-cli post delete urn:li:share:7323456789012345678 --json
```

Inspect a profile and then fetch their last 5 posts:

```bash
uv run linkedin-cli read profile your-handle --json
uv run linkedin profile-posts your-handle --max 5 --json
```

Search a company name and persist results:

```bash
mkdir -p tmp
uv run linkedin-cli read search "MercadoLibre" --limit 15 --json --output tmp/mercadolibre-search.json
```

Inspect one known activity:

```bash
uv run linkedin activity urn:li:activity:7323456789012345678 --json
```

## Stability Notes

Live end-to-end verification in the repository is strongest for:

- `auth-status`
- `read feed`
- `read profile`

The following are implemented and covered by tests, but are less battle-tested against live sessions:

- `read saved`
- `saved unsave`
- `read search`
- `profile-posts`
- `activity`
- official `post text`
- official `post media`
- official `post article`
- official `post reshare` / `post quote`
- `post repost` unsupported boundary
- official `insights media`
- official `insights organization`
- `insights user` unsupported boundary
- official `post update`
- official `post get`
- official `post list`
- official `post delete`
- legacy session-based write actions

When a read command fails unexpectedly, verify `auth-status` again before assuming a code regression.
