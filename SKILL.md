# linkedin-cli skill

Project-local skill source lives at:

```text
skills/linkedin-cli/SKILL.md
```

Use that skill for first-time setup, OAuth/cookie auth, read commands, saved-post workflows, official UGC post publishing, and `sns-json-v1` command selection.

Start from this directory:

```bash
uv sync --extra dev
uv run linkedin-cli auth-status
```

Issue official publishing OAuth with:

```bash
agents-env run LINKEDIN_CLIENT_ID LINKEDIN_CLIENT_SECRET -- \
  uv run linkedin-cli auth oauth-login
```
