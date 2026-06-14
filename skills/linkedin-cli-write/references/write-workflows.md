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
uv run linkedin-cli post media --text "hello from linkedin-cli" --media image.png --visibility public --dry-run --json
```

Publish through official LinkedIn APIs:

```bash
uv run linkedin-cli post text --text "hello from linkedin-cli" --visibility public --json
uv run linkedin-cli post text --text-file post.md --visibility public --json
uv run linkedin-cli post media --text "hello from linkedin-cli" --media image.png --visibility public --json
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
uv run linkedin-cli saved unsave urn:li:activity:123 --json
```

Inspect saved posts before removing one:

```bash
uv run linkedin-cli read saved --limit 20 --json
uv run linkedin-cli saved unsave urn:li:activity:123 --json
```

Comment on an activity:

```bash
uv run linkedin comment urn:li:activity:123 "nice post"
```

## Official Post Auth

Official `post text`, `post media`, and `post delete` load OAuth credentials from:

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

`post media` currently supports exactly one local JPG/GIF/PNG image path. Multiple media files, videos, and carousels are outside the current vertical slice.

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

Use `plan_text_post`, `plan_image_post`, or `plan_delete_post` for no-side-effect validation before mutating LinkedIn.

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

- `post text` publishes through the official Share on LinkedIn / UGC Posts API
- `post media` registers an official Assets API upload, uploads one image, then publishes through UGC Posts API
- `post delete` deletes through the official LinkedIn Posts API
- `post text --dry-run`, `post media --dry-run`, and `post delete --dry-run` validate planned official payloads without side effects
- `linkedin_cli.LinkedInWriteAPI` exposes the same official text and one-image write surface to Python callers
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

`Unsupported image type for LinkedIn upload`

- Use one local `.jpg`, `.jpeg`, `.gif`, or `.png` file

`Official LinkedIn post delete requires a share or ugcPost URN`

- Use the `id` returned by `post text` or `post media`, or paste the LinkedIn feed update URL
- Do not pass a `urn:li:activity:*` value to `post delete`

## Safety Rules

- Treat all write operations as user-facing side effects.
- Do not post, react, save, or comment in bulk.
- Do not log secrets or browser cookies while debugging write failures.
- Do not log OAuth access tokens while debugging official publishing failures.
- Use `--dry-run --json` before official publishing when content was generated in the current session or needs user review.
- Confirm `public` visibility explicitly; otherwise prefer `connections` for legacy browser posting.
