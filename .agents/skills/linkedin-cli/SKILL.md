---
name: linkedin-cli
description: Use the project-local `linkedin-cli` skill for all LinkedIn CLI work in this repository — setup, authentication, reads, official publishing, and command selection. Trigger on requests to set up linkedin-cli, configure or diagnose LinkedIn OAuth, access tokens, or cookies, run auth-status or permission-check, fix cookie/session/redirect/authwall/checkpoint failures or browser cookie extraction, read feeds, saved posts, profiles, activities, comments, or reactions, search people/posts, publish or dry-run posts (text, media, multi-image, video, document, poll, article, reshare, update, delete), react, comment, manage reactions and social metadata, unsave items, export sns-json-v1 JSON, or choose the right `linkedin-cli` command.
---

# linkedin-cli

Use this project-local skill for LinkedIn setup, auth, read workflows, official Posts API publishing, and command selection in this repository.

## Boundaries

- Run commands from the repository root unless the user has installed the package globally.
- Treat `read.*` as unofficial: it uses the user's own LinkedIn web session.
- Treat `post.*`, `comment.*`, `reaction.*`, and `social.*` as official: they use LinkedIn REST APIs with OAuth. Comments, reactions, and social metadata may require Social Feed permissions beyond `w_member_social`.
- Never print cookies, access tokens, client secrets, passwords, or browser storage-state contents.
- Use `--dry-run --json` before live publishing generated content.

## Standard Workflow

1. If the user is setting up the CLI, read `references/initial-setup.md`.
2. If the CLI already exists, start with `uv run linkedin-cli auth-status`.
3. Choose the narrowest command that answers the request.
4. Prefer canonical `linkedin-cli read ... --json` for agent, Skim, or script consumption.
5. For auth/session failures, read `references/auth-troubleshooting.md`.
6. For mutations and publishing details, read `references/write-workflows.md`.
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
uv run linkedin-cli auth permission-check --json
```

## Command Selection

| Need | Command |
|------|---------|
| Install dependencies | `uv sync --extra dev` |
| Verify session and probes | `uv run linkedin-cli auth-status` |
| Issue official OAuth token | `uv run linkedin-cli auth oauth-login` (export `LINKEDIN_CLIENT_ID`/`LINKEDIN_CLIENT_SECRET` first) |
| Check official OAuth permissions | `uv run linkedin-cli auth permission-check --json` |
| Check post-scoped official permissions | `uv run linkedin-cli auth permission-check --post-id urn:li:ugcPost:123 --json` |
| Read home feed as SNS contract JSON | `uv run linkedin-cli read feed --limit 10 --json` |
| Read saved posts as SNS contract JSON | `uv run linkedin-cli read saved --limit 10 --json` |
| Unsave one saved activity | `uv run linkedin-cli saved unsave urn:li:activity:123 --json` |
| Search people and posts | `uv run linkedin-cli read search "AI engineer" --limit 10 --json` |
| Fetch one profile | `uv run linkedin-cli read profile seungwon-aiden --json` |
| Fetch recent posts from a profile | `uv run linkedin-cli read profile-posts seungwon-aiden --limit 10 --json` |
| Inspect one activity | `uv run linkedin-cli read activity urn:li:activity:123 --json` |
| Read activity comments | `uv run linkedin-cli read comments urn:li:activity:123 --limit 20 --json` |
| Read activity reactions | `uv run linkedin-cli read reactions urn:li:activity:123 --limit 20 --json` |
| Dry-run text post | `uv run linkedin-cli post text --text-file post.md --visibility public --dry-run --json` |
| Publish text post | `uv run linkedin-cli post text --text-file post.md --visibility public --json` |
| Dry-run image post | `uv run linkedin-cli post media --text-file post.md --media image.png --visibility public --dry-run --json` |
| Dry-run multi-image post | `uv run linkedin-cli post multi-image --text-file post.md --media one.png --media two.jpg --dry-run --json` |
| Dry-run video post | `uv run linkedin-cli post video --text-file post.md --video clip.mp4 --title "Demo" --dry-run --json` |
| Dry-run document post | `uv run linkedin-cli post document --text-file post.md --document deck.pdf --title "Deck" --dry-run --json` |
| Dry-run poll post | `uv run linkedin-cli post poll --text-file post.md --question "Pick one" --option Red --option Blue --dry-run --json` |
| Dry-run article post | `uv run linkedin-cli post article --text-file post.md --url https://example.com --dry-run --json` |
| Dry-run reshare | `uv run linkedin-cli post reshare urn:li:share:123 --text-file post.md --dry-run --json` |
| Dry-run post update | `uv run linkedin-cli post update urn:li:share:123 --text-file post.md --dry-run --json` |
| Get official post | `uv run linkedin-cli post get urn:li:share:123 --json` |
| List official posts by author | `uv run linkedin-cli post list --count 10 --json` |
| Dry-run post deletion | `uv run linkedin-cli post delete urn:li:share:123 --dry-run --json` |
| Delete an official post | `uv run linkedin-cli post delete urn:li:share:123 --json` |
| List official comments | `uv run linkedin-cli comment list urn:li:ugcPost:123 --json` |
| Create official comment | `uv run linkedin-cli comment create urn:li:ugcPost:123 --text-file comment.md --json` |
| Delete official comment | `uv run linkedin-cli comment delete urn:li:ugcPost:123 987654321 --json` |
| Create official reaction | `uv run linkedin-cli reaction create urn:li:ugcPost:123 --type like --json` |
| Delete official reaction | `uv run linkedin-cli reaction delete urn:li:ugcPost:123 --json` |
| Get social metadata | `uv run linkedin-cli social metadata urn:li:ugcPost:123 --json` |
| Open or close comments | `uv run linkedin-cli social comments-state urn:li:ugcPost:123 --state closed --json` |

## Identifier Rules

- Pass a profile public identifier like `seungwon-aiden` or a full LinkedIn profile URL to `profile` and `profile-posts`.
- Pass a full activity URN, a numeric activity id, or a LinkedIn activity URL to `activity` and write-side commands.
- Normalize to `--json` before downstream processing when the request involves filtering, summarizing, or saving structured output.

## Read Next

- Read [initial-setup.md](references/initial-setup.md) for first-time setup, OAuth token issue, cookie/session setup, and verification order.
- Read [command-cookbook.md](references/command-cookbook.md) for exact command patterns, JSON usage, and realistic examples.
- Read [auth-troubleshooting.md](references/auth-troubleshooting.md) for session recovery and runtime troubleshooting.
- Read [write-workflows.md](references/write-workflows.md) for authenticated mutations and browser fallback behavior.
