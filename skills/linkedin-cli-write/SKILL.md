---
name: linkedin-cli-write
description: Use `linkedin-cli` for authenticated LinkedIn write actions. Trigger on requests to publish a LinkedIn post, react, unreact, save, unsave, or comment through the terminal, or when a user needs guidance on write-side browser fallback, visibility options, reaction types, or safe mutation workflows in this repo.
---

# linkedin-cli-write

Use this skill for authenticated LinkedIn mutations in the `linkedin-cli` repository.

## Preflight

Run `uv run linkedin-cli auth-status` before legacy session-based write actions. Do not attempt those actions against a degraded session.

Canonical `post` commands use official LinkedIn publishing APIs. They require `LINKEDIN_ACCESS_TOKEN` plus `LINKEDIN_AUTHOR_URN`, or a token file at `~/.config/linkedin/oauth.json`.

## Canonical Post Commands

```bash
uv run linkedin-cli post text --text "Hello from linkedin-cli" --visibility public --dry-run --json
uv run linkedin-cli post text --text-file post.md --visibility public --dry-run --json
uv run linkedin-cli post text --text "Hello from linkedin-cli" --visibility public --json
uv run linkedin-cli post media --text "Hello with image" --media image.png --visibility public --json
```

## Legacy Mutation Commands

```bash
uv run linkedin post "Hello from linkedin-cli" --visibility connections
uv run linkedin react urn:li:activity:123 --type like
uv run linkedin unreact urn:li:activity:123
uv run linkedin save urn:li:activity:123
uv run linkedin unsave urn:li:activity:123
uv run linkedin-cli saved unsave urn:li:activity:123 --json
uv run linkedin comment urn:li:activity:123 "great post"
```

## Operating Rules

- Confirm the target activity identifier before sending a mutation.
- Keep write volume conservative; do not automate repeated posting or engagement loops.
- Use `--dry-run --json` before publishing when the user wants confirmation or when the text/media was generated in the current session.
- Prefer `--text-file` for long generated posts to avoid shell quoting and accidental truncation.
- Prefer explicit visibility; use `public` only when the user asks for public publishing.
- Use `$linkedin-cli-auth` immediately when writes fail because of session health, redirects, missing cookies, or missing OAuth tokens.
- Read the reference doc before relying on browser fallback behavior.

## Read Next

- Read [write-workflows.md](references/write-workflows.md) for command coverage, fallback behavior, and failure mapping.
- Use `$linkedin-cli` for read-side inspection before mutating unknown activities.
