# AGENTS.md

Guidance for AI agents and contributors working on `linkedin-cli`.

## What This Is

`linkedin-cli` is a terminal-first LinkedIn CLI with two clearly separated surfaces:

- `read.*` — unofficial reads over the user's own authenticated LinkedIn web session.
- `post.*`, `comment.*`, `reaction.*`, `social.*` — official writes through LinkedIn OAuth and the
  Share on LinkedIn / Posts / Comments / Reactions / Social Metadata APIs.

Browser/session-fallback commands — the top-level `react`, `unreact`, `save`, `unsave`, the hidden
`post "text"`, and `comment <id> <text>` — are kept for compatibility but are not the canonical
surface. Do not confuse them with the official `post.*`/`comment.*`/`reaction.*`/`social.*` groups.

## Layout

- `linkedin_cli/` — the package. `cli.py` holds the Click commands; `client.py`/`transport.py` drive
  the read path; `oauth*.py`/`publisher.py`/`api.py` drive the official write path;
  `contract.py`/`serialization.py` build the `sns-json-v1` envelope; `browser.py` handles
  Playwright browser-context reads and fallbacks.
- `.agents/skills/` — source for the `linkedin-cli` agent skill (setup, auth, read, and write
  workflows in one skill); `skills/`, `.claude/skills/`, and `.codex/skills/` are project-local
  symlinks to it. Claude plugin metadata lives in `.claude-plugin/plugin.json`. Edit the source,
  never the symlinks.
- `tests/` — unit tests; no live LinkedIn session required.

## Output Contract

Every canonical `--json` command emits one `sns-json-v1` envelope (see `contract.py`). Never write
secrets (cookies, tokens, client secrets) into `request`, `data`, `raw`, or logs.
`read feed --comments N --json` hydrates up to `N` top comments per post into each post's
top-level `comments` array; engagement counts remain under `metrics`.

## Dev Commands

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest -q
uv run python -m compileall linkedin_cli tests
uv run playwright install chromium   # only for browser fallback
```

## Conventions

- Python >= 3.9. Ruff line-length 100. Keep implementations simple and explicit; prefer small
  functions over abstractions.
- Unit tests must not depend on a live LinkedIn session. Mock transport/browser behavior and keep
  live-network checks manual.
- When CLI behavior changes, update tests in `tests/` and docs (`README.md` + `README.en.md`) in the
  same change. Keep changes surgical and match the existing style.

## Security

- Treat cookies (`li_at`, `JSESSIONID`, `LINKEDIN_COOKIE_HEADER`, `LINKEDIN_COOKIE_FILE`) and OAuth access tokens as credentials.
- Never hardcode credentials in source, tests, fixtures, or examples. Never print raw cookie, token,
  or secret values.
- Never commit cookies, tokens, HAR files, or browser storage state. The OAuth token file
  (`~/.config/linkedin/oauth.json`) and read cookie file (`~/.config/linkedin/cookies.env`) stay
  user-private.

## Operating Skills

For command-level guidance, use the in-repo `linkedin-cli` skill — it covers setup, auth and session
diagnostics, read workflows, official publishing and safe mutations, and command selection.

See `skills/linkedin-cli/references/` for detailed cookbooks.
