# LinkedIn OAuth Permission Evidence

This file records safe, redacted permission probe results for the current development setup.
Do not paste OAuth tokens, author URNs, Authorization headers, cookies, or raw API payloads here.

## 2026-06-15

Command:

```bash
uv run linkedin-cli auth permission-check --json
```

Result summary:

| Probe | Result | Code |
|---|---:|---|
| `openid.userinfo` | pass | `null` |
| `posts.author_list` | fail | `permission_denied` |

Interpretation:

- The saved OAuth token is loadable and can call OpenID userinfo.
- The current LinkedIn app/token does not have the official permission needed by `posts.author_list`.
- No post-scoped probes were run in this check because no `--post-id` was provided.
