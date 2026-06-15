# Write Workflows

## Contents

1. Preflight
2. Command matrix
3. Official post auth
4. Identifier handling
5. Browser fallback behavior
6. Failure mapping
7. Safety rules

## Preflight

Always verify the session first:

```bash
uv run linkedin-cli auth-status
```

If the result is degraded, stop and repair auth before legacy session-based mutations.

## Command Matrix

Validate official post payloads without side effects:

```bash
uv run linkedin-cli post text --text "hello from linkedin-cli" --visibility public --dry-run --json
uv run linkedin-cli post text --text-file post.md --visibility public --dry-run --json
uv run linkedin-cli post text --text-file post.md --visibility public --dry-run --json --output tmp/linkedin-post-text-dry-run.json
uv run linkedin-cli post media --text "hello from linkedin-cli" --media image.png --visibility public --dry-run --json
uv run linkedin-cli post multi-image --text-file post.md --media one.png --media two.jpg --dry-run --json
uv run linkedin-cli post video --text-file post.md --video clip.mp4 --title "Demo" --dry-run --json
uv run linkedin-cli post document --text-file post.md --document deck.pdf --title "Deck" --dry-run --json
uv run linkedin-cli post poll --text-file post.md --question "Pick one" --option Red --option Blue --dry-run --json
uv run linkedin-cli post article --text "read this" --url https://example.com/post --dry-run --json
uv run linkedin-cli post reshare urn:li:share:123 --text "worth reading" --dry-run --json
uv run linkedin-cli post quote urn:li:share:123 --text "worth reading" --dry-run --json
uv run linkedin-cli post reply urn:li:ugcPost:123 --text-file reply.md --dry-run --json
uv run linkedin-cli post repost urn:li:share:123 --dry-run --json
uv run linkedin-cli post update urn:li:share:123 --text "updated" --dry-run --json
```

Publish through official LinkedIn APIs:

```bash
uv run linkedin-cli post text --text "hello from linkedin-cli" --visibility public --json
uv run linkedin-cli post text --text-file post.md --visibility public --json
uv run linkedin-cli post media --text "hello from linkedin-cli" --media image.png --visibility public --json
uv run linkedin-cli post multi-image --text-file post.md --media one.png --media two.jpg --json
uv run linkedin-cli post video --text-file post.md --video clip.mp4 --title "Demo" --json
uv run linkedin-cli post document --text-file post.md --document deck.pdf --title "Deck" --json
uv run linkedin-cli post poll --text-file post.md --question "Pick one" --option Red --option Blue --json
uv run linkedin-cli post article --text "read this" --url https://example.com/post --json
uv run linkedin-cli post reshare urn:li:share:123 --text "worth reading" --json
uv run linkedin-cli post quote urn:li:share:123 --text "worth reading" --json
uv run linkedin-cli post reply urn:li:ugcPost:123 --text-file reply.md --json
uv run linkedin-cli post update urn:li:share:123 --text "updated" --json
uv run linkedin-cli post get urn:li:share:123 --json
uv run linkedin-cli post list --limit 10 --json
```

Use official social action commands for comments, reactions, and comment state:

```bash
uv run linkedin-cli comment list urn:li:ugcPost:123 --json
uv run linkedin-cli comment create urn:li:ugcPost:123 --text-file comment.md --dry-run --json
uv run linkedin-cli comment create urn:li:ugcPost:123 --text-file comment.md --dry-run --json --output tmp/linkedin-comment-create-dry-run.json
uv run linkedin-cli comment update urn:li:ugcPost:123 987654321 --text "updated" --dry-run --json
uv run linkedin-cli comment delete urn:li:ugcPost:123 987654321 --dry-run --json
uv run linkedin-cli reaction create urn:li:ugcPost:123 --type like --dry-run --json
uv run linkedin-cli reaction create urn:li:ugcPost:123 --type like --dry-run --json --output tmp/linkedin-reaction-create-dry-run.json
uv run linkedin-cli reaction delete urn:li:ugcPost:123 --dry-run --json
uv run linkedin-cli social metadata urn:li:ugcPost:123 --json
uv run linkedin-cli social comments-state urn:li:ugcPost:123 --state closed --dry-run --json
uv run linkedin-cli social comments-state urn:li:ugcPost:123 --state closed --dry-run --json --output tmp/linkedin-comments-state-dry-run.json
uv run linkedin-cli insights media urn:li:ugcPost:123 --json
uv run linkedin-cli insights organization urn:li:organization:123 --json
uv run linkedin-cli insights user --json
```

Delete through official LinkedIn APIs:

```bash
uv run linkedin-cli post delete urn:li:share:123 --dry-run --json
uv run linkedin-cli post delete urn:li:share:123 --json
```

Existing browser-based posting remains a legacy compatibility path:

```bash
uv run linkedin post "hello from linkedin-cli"
uv run linkedin post "hello from linkedin-cli" --visibility connections
```

React to an activity:

```bash
uv run linkedin react urn:li:activity:123 --type like
uv run linkedin react urn:li:activity:123 --type celebrate
uv run linkedin react urn:li:activity:123 --type support
uv run linkedin react urn:li:activity:123 --type love
uv run linkedin react urn:li:activity:123 --type insightful
uv run linkedin react urn:li:activity:123 --type curious
```

Remove the current reaction:

```bash
uv run linkedin unreact urn:li:activity:123
```

Save or unsave an activity:

```bash
uv run linkedin save urn:li:activity:123
uv run linkedin unsave urn:li:activity:123
uv run linkedin-cli saved unsave urn:li:activity:123 --dry-run --json
```

Inspect saved posts before removing one:

```bash
uv run linkedin-cli read saved --limit 20 --json
uv run linkedin-cli saved unsave urn:li:activity:123 --dry-run --json
```

Comment on an activity:

```bash
uv run linkedin comment urn:li:activity:123 "nice post"
```

## Official Post Auth

Official `post text`, `post media`, `post article`, `post reshare`, `post quote`, `post update`, `post get`, `post list`, and `post delete` load OAuth credentials from:

1. `LINKEDIN_ACCESS_TOKEN` + `LINKEDIN_AUTHOR_URN`
2. `LINKEDIN_OAUTH_FILE`
3. `~/.config/linkedin/oauth.json`

Token file shape:

```json
{
  "access_token": "...",
  "author_urn": "urn:li:person:...",
  "linkedin_version": "202605"
}
```

Use `--author` or `--linkedin-version` only when the caller explicitly wants to override the environment or file.

Use `--text-file <path>` for long posts. Use `--text-file -` only when the caller intentionally pipes stdin into the command.

`post media` supports exactly one local JPG/GIF/PNG image path.

`post multi-image` supports 2-20 local JPG/GIF/PNG image paths and optional `--alt-text` values. If alt text is provided, pass exactly one `--alt-text` per image.

`post video` supports one local MP4 file. It initializes a Videos API upload, uploads the video bytes, finalizes the upload, then creates the post.

`post document` supports one local PDF/DOC/DOCX/PPT/PPTX file. It initializes a Documents API upload, uploads the document, then creates the post.

`post poll` supports non-sponsored polls with 2-4 options. Use `--duration one-day|three-days|seven-days|fourteen-days`.

`post article` accepts `--url` plus optional `--title`, `--description`, and `--thumbnail`.

`post get` and `post list` may require `r_member_social` or `r_organization_social`; a token with only `w_member_social` may receive `permission_denied`.

`comment.*`, `reaction.*`, and `social.*` may require `w_member_social_feed`, `r_member_social_feed`, `w_organization_social_feed`, or `r_organization_social_feed`; a token with only `w_member_social` may receive `permission_denied`.

Use the no-side-effect permission probe before debugging individual official API failures:

```bash
uv run linkedin-cli auth permission-check --json
uv run linkedin-cli auth permission-check --post-id urn:li:ugcPost:123 --json
```

`post delete` accepts a `urn:li:share:*`, `urn:li:ugcPost:*`, numeric share id, or LinkedIn feed update URL. It rejects `urn:li:activity:*` because the official delete surface expects a post/share URN.

## Python Write API

Programmatic callers should use the same official write surface as the CLI:

```python
from pathlib import Path

from linkedin_cli import LinkedInWriteAPI

api = LinkedInWriteAPI.from_config()
plan = api.plan_text_post(text=Path("post.md").read_text(), visibility="public")
result = api.create_text_post(text=Path("post.md").read_text(), visibility="public")
delete_plan = api.plan_delete_post(post_id=result.post_id)
delete_result = api.delete_post(post_id=result.post_id)
```

Use `plan_text_post`, `plan_image_post`, `plan_multi_image_post`, `plan_video_post`, or `plan_delete_post` for no-side-effect validation before mutating LinkedIn.

## Identifier Handling

Write-side commands accept:

- a full activity URN
- a numeric activity id
- a full LinkedIn activity URL

Normalize unknown activity references before mutating them. If needed, inspect them first with:

```bash
uv run linkedin activity <identifier> --json
```

## Browser Fallback Behavior

Current implementation details:

- `post text` publishes through the official LinkedIn Posts API
- `post media` registers an official Images API upload, uploads one image, then publishes through Posts API
- `post multi-image` registers and uploads 2-20 official Images API assets, then publishes through Posts API
- `post video` initializes an official Videos API upload, uploads/finalizes the MP4, then publishes through Posts API
- `post document` initializes an official Documents API upload, uploads the document, then publishes through Posts API
- `post poll` publishes non-sponsored poll content through Posts API
- `post article`, `post reshare`, `post quote`, `post update`, `post get`, and `post list` use the official LinkedIn Posts API
- `post quote` is a command alias for LinkedIn's official reshare payload with commentary
- `post reply` is a command alias for LinkedIn's official Comments API
- `post repost` returns an `unsupported` JSON contract boundary until commentary-free repost is implemented safely
- `post delete` deletes through the official LinkedIn Posts API
- `comment list/get/create/update/delete` use the official LinkedIn Comments API
- `reaction list/get/create/delete` use the official LinkedIn Reactions API
- `social metadata` and `social comments-state` use the official LinkedIn Social Metadata API
- `insights media` returns Social Metadata API output in the common `insights.media` envelope
- `insights organization` returns Organization Share Statistics API output in `insights.organization`
- `insights user` returns an `unsupported` JSON contract boundary until personal account-level analytics are implemented
- `post text --dry-run`, `post media --dry-run`, `post multi-image --dry-run`, `post video --dry-run`, `post document --dry-run`, `post poll --dry-run`, `post article --dry-run`, `post reshare --dry-run`, `post quote --dry-run`, `post reply --dry-run`, `post update --dry-run`, `post delete --dry-run`, `comment create/update/delete --dry-run`, `reaction create/delete --dry-run`, `social comments-state --dry-run`, and `saved unsave --dry-run` validate planned payloads without side effects
- `linkedin_cli.LinkedInWriteAPI` exposes the same official write surface to Python callers
- legacy `post "..."` uses Playwright-backed browser fallback
- `comment` uses Playwright-backed browser fallback
- `save` and `unsave` use Playwright-backed browser fallback
- `saved unsave` is the canonical JSON-emitting wrapper for the same saved-item removal flow
- `unreact` uses Playwright-backed browser fallback
- `react` uses the API client directly

Important limitation:

- browser fallback only supports applying `like` directly when it is used as the fallback path
- richer reactions depend on the normal API flow succeeding

If Playwright browsers are missing, install them from the repository root:

```bash
uv run playwright install chromium
```

## Failure Mapping

`Unsupported reaction type`

- Use one of: `like`, `celebrate`, `support`, `love`, `insightful`, `curious`

`Unsupported LinkedIn activity identifier`

- Convert the value to a numeric activity id, a full URN, or a LinkedIn activity URL

`Unable to locate LinkedIn UI control`

- LinkedIn UI selectors likely changed or the session is not landing on the expected page
- verify `auth-status`
- retry with a healthy browser-backed session

`Playwright is not installed`

- Install project dependencies and Playwright browser binaries before retrying

`Missing LinkedIn OAuth token file`

- Set `LINKEDIN_ACCESS_TOKEN` and `LINKEDIN_AUTHOR_URN`, or write `~/.config/linkedin/oauth.json`
- Run `uv run linkedin-cli auth permission-check --json` after token setup to verify the token without printing it

`Unsupported image type for LinkedIn upload`

- Use one local `.jpg`, `.jpeg`, `.gif`, or `.png` file

`Official LinkedIn post delete requires a share or ugcPost URN`

- Use the `id` returned by `post text` or `post media`, or paste the LinkedIn feed update URL
- Do not pass a `urn:li:activity:*` value to `post delete`

## Safety Rules

- Treat all write operations as user-facing side effects.
- Do not post, react, save, or comment in bulk.
- Do not use browser automation for bulk saved-post cleanup, bulk unsave, bulk scraping, or repeated
  page-draining loops. LinkedIn's User Agreement restricts scripts, robots, crawlers, scraping, and
  unauthorized automated access; see https://www.linkedin.com/legal/user-agreement and
  https://www.linkedin.com/help/linkedin/answer/a1341387.
- Use `references/terms-automation-guardrail.md` for the reusable risk assessment and user-facing
  response template.
- If LinkedIn shows an automation, suspicious-activity, account-risk, checkpoint, restriction, or
  "review tools" warning, stop immediately. Kill running Playwright/browser automation processes,
  report what was already backed up or mutated, and do not try to bypass or continue the workflow.
- After an automation warning, only advise manual cleanup in LinkedIn's official UI or a separately
  reviewed official-API path. Do not restart the same browser-automation workflow in the same session.
- Do not log secrets or browser cookies while debugging write failures.
- Do not log OAuth access tokens while debugging official publishing failures.
- Use `--dry-run --json` before official publishing when content was generated in the current session or needs user review.
- Confirm `public` visibility explicitly; otherwise prefer `connections` for legacy browser posting.
