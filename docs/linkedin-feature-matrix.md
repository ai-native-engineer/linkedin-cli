# LinkedIn Feature Matrix

Status date: 2026-06-15

This matrix defines the target scope for making `linkedin-cli` a full personal LinkedIn workflow CLI.

## Status Labels

- `implemented`: available in CLI and covered by tests.
- `partial`: available, but not yet complete or not on the canonical command surface.
- `next`: should be implemented next.
- `restricted`: official API access or LinkedIn product approval may block normal users.
- `out-of-scope`: not aligned with the personal workflow / low-volume positioning.

## Official Write APIs

| Feature | Target command | Status | Notes |
|---|---|---:|---|
| OAuth token issue | `auth oauth-login` | implemented | Saves `~/.config/linkedin/oauth.json`. |
| Text post create | `post text` | implemented | Uses `/rest/posts`. |
| Image post create | `post media` | partial | One local image only; uses `/rest/images` + `/rest/posts`. |
| Post delete | `post delete` | implemented | Uses `/rest/posts/{encodedUrn}`. |
| Post get | `post get` | implemented | Requires official read permission. |
| Posts by author | `post list` | implemented | Requires official read permission. |
| Post update | `post update` | implemented | Patch commentary. |
| Article post | `post article` | implemented | URL/article content. |
| Reshare | `post reshare` | implemented | Reshare an existing post with commentary. |
| Multi-image post | `post media --media ... --media ...` | next | Needs multiple asset upload support. |
| Video post | `post video` | next | Needs video asset upload flow. |
| Document post | `post document` | next | Needs document asset upload flow. |
| Poll post | `post poll` | next | Needs poll payload validation. |
| Organization author | `--author urn:li:organization:*` | partial | OAuth and app permission dependent. |

## Official Community APIs

| Feature | Target command | Status | Notes |
|---|---|---:|---|
| Comment list | `comment list` | next | Official Comments API. |
| Comment create | `comment create` | next | Prefer official over browser fallback. |
| Comment update | `comment update` | next | Official Comments API. |
| Comment delete | `comment delete` | next | Official Comments API. |
| Reaction list | `reaction list` | next | Official Reactions API. |
| Reaction create | `reaction create` | next | Prefer official over legacy `react`. |
| Reaction delete | `reaction delete` | next | Prefer official over legacy `unreact`. |
| Social metadata | `social metadata` | next | Counts, summaries, comment settings. |
| Disable comments | `social comments disable` | next | Official Social Metadata API if permitted. |

## Unofficial Personal Read APIs

| Feature | Target command | Status | Notes |
|---|---|---:|---|
| Home feed | `read feed` | implemented | Unofficial web session. |
| Saved posts | `read saved` | implemented | Unofficial web session; pagination can improve. |
| Profile | `read profile` | implemented | Unofficial web session. |
| Search | `read search` | implemented | Unofficial web session. |
| Activity detail | `read activity` | next | Exists as legacy `activity`; promote to canonical JSON. |
| Profile posts | `read profile-posts` | next | Exists as legacy `profile-posts`; promote to canonical JSON. |
| Comments read | `read comments` | next | Unofficial fallback if official permission is unavailable. |
| Reactions read | `read reactions` | next | Unofficial fallback if official permission is unavailable. |
| Notifications | `read notifications` | restricted | Higher product/ToS risk; implement only if clearly personal and low-volume. |

## Explicit Non-Goals

| Feature | Status | Reason |
|---|---:|---|
| Bulk scraping | out-of-scope | Conflicts with personal workflow positioning. |
| Engagement automation loops | out-of-scope | High platform and abuse risk. |
| Messaging/DM automation | restricted | Not part of current official/personal workflow scope. |
| Connection request automation | restricted | High platform and abuse risk. |
| Sales Navigator automation | restricted | Separate product and permission model. |
| Ads campaign management | restricted | Separate Marketing/Ads API product area. |

## Implementation Order

1. Promote legacy `activity` and `profile-posts` to canonical `read activity` and `read profile-posts`.
2. Add official `comment` and `reaction` command groups.
3. Add social metadata commands.
4. Add multi-image, video, document, and poll publishing.

Official references:

- LinkedIn Posts API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
- LinkedIn Comments API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/comments-api
- LinkedIn Reactions API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/reactions-api
- LinkedIn Social Metadata API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/social-metadata-api
