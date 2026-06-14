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
uv run linkedin-cli auth-status
```

Treat a degraded result as a blocker for all read and write requests until the session is repaired.

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

Issue and save official publishing OAuth:

```bash
agents-env run LINKEDIN_CLIENT_ID LINKEDIN_CLIENT_SECRET -- \
  uv run linkedin-cli auth oauth-login
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
uv run linkedin-cli read profile satyanadella
uv run linkedin-cli read profile https://www.linkedin.com/in/satyanadella/ --json
```

Fetch posts from a profile:

```bash
uv run linkedin profile-posts satyanadella --max 10
uv run linkedin profile-posts satyanadella --max 10 --json
uv run linkedin profile-posts satyanadella --max 10 --json --output tmp/posts.json
```

Inspect one activity:

```bash
uv run linkedin activity urn:li:activity:123 --json
uv run linkedin activity 123 --json
uv run linkedin activity https://www.linkedin.com/feed/update/urn:li:activity:123/ --json
```

## Write Commands

Official text publishing uses Share on LinkedIn / UGC API:

```bash
uv run linkedin-cli post text --text "hello from linkedin-cli" --visibility public --dry-run --json
uv run linkedin-cli post text --text-file post.md --visibility public --dry-run --json
uv run linkedin-cli post text --text-file post.md --visibility public --json
```

Official image publishing registers one local image asset, uploads it, then publishes a UGC post:

```bash
uv run linkedin-cli post media --text-file post.md --media image.png --visibility public --dry-run --json
uv run linkedin-cli post media --text-file post.md --media image.png --visibility public --json
```

Official post deletion removes a post by share/ugcPost URN, numeric share id, or feed update URL:

```bash
uv run linkedin-cli post delete urn:li:share:123 --dry-run --json
uv run linkedin-cli post delete urn:li:share:123 --json
```

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

- `read feed`
- `read saved`
- `saved list`
- `read search`
- `read profile`
- `profile-posts`

For the contract commands (`read feed`, `read saved`, `read search`, `read profile`, `saved list`), `--output` only writes a file when `--json` is also passed — the file contains the contract envelope, so always pair `--output` with `--json`. The flat commands (`feed`, `search`, `profile-posts`) write the file regardless of `--json`.

Do not assume `profile` or `activity` support `--output`; they do not.

## Identifier Handling

Profile commands accept:

- a public id like `lebrero-juan-francisco`
- a full profile URL like `https://www.linkedin.com/in/lebrero-juan-francisco/`

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
```

Read saved posts and remove one saved item:

```bash
uv run linkedin-cli read saved --limit 20 --json
uv run linkedin-cli saved unsave urn:li:activity:7323456789012345678 --json
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
```

Delete a post through official LinkedIn APIs:

```bash
uv run linkedin-cli post delete urn:li:share:7323456789012345678 --dry-run --json
uv run linkedin-cli post delete urn:li:share:7323456789012345678 --json
```

Inspect a profile and then fetch their last 5 posts:

```bash
uv run linkedin-cli read profile lebrero-juan-francisco --json
uv run linkedin profile-posts lebrero-juan-francisco --max 5 --json
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
- official `post delete`
- legacy session-based write actions

When a read command fails unexpectedly, verify `auth-status` again before assuming a code regression.
