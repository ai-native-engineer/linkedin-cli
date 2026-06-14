---
name: linkedin-cli-auth
description: Diagnose and repair `linkedin-cli` authentication and runtime setup. Trigger on requests about `auth-status`, cookies, `LINKEDIN_COOKIE_HEADER`, `LINKEDIN_LI_AT`, `LINKEDIN_JSESSIONID`, `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_AUTHOR_URN`, `LINKEDIN_OAUTH_FILE`, browser extraction, `LINKEDIN_BROWSER`, `LINKEDIN_HEADLESS`, `LINKEDIN_PROXY`, `LINKEDIN_CONFIG`, `config.yaml`, redirect loops, authwall, checkpoint, session rejection, or any failure to authenticate LinkedIn requests in this repo.
---

# linkedin-cli-auth

Use this skill when the main problem is session health, cookie sourcing, official publish token loading, browser extraction, config, or redirects.

## First Action

Run:

```bash
uv run linkedin-cli auth-status
```

Use that output as the source of truth before trying any other LinkedIn command.

## Read Auth Resolution Order

`linkedin-cli` resolves auth in this order:

1. `LINKEDIN_COOKIE_HEADER`
2. `LINKEDIN_LI_AT` + `LINKEDIN_JSESSIONID`
3. Browser cookie extraction from Chrome, Chromium, Brave, Edge, or Firefox

Prefer the full cookie header over the minimal cookie pair whenever reads are unstable.

For browser fallback actions and saved-post reads, if extracted cookies open a logged-out LinkedIn
page, `linkedin-cli` can recover through the browser path:

1. LinkedIn's own "stay on this page to sign in" countdown screen.
2. `LINKEDIN_USERNAME` + `LINKEDIN_PASSWORD`, when both are set.
3. macOS Chrome Password Manager via Keychain when `LINKEDIN_BROWSER=chrome`.

The recovered Playwright storage state is saved at
`~/.config/linkedin-cli/browser-state.json` unless `LINKEDIN_BROWSER_STATE` overrides it. Never print
the password or storage-state contents.

## Official Post Auth Resolution Order

Canonical `post` commands use official LinkedIn API OAuth tokens. They resolve auth in this order:

1. `LINKEDIN_ACCESS_TOKEN` + `LINKEDIN_AUTHOR_URN`
2. `LINKEDIN_OAUTH_FILE`
3. `~/.config/linkedin/oauth.json`

Issue and save a token with:

```bash
uv run linkedin-cli auth oauth-login
```

This command requires `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET`, opens the LinkedIn OAuth
consent screen, validates `state`, fetches OpenID userinfo, and saves the token file without printing
the access token.

The token file must contain:

```json
{
  "access_token": "...",
  "author_urn": "urn:li:person:...",
  "linkedin_version": "202605"
}
```

## Operating Rules

- Treat cookies and session headers like passwords.
- Treat OAuth access tokens like passwords.
- Never print raw cookie values in logs, issues, or shared transcripts.
- Never print raw OAuth access tokens in logs, issues, or shared transcripts.
- Never print raw `LINKEDIN_USERNAME`, `LINKEDIN_PASSWORD`, or Chrome Password Manager values.
- Fail fast when `auth-status` reports redirects, authwall, checkpoint, or missing required cookies.
- Re-run `auth-status` after each cookie/session fix before retrying `feed`, `profile`, or legacy session-based write actions.
- Route to `$linkedin-cli-write` when the auth problem is resolved and the remaining task is a write action.

## Read Next

- Read [auth-troubleshooting.md](references/auth-troubleshooting.md) for failure mapping, env vars, config, and browser notes.
- Use `$linkedin-cli` when the task shifts back to read workflows.
