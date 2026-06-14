# Changelog

All notable changes to this project should be documented in this file.

The format is based on Keep a Changelog, adapted for this repository.

## [0.1.0] - 2026-03-09

Initial open-source release of the Python-based LinkedIn CLI (Click commands).

Read (unofficial, over the user's own web session):
- Home feed, saved posts, profile, search, activity, profile-posts, and activity comments/reactions
- `LINKEDIN_COOKIE_HEADER`, minimal env cookies, and browser cookie extraction
- Auth diagnostics and direct Voyager transport

Write (official, through LinkedIn OAuth):
- OAuth login and no-side-effect permission checks
- Posts API publishing — text, image, multi-image, video, document, poll, article, reshare, update, get, list, and delete (all with `--dry-run`)
- Official Comments, Reactions, and Social Metadata commands
- Browser/session fallback for legacy posting, reacting, saving, and commenting

Tooling:
- `sns-json-v1` output contract across canonical `--json` commands
- Python write API (`linkedin_cli.LinkedInWriteAPI`)
- Tests, CI workflow, and publish workflow
