---
name: linkedin-cli
description: Use the project-local `linkedin-cli` skill for LinkedIn CLI setup and operation. Trigger on requests to set up linkedin-cli, configure LinkedIn OAuth or cookies, run auth-status, inspect feeds or saved posts, search people/posts, fetch profiles, publish or dry-run LinkedIn posts, unsave items, export sns-json-v1 JSON, or choose the right `linkedin-cli` command in this repository.
---

# linkedin-cli

Use this project-local skill for LinkedIn setup, auth, read workflows, official Posts API publishing, and command selection in this repository.

## Boundaries

- Run commands from the repository root unless the user has installed the package globally.
- Treat `read.*` as unofficial: it uses the user's own LinkedIn web session.
- Treat `post.*` as official: it uses LinkedIn Posts API with OAuth `w_member_social`.
- Never print cookies, access tokens, client secrets, passwords, or browser storage-state contents.
- Use `--dry-run --json` before live publishing generated content.

## Standard Workflow

1. If the user is setting up the CLI, read `references/initial-setup.md`.
2. If the CLI already exists, start with `uv run linkedin-cli auth-status`.
3. Choose the narrowest command that answers the request.
4. Prefer canonical `linkedin-cli read ... --json` for agent, Skim, or script consumption.
5. For auth/session failures, read `../linkedin-cli-auth/references/auth-troubleshooting.md`.
6. For mutations and publishing details, read `../linkedin-cli-write/references/write-workflows.md`.
7. For exact command patterns, read `references/command-cookbook.md`.

## Setup Quick Start

```bash
cd linkedin-cli
uv sync --extra dev
uv run linkedin-cli --help
uv run linkedin-cli auth-status
```

Official publishing token setup:

```bash
export LINKEDIN_CLIENT_ID='...'
export LINKEDIN_CLIENT_SECRET='...'
uv run linkedin-cli auth oauth-login
```

## Command Selection

| Need | Command |
|------|---------|
| Install dependencies | `uv sync --extra dev` |
| Verify session and probes | `uv run linkedin-cli auth-status` |
| Issue official OAuth token | `uv run linkedin-cli auth oauth-login` (export `LINKEDIN_CLIENT_ID`/`LINKEDIN_CLIENT_SECRET` first) |
| Read home feed as SNS contract JSON | `uv run linkedin-cli read feed --limit 10 --json` |
| Read saved posts as SNS contract JSON | `uv run linkedin-cli read saved --limit 10 --json` |
| Unsave one saved activity | `uv run linkedin-cli saved unsave urn:li:activity:123 --json` |
| Search people and posts | `uv run linkedin-cli read search "AI engineer" --limit 10 --json` |
| Fetch one profile | `uv run linkedin-cli read profile seungwon-aiden --json` |
| Fetch recent posts from a profile | `uv run linkedin profile-posts seungwon-aiden --max 10` |
| Inspect one activity | `uv run linkedin activity urn:li:activity:123 --json` |
| Dry-run text post | `uv run linkedin-cli post text --text-file post.md --visibility public --dry-run --json` |
| Publish text post | `uv run linkedin-cli post text --text-file post.md --visibility public --json` |
| Dry-run image post | `uv run linkedin-cli post media --text-file post.md --media image.png --visibility public --dry-run --json` |
| Dry-run article post | `uv run linkedin-cli post article --text-file post.md --url https://example.com --dry-run --json` |
| Dry-run reshare | `uv run linkedin-cli post reshare urn:li:share:123 --text-file post.md --dry-run --json` |
| Dry-run post update | `uv run linkedin-cli post update urn:li:share:123 --text-file post.md --dry-run --json` |
| Get official post | `uv run linkedin-cli post get urn:li:share:123 --json` |
| List official posts by author | `uv run linkedin-cli post list --count 10 --json` |
| Dry-run post deletion | `uv run linkedin-cli post delete urn:li:share:123 --dry-run --json` |
| Delete an official post | `uv run linkedin-cli post delete urn:li:share:123 --json` |

## Identifier Rules

- Pass a profile public identifier like `seungwon-aiden` or a full LinkedIn profile URL to `profile` and `profile-posts`.
- Pass a full activity URN, a numeric activity id, or a LinkedIn activity URL to `activity` and write-side commands.
- Normalize to `--json` before downstream processing when the request involves filtering, summarizing, or saving structured output.

## Read Next

- Read [initial-setup.md](references/initial-setup.md) for first-time setup, OAuth token issue, cookie/session setup, and verification order.
- Read [command-cookbook.md](references/command-cookbook.md) for exact command patterns, JSON usage, and realistic examples.
- Read [auth-troubleshooting.md](../linkedin-cli-auth/references/auth-troubleshooting.md) for session recovery and runtime troubleshooting.
- Read [write-workflows.md](../linkedin-cli-write/references/write-workflows.md) for authenticated mutations and browser fallback behavior.
