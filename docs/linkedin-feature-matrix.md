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
| Image post create | `post media` | implemented | One local image; uses `/rest/images` + `/rest/posts`. |
| Post delete | `post delete` | implemented | Uses `/rest/posts/{encodedUrn}`. |
| Post get | `post get` | implemented | Requires official read permission. |
| Posts by author | `post list` | implemented | Requires official read permission. |
| Post update | `post update` | implemented | Patch commentary. |
| Article post | `post article` | implemented | URL/article content. |
| Reshare | `post reshare` | implemented | Reshare an existing post with commentary. |
| Multi-image post | `post multi-image` | implemented | 2-20 local images; uses `/rest/images` + `/rest/posts`. |
| Video post | `post video` | implemented | Local MP4; uses `/rest/videos` + `/rest/posts`. |
| Document post | `post document` | next | Needs document asset upload flow. |
| Poll post | `post poll` | next | Needs poll payload validation. |
| Organization author | `--author urn:li:organization:*` | partial | OAuth and app permission dependent. |

## Official Community APIs

| Feature | Target command | Status | Notes |
|---|---|---:|---|
| Comment list | `comment list` | implemented | Official Comments API; permission dependent. |
| Comment get | `comment get` | implemented | Official Comments API; permission dependent. |
| Comment create | `comment create` | implemented | Official Comments API; prefers official over browser fallback. |
| Comment update | `comment update` | implemented | Official Comments API; permission dependent. |
| Comment delete | `comment delete` | next | Needs endpoint confirmation before adding. |
| Reaction list | `reaction list` | implemented | Official Reactions API; permission dependent. |
| Reaction get | `reaction get` | implemented | Official Reactions API; permission dependent. |
| Reaction create | `reaction create` | implemented | Official Reactions API; prefers official over legacy `react`. |
| Reaction delete | `reaction delete` | implemented | Official Reactions API; prefers official over legacy `unreact`. |
| Social metadata | `social metadata` | implemented | Counts, summaries, comment settings. |
| Comments state | `social comments-state` | implemented | Open/close comments if permitted. |

## Unofficial Personal Read APIs

| Feature | Target command | Status | Notes |
|---|---|---:|---|
| Home feed | `read feed` | implemented | Unofficial web session. |
| Saved posts | `read saved` | implemented | Unofficial web session; pagination can improve. |
| Profile | `read profile` | implemented | Unofficial web session. |
| Search | `read search` | implemented | Unofficial web session. |
| Activity detail | `read activity` | implemented | Canonical JSON wrapper over unofficial activity read. |
| Profile posts | `read profile-posts` | implemented | Canonical JSON wrapper over unofficial profile post read. |
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

1. Confirm and add official comment deletion if supported for the current API version.
2. Add document and poll publishing.
3. Harden pagination for unofficial saved/profile-posts reads.
4. Add live permission matrix evidence for `w_member_social_feed` / `r_member_social_feed`.

Official references:

- LinkedIn Posts API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
- LinkedIn MultiImage Post API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/multiimage-post-api
- LinkedIn Videos API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/videos-api
- LinkedIn Comments API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/comments-api
- LinkedIn Reactions API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/reactions-api
- LinkedIn Social Metadata API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/social-metadata-api
