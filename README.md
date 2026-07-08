<h1 align="center">linkedin-cli</h1>

<p align="center">AI 에이전트가 LinkedIn을 다루는 CLI — 비공식 읽기와 공식 OAuth 게시를 명확히 분리</p>

<p align="center">
  <a href="https://pypi.org/project/agent-linkedin/"><img src="https://img.shields.io/pypi/v/agent-linkedin.svg" alt="PyPI"></a>
  <a href="https://github.com/ai-native-engineer/linkedin-cli/actions/workflows/ci.yml"><img src="https://github.com/ai-native-engineer/linkedin-cli/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="license"></a>
  <img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="python">
</p>

<p align="center"><b>한국어</b> · <a href="./README.en.md">English</a></p>

---

`linkedin-cli`는 두 표면을 명확히 분리합니다.

- `read.*`: 본인 LinkedIn 웹 세션을 사용하는 비공식 읽기 워크플로우
- `post.*`: LinkedIn OAuth와 공식 LinkedIn API를 사용하는 공식 쓰기 워크플로우

태그: `linkedin`, `cli`, `sns-json-v1`, `unofficial-read`, `official-post`, `personal-workflow`, `oauth`, `comments`, `reactions`, `media`

> 이 프로젝트는 LinkedIn과 무관합니다. 읽기 명령은 비공식 웹 동작에 의존하며, LinkedIn 내부 엔드포인트가 바뀌면 깨질 수 있습니다. 계정에 적용되는 약관은 사용자가 직접 검토해야 하며, 준수 책임은 사용자에게 있습니다.

## 기능

읽기:

- 홈 피드 읽기
- 저장한 게시글 읽기
- 프로필 조회
- 사람/게시글 검색
- 특정 프로필의 게시글 조회
- 단일 activity 조회
- 활동 댓글 읽기
- 활동 반응 읽기
- 에이전트, 스크립트, SNS CLI ecosystem 소비용 `sns-json-v1` JSON 출력

쓰기:

- 실제 발행 전 공식 게시 payload dry-run
- 공식 LinkedIn Posts API로 텍스트 게시
- LinkedIn Images + Posts API로 로컬 이미지 1개 게시
- 로컬 이미지 2~20장 다중 이미지 게시
- LinkedIn Videos + Posts API로 로컬 MP4 영상 1개 게시
- LinkedIn Documents + Posts API로 PDF/DOC/DOCX/PPT/PPTX 문서 게시
- Posts API로 non-sponsored poll 게시
- article/link 게시
- 기존 게시글 재공유
- 공식 Comments API 기반 `post reply` 답글 작성
- 게시글 commentary 수정
- 공식 Comments API로 댓글 목록/조회/작성/수정/삭제
- 공식 Reactions API로 반응 목록/조회/생성/삭제
- 공식 Social Metadata API로 반응/댓글 요약 조회 및 댓글 open/closed 상태 수정
- Social Metadata API 결과를 `insights.media` 계약으로 조회
- Organization Share Statistics API 결과를 `insights.organization` 계약으로 조회
- 개인 계정 단위 `insights.user`는 현재 `unsupported` 계약으로 명시
- 토큰에 필요한 read 권한이 있을 때 단일 게시글 조회 및 author별 게시글 목록 조회
- share/ugcPost URN, numeric share id, feed update URL로 본인 공식 게시글 삭제
- 저장한 게시글 저장 취소
- react, unreact, save, unsave, comment, 구형 posting을 위한 legacy browser fallback 유지

## 설치

```bash
pip install agent-linkedin
# 또는
uv tool install agent-linkedin
```

`agent-linkedin` 패키지가 `linkedin-cli` 명령을 제공합니다. PyPI에서 `linkedin-cli` 이름은 이미 점유되어 배포명만 다릅니다.

소스에서 설치:

```bash
git clone https://github.com/ai-native-engineer/linkedin-cli.git
cd linkedin-cli
uv sync --extra dev
```

소스에서 실행할 때는 명령 앞에 `uv run`을 붙입니다(예: `uv run linkedin-cli --help`). `uv tool install .`로 전역 설치하면 아래 예시처럼 `linkedin-cli`를 그대로 쓸 수 있습니다.

브라우저 fallback이 필요할 때만 Playwright를 설치합니다.

```bash
uv run playwright install chromium
```

## 빠른 시작

> 아래 예시는 설치된 `linkedin-cli` 기준입니다. clone에서 개발 중이면 각 명령 앞에 `uv run`을 붙이거나(`uv run linkedin-cli ...`), `uv tool install .`로 전역 설치하세요.

CLI 확인:

```bash
linkedin-cli --help
```

읽기 명령은 LinkedIn 웹 세션이 필요합니다. 가장 쉬운 방법은 로그인된 브라우저에서 쿠키를 자동으로 가져오는 것입니다.

```bash
linkedin-cli auth login
linkedin-cli auth-status
```

`auth login`은 로그인된 브라우저(Chrome·Chromium·Brave·Edge·Firefox)에서 쿠키를 추출해 private file(`~/.config/linkedin/cookies.env`, 권한 `600`)에 저장하고 세션을 검증합니다. 자동 추출이 실패하면 DevTools로 직접 복사하는 단계를 출력합니다 — [읽기 인증](#읽기-인증) 참고. `read feed`와 saved-post browser fallback은 쿠키를 Python HTTP 클라이언트에만 의존하지 않고, 저장된 Playwright browser state/프로필 안에서 읽기를 실행합니다.

자동 추출은 성공했지만 LinkedIn Voyager가 self-redirect/authwall로 세션을 거부하면, 새 웹 세션을 직접 캡처합니다.

```bash
linkedin-cli auth login --via-browser --browser chrome
linkedin-cli auth login --via-browser --browser firefox
```

Firefox를 선택하려면 Playwright Firefox 빌드가 필요합니다: `uv run playwright install firefox`.

이 명령은 Playwright 브라우저 창을 열고 사용자가 직접 로그인/2FA/checkpoint를 통과한 뒤 전체 LinkedIn 쿠키 jar와 browser state를 private file에 저장합니다. 쿠키 값은 출력하지 않습니다. `auth-status`는 direct HTTP 진단이므로 browser-context 기반 `read feed`와 결과가 다를 수 있습니다.

공식 OAuth 권한을 mutation 없이 점검:

```bash
linkedin-cli auth permission-check --json
linkedin-cli auth permission-check --post-id urn:li:ugcPost:1234567890 --json
```

읽기 명령 실행:

```bash
linkedin-cli read feed --limit 10 --json
linkedin-cli read feed --limit 10 --comments 1 --json
linkedin-cli read saved --limit 10 --json
linkedin-cli read profile your-handle --json
linkedin-cli read profile-posts your-handle --limit 5 --json
linkedin-cli read activity urn:li:activity:1234567890 --json
linkedin-cli read comments urn:li:activity:1234567890 --limit 20 --json
linkedin-cli read reactions urn:li:activity:1234567890 --limit 20 --json
linkedin-cli read search "AI engineer" --limit 10 --json
```

쓰기 명령은 공식 OAuth 토큰이 필요합니다.

```bash
linkedin-cli post text --text "hello from linkedin-cli" --visibility public --dry-run --json
linkedin-cli post text --text "hello from linkedin-cli" --visibility public --dry-run --json --output tmp/linkedin-post-text-dry-run.json
linkedin-cli post text --text "hello from linkedin-cli" --visibility public --json
linkedin-cli post media --text "hello with image" --media image.png --visibility public --json
linkedin-cli post multi-image --text "hello album" --media one.png --media two.jpg --dry-run --json
linkedin-cli post video --text "hello video" --video clip.mp4 --title "Demo" --dry-run --json
linkedin-cli post document --text "hello deck" --document deck.pdf --title "Deck" --dry-run --json
linkedin-cli post poll --text "vote" --question "Pick one" --option Red --option Blue --duration three-days --dry-run --json
linkedin-cli post article --text "read this" --url https://example.com/post --dry-run --json
linkedin-cli post reshare urn:li:share:1234567890 --text "worth reading" --dry-run --json
linkedin-cli post quote urn:li:share:1234567890 --text "worth reading" --dry-run --json
linkedin-cli post reply urn:li:ugcPost:1234567890 --text "great post" --dry-run --json
linkedin-cli post repost urn:li:share:1234567890 --dry-run --json
linkedin-cli post update urn:li:share:1234567890 --text "updated text" --dry-run --json
linkedin-cli post get urn:li:share:1234567890 --json
linkedin-cli post list --limit 10 --json
linkedin-cli post delete urn:li:share:1234567890 --dry-run --json
linkedin-cli post delete urn:li:share:1234567890 --json
linkedin-cli comment list urn:li:ugcPost:1234567890 --json
linkedin-cli comment create urn:li:ugcPost:1234567890 --text "great post" --dry-run --json
linkedin-cli comment create urn:li:ugcPost:1234567890 --text "great post" --dry-run --json --output tmp/linkedin-comment-create-dry-run.json
linkedin-cli comment update urn:li:ugcPost:1234567890 987654321 --text "updated comment" --dry-run --json
linkedin-cli comment delete urn:li:ugcPost:1234567890 987654321 --dry-run --json
linkedin-cli reaction create urn:li:ugcPost:1234567890 --type like --dry-run --json
linkedin-cli reaction create urn:li:ugcPost:1234567890 --type like --dry-run --json --output tmp/linkedin-reaction-create-dry-run.json
linkedin-cli reaction delete urn:li:ugcPost:1234567890 --dry-run --json
linkedin-cli social metadata urn:li:ugcPost:1234567890 --json
linkedin-cli social metadata urn:li:ugcPost:1234567890 --json --output tmp/linkedin-social-metadata.json
linkedin-cli social comments-state urn:li:ugcPost:1234567890 --state closed --dry-run --json
linkedin-cli social comments-state urn:li:ugcPost:1234567890 --state closed --dry-run --json --output tmp/linkedin-comments-state-dry-run.json
linkedin-cli insights media urn:li:ugcPost:1234567890 --json
linkedin-cli insights organization urn:li:organization:123456 --json
linkedin-cli insights user --json
linkedin-cli insights user --json --output tmp/linkedin-insights-user.json
```

긴 글이나 생성된 글은 inline text보다 파일 입력을 권장합니다.

```bash
linkedin-cli post text --text-file draft.md --visibility public --dry-run --json
linkedin-cli post text --text-file draft.md --visibility public --json
```

## 공식 OAuth 토큰 발급

공식 `post.*` 명령은 LinkedIn Developer app과 `w_member_social` 권한이 있는 access token이 필요합니다.
공식 `comment.*`, `reaction.*`, `social.*` 명령은 LinkedIn app/product 승인 상태에 따라 `w_member_social_feed`, `r_member_social_feed`, `w_organization_social_feed`, `r_organization_social_feed` 같은 추가 권한이 필요할 수 있습니다.

### 1. LinkedIn Developer app 만들기

LinkedIn Developer Portal을 엽니다.

```text
https://www.linkedin.com/developers/apps
```

앱을 만들고 필수 항목을 채웁니다.

- App name
- LinkedIn Page
- Privacy policy URL
- App logo
- API Terms 동의

LinkedIn Page가 없다면 새로 만들거나, 개인 개발자에게 허용되는 기본 Page를 선택합니다.

### 2. 필요한 product와 scope 활성화

앱의 Products/Auth 설정에서 아래 scope를 요청할 수 있어야 합니다.

- `openid`
- `profile`
- `email`
- `w_member_social`

CLI는 `openid profile email`로 인증된 멤버를 식별하고, `w_member_social`로 해당 멤버의 게시글 생성/수정/삭제를 수행합니다.
댓글/반응/소셜 메타데이터 명령은 LinkedIn의 Social Feed 권한이 있어야 성공합니다. 권한이 없으면 CLI는 `permission_denied` JSON envelope를 반환합니다.

### 3. Redirect URL 추가

앱의 Auth 탭에 CLI가 사용하는 로컬 callback URL을 추가합니다.

```text
http://localhost:8787/callback
```

host override를 쓰려면 아래 URL도 추가할 수 있습니다.

```text
http://127.0.0.1:8787/callback
```

redirect URI는 정확히 일치해야 합니다. `--redirect-uri`나 `LINKEDIN_REDIRECT_URI`를 쓴다면 그 값을 Developer Portal에도 그대로 추가해야 합니다.

### 4. Client ID와 Client Secret 설정

Auth 탭에서 앱 credential을 복사합니다.

환경 변수 방식:

```bash
export LINKEDIN_CLIENT_ID='...'
export LINKEDIN_CLIENT_SECRET='...'
```

### 5. 토큰 발급 및 저장

로컬 OAuth flow를 실행합니다.

```bash
linkedin-cli auth oauth-login
```

유용한 옵션:

```bash
linkedin-cli auth oauth-login --json --output tmp/linkedin-auth-oauth-login.json
linkedin-cli auth oauth-login --timeout 300
linkedin-cli auth oauth-login --no-open
linkedin-cli auth oauth-login --redirect-uri http://localhost:8787/callback
```

이 명령은 LinkedIn OAuth를 브라우저에서 열고, callback `state`를 검증하고, 인증된 멤버를 조회한 뒤 아래 파일에 토큰을 저장합니다.

```text
~/.config/linkedin/oauth.json
```

토큰 파일 구조:

```json
{
  "access_token": "...",
  "author_urn": "urn:li:person:...",
  "linkedin_version": "202605"
}
```

이 파일은 비공개로 보관해야 합니다. CLI는 사용자 본인만 읽을 수 있는 파일로 취급합니다.

### 6. 게시 전 검증

항상 dry-run을 먼저 실행합니다.

```bash
linkedin-cli post text --text "token smoke test" --visibility public --dry-run --json
```

최종 문구가 확정된 뒤에만 게시합니다.

```bash
linkedin-cli post text --text-file draft.md --visibility public --json
```

반환된 post id로 삭제할 수 있습니다.

```bash
linkedin-cli post delete urn:li:share:1234567890 --dry-run --json
linkedin-cli post delete urn:li:share:1234567890 --json
```

### OAuth 문제 해결

`Oops. We can't verify the authenticity of your request because the state parameter was modified.`

- `linkedin-cli auth oauth-login`을 새로 실행합니다.
- 오래된 OAuth URL을 재사용하지 않습니다.
- CLI가 연 브라우저 탭에서 flow를 완료합니다.
- Developer Portal의 redirect URI가 CLI redirect URI와 정확히 같은지 확인합니다.
- 오래된 localhost callback 페이지가 열려 있으면 닫고 다시 시도합니다.

`permission_denied` 또는 `w_member_social` 누락

- 앱에 Share on LinkedIn / member social product가 활성화되어 있는지 확인합니다.
- product/scope를 활성화한 뒤 `auth oauth-login`을 다시 실행합니다.
- OAuth 동의 화면에 `w_member_social`이 표시되는지 확인합니다.
- 댓글/반응/소셜 메타데이터 명령이면 `w_member_social_feed`/`r_member_social_feed` 또는 organization social feed 권한이 필요한지 확인합니다.

`auth_expired`

- `linkedin-cli auth oauth-login`을 다시 실행합니다.

공식 참고 문서:

- LinkedIn OAuth 2.0 Authorization Code Flow: https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow
- Share on LinkedIn: https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin
- LinkedIn Posts API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
- LinkedIn MultiImage Post API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/multiimage-post-api
- LinkedIn Videos API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/videos-api
- LinkedIn Documents API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/documents-api
- LinkedIn Poll API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/poll-post-api
- LinkedIn Comments API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/comments-api
- LinkedIn Reactions API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/reactions-api
- LinkedIn Social Metadata API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/social-metadata-api

## 읽기 인증

읽기 인증은 공식 쓰기 OAuth와 분리되어 있습니다.

해결 순서:

1. `LINKEDIN_COOKIE_HEADER`
2. `LINKEDIN_LI_AT` + `LINKEDIN_JSESSIONID`
3. `LINKEDIN_COOKIE_FILE` 또는 기본 파일 `~/.config/linkedin/cookies.env`
4. Chrome, Chromium, Brave, Edge, Firefox의 브라우저 cookie 추출

**권장: `auth login`으로 자동 캡처.** 로그인된 브라우저에서 쿠키를 추출해 private file(권한 `600`)에 저장하고 세션을 검증합니다. 값은 절대 출력하지 않습니다.

```bash
linkedin-cli auth login
linkedin-cli auth-status
```

자동 추출된 쿠키가 LinkedIn Voyager에서 거부되면 Playwright 브라우저 창으로 새 세션을 직접 캡처합니다.

```bash
linkedin-cli auth login --via-browser --browser chrome
linkedin-cli auth login --via-browser --browser firefox
```

Firefox를 선택하려면 Playwright Firefox 빌드가 필요합니다: `uv run playwright install firefox`.

자동 추출이 실패하면(macOS는 Chrome·Brave·Edge가 Keychain 접근을 요구 — `--browser firefox`가 가장 안정적) 아래 단계로 직접 캡처합니다.

**수동 캡처 (DevTools):**

1. 브라우저에서 https://www.linkedin.com 에 로그인된 상태를 확인합니다.
2. DevTools를 엽니다 (macOS `Option+Command+I`, 또는 `F12`).
3. **Application** 탭 → **Storage** → **Cookies** → `https://www.linkedin.com`.
4. `li_at`와 `JSESSIONID` 값을 복사합니다 (`JSESSIONID`는 `"ajax:..."` 형태이니 따옴표를 포함해 복사).
5. 한 줄로 만듭니다: `li_at=<값>; JSESSIONID=<값>`
6. 저장: `linkedin-cli auth cookie-file --from-stdin`을 실행하고 그 줄을 붙여넣은 뒤 `Return`, `Ctrl-D`.
7. 검증: `linkedin-cli auth-status`

또는 DevTools **Network** 탭에서 `www.linkedin.com` 요청의 `cookie:` request header 전체를 복사해 같은 명령에 붙여넣어도 됩니다(LinkedIn이 가끔 요구하는 더 완전한 cookie jar).

이 값들은 LinkedIn 비밀번호와 같습니다 — 채팅에 붙여넣거나 커밋·공유하지 마세요.

일회성 env 방식:

```bash
export LINKEDIN_COOKIE_HEADER='li_at=...; JSESSIONID="ajax:..."; ...'
linkedin-cli auth-status
```

최소 cookie 변수. authwall/checkpoint나 redirect가 나오면 전체 Cookie header를 사용하세요.

```bash
export LINKEDIN_LI_AT='AQ...'
export LINKEDIN_JSESSIONID='"ajax:123456789"'
```

선택적 브라우저 설정:

```bash
export LINKEDIN_BROWSER='chrome'
export LINKEDIN_HEADLESS='1'
export LINKEDIN_PROXY='http://127.0.0.1:7890'
export LINKEDIN_CONFIG="$PWD/config.yaml"
export LINKEDIN_COOKIE_FILE="$HOME/.config/linkedin/cookies.env"
export LINKEDIN_BROWSER_STATE="$HOME/.config/linkedin-cli/browser-state.json"
```

## 명령 레퍼런스

표준 JSON 명령:

```bash
linkedin-cli auth-status
linkedin-cli auth oauth-login

linkedin-cli read feed --limit 20 --json
linkedin-cli read feed --limit 20 --comments 1 --json
linkedin-cli read saved --limit 20 --json
linkedin-cli read profile your-handle --json
linkedin-cli read profile-posts your-handle --limit 5 --json
linkedin-cli read activity urn:li:activity:1234567890 --json
linkedin-cli read comments urn:li:activity:1234567890 --limit 20 --json
linkedin-cli read reactions urn:li:activity:1234567890 --limit 20 --json
linkedin-cli read search "product manager" --limit 10 --json

linkedin-cli saved list --limit 20 --json
linkedin-cli saved unsave urn:li:activity:123 --dry-run --json

linkedin-cli post text --text "hello" --visibility public --dry-run --json
linkedin-cli post text --text-file draft.md --visibility public --json
linkedin-cli post media --text "hello with image" --media image.png --visibility public --json
linkedin-cli post multi-image --text "hello album" --media one.png --media two.jpg --json
linkedin-cli post video --text "hello video" --video clip.mp4 --title "Demo" --json
linkedin-cli post document --text "hello deck" --document deck.pdf --title "Deck" --json
linkedin-cli post poll --text "vote" --question "Pick one" --option Red --option Blue --duration three-days --json
linkedin-cli post article --text "read this" --url https://example.com/post --json
linkedin-cli post reshare urn:li:share:1234567890 --text "worth reading" --json
linkedin-cli post quote urn:li:share:1234567890 --text "worth reading" --json
linkedin-cli post reply urn:li:ugcPost:1234567890 --text "great post" --json
linkedin-cli post repost urn:li:share:1234567890 --dry-run --json
linkedin-cli post update urn:li:share:1234567890 --text "updated text" --json
linkedin-cli post get urn:li:share:1234567890 --json
linkedin-cli post list --limit 10 --json
linkedin-cli post delete urn:li:share:1234567890 --dry-run --json
linkedin-cli post delete urn:li:share:1234567890 --json

linkedin-cli comment list urn:li:ugcPost:1234567890 --json
linkedin-cli comment get urn:li:ugcPost:1234567890 987654321 --json
linkedin-cli comment create urn:li:ugcPost:1234567890 --text "great post" --dry-run --json
linkedin-cli comment update urn:li:ugcPost:1234567890 987654321 --text "updated comment" --dry-run --json
linkedin-cli comment delete urn:li:ugcPost:1234567890 987654321 --dry-run --json

linkedin-cli reaction list urn:li:ugcPost:1234567890 --json
linkedin-cli reaction get urn:li:ugcPost:1234567890 --json
linkedin-cli reaction create urn:li:ugcPost:1234567890 --type like --dry-run --json
linkedin-cli reaction delete urn:li:ugcPost:1234567890 --dry-run --json

linkedin-cli social metadata urn:li:ugcPost:1234567890 --json
linkedin-cli social metadata urn:li:ugcPost:1234567890 --json --output tmp/linkedin-social-metadata.json
linkedin-cli social comments-state urn:li:ugcPost:1234567890 --state open --dry-run --json
linkedin-cli insights media urn:li:ugcPost:1234567890 --json
linkedin-cli insights organization urn:li:organization:123456 --json
linkedin-cli insights user --json
linkedin-cli insights user --json --output tmp/linkedin-insights-user.json
```

Legacy 호환 명령:

```bash
linkedin-cli feed --max 10
linkedin-cli search "product manager" --max 10
linkedin-cli profile your-handle --json --output tmp/linkedin-profile.json
linkedin-cli profile-posts your-handle --max 20
linkedin-cli activity urn:li:activity:123 --json --output tmp/linkedin-activity.json
linkedin-cli post "hello from browser fallback"
linkedin-cli react urn:li:activity:123 --type like
linkedin-cli unreact urn:li:activity:123
linkedin-cli save urn:li:activity:123
linkedin-cli unsave urn:li:activity:123
linkedin-cli comment urn:li:activity:123 "nice post"
```

## JSON 계약

모든 표준 `--json` 명령은 하나의 `sns-json-v1` envelope만 출력합니다.

```json
{
  "schema_version": "sns-json-v1",
  "ok": true,
  "platform": "linkedin",
  "command": "post.text",
  "source": "official",
  "request": {},
  "data": {},
  "error": null,
  "warnings": [],
  "meta": {
    "cli_name": "linkedin-cli"
  }
}
```

secret은 `request`, `data`, `raw`, log에 쓰지 않습니다.

## Python API

```python
from pathlib import Path

from linkedin_cli import LinkedInWriteAPI

api = LinkedInWriteAPI.from_config()

plan = api.plan_text_post(text=Path("draft.md").read_text(), visibility="public")
print(plan.to_dict())

result = api.create_text_post(text=Path("draft.md").read_text(), visibility="public")
print(result.url)

delete_plan = api.plan_delete_post(post_id=result.post_id)
print(delete_plan.to_dict())

delete_result = api.delete_post(post_id=result.post_id)
print(delete_result.deleted_at)
```

## Skills

이 repo는 셋업, 인증, 읽기/쓰기 워크플로, 명령 선택을 하나로 다루는 project-local [`linkedin-cli`](./.agents/skills/linkedin-cli) skill을 포함합니다. 정본은 [`.agents/skills/linkedin-cli/SKILL.md`](./.agents/skills/linkedin-cli/SKILL.md)이며, `skills/`, `.claude/skills/`, `.codex/skills/`는 이 skill로 연결된 project-local 심볼릭 링크입니다. 플러그인으로도 같은 skill을 설치할 수 있습니다([`.claude-plugin/plugin.json`](./.claude-plugin/plugin.json)). 플러그인은 skill만 제공하므로, skill을 처음 쓸 때 `linkedin-cli` 명령이 없으면 [`scripts/ensure-cli.sh`](./.agents/skills/linkedin-cli/scripts/ensure-cli.sh)가 `agent-linkedin`을 자동 설치합니다(`uv` 또는 `pipx`가 먼저 설치돼 있어야 합니다). 그 뒤 `auth login` → `auth-status`로 read 인증을 확인합니다.

- [`SKILL.md`](./.agents/skills/linkedin-cli/SKILL.md) — skill entrypoint
- [initial-setup.md](./.agents/skills/linkedin-cli/references/initial-setup.md) — 첫 셋업과 OAuth/쿠키 인증
- [command-cookbook.md](./.agents/skills/linkedin-cli/references/command-cookbook.md) — 정확한 명령 패턴과 JSON 사용
- [auth-troubleshooting.md](./.agents/skills/linkedin-cli/references/auth-troubleshooting.md) — 세션 복구와 진단
- [write-workflows.md](./.agents/skills/linkedin-cli/references/write-workflows.md) — 공식 발행과 안전한 mutation

## 개발

```bash
uv sync --extra dev
uv run playwright install chromium
uv run ruff check .
uv run pytest -q
uv run python -m compileall linkedin_cli tests
```

테스트 규칙:

- Unit test는 live LinkedIn session에 의존하지 않아야 합니다.
- 네트워크에 민감한 동작은 transport/browser abstraction 뒤에 둡니다.
- 릴리스 전 live verification은 유용하지만 일반 CI의 필수 조건으로 두지 않습니다.

## 보안

- cookie, OAuth token, HAR file, browser storage state를 commit하지 않습니다.
- `LINKEDIN_COOKIE_HEADER`, `li_at`, `JSESSIONID`, `~/.config/linkedin/cookies.env`, access token, client secret, token file을 issue나 PR에 붙이지 않습니다.
- screenshot, log, terminal transcript를 공유하기 전에 secret을 제거합니다.

[SECURITY.md](.github/SECURITY.md)를 참고하세요.

## 기여

아래 문서를 먼저 읽어주세요.

- [CONTRIBUTING.md](.github/CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](.github/CODE_OF_CONDUCT.md)
- [SECURITY.md](.github/SECURITY.md)
- [CHANGELOG.md](./CHANGELOG.md)

## 라이선스

MIT. [LICENSE](./LICENSE)를 참고하세요.

## 감사

`linkedin-cli`는 Juan Francisco Lebrero의 [`frizynn/linkedin-cli`](https://github.com/frizynn/linkedin-cli)에서 시작했습니다. 이 fork는 공식 LinkedIn OAuth publishing, JSON contract layer, Python write API, Codex/Claude skill packaging을 추가합니다. 원본 작업은 MIT 라이선스이며 copyright는 [LICENSE](./LICENSE)에 보존되어 있습니다.
