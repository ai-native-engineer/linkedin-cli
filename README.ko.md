# linkedin-cli

[English](./README.md) | [한국어](./README.ko.md)

개인 LinkedIn 워크플로우를 위한 AI-native CLI입니다.

`linkedin-cli`는 두 표면을 명확히 분리합니다.

- `read.*`: 본인 LinkedIn 웹 세션을 사용하는 비공식 읽기 워크플로우
- `post.*`: LinkedIn OAuth와 공식 LinkedIn API를 사용하는 공식 쓰기 워크플로우

태그: `linkedin`, `cli`, `sns-json-v1`, `unofficial-read`, `official-post`, `personal-workflow`

> 이 프로젝트는 LinkedIn과 무관합니다. 읽기 명령은 비공식 웹 동작에 의존하며, LinkedIn 내부 엔드포인트가 바뀌면 깨질 수 있습니다. 계정에 적용되는 약관은 사용자가 직접 검토해야 합니다.

## 기능

읽기:

- 홈 피드 읽기
- 저장한 게시글 읽기
- 프로필 조회
- 사람/게시글 검색
- 특정 프로필의 게시글 조회
- 단일 activity 조회
- 에이전트, 스크립트, SNS CLI ecosystem 소비용 `sns-json-v1` JSON 출력

쓰기:

- 실제 발행 전 공식 게시 payload dry-run
- 공식 LinkedIn Posts API로 텍스트 게시
- LinkedIn Images + Posts API로 로컬 이미지 1개 게시
- article/link 게시
- 기존 게시글 재공유
- 게시글 commentary 수정
- 토큰에 필요한 read 권한이 있을 때 단일 게시글 조회 및 author별 게시글 목록 조회
- share/ugcPost URN, numeric share id, feed update URL로 본인 공식 게시글 삭제
- 저장한 게시글 저장 취소
- react, unreact, save, unsave, comment, 구형 posting을 위한 legacy browser fallback 유지

## 설치

소스에서 설치:

```bash
git clone https://github.com/ai-native-engineer/linkedin-cli.git
cd linkedin-cli
uv sync --extra dev
```

로컬 tool로 설치:

```bash
uv tool install .
```

대안:

```bash
pipx install .
```

브라우저 fallback이 필요할 때만 Playwright를 설치합니다.

```bash
uv run playwright install chromium
```

## 빠른 시작

CLI 확인:

```bash
linkedin-cli --help
```

읽기 명령은 LinkedIn 웹 세션이 필요합니다. 가장 안정적인 방식은 로그인된 브라우저에서 전체 cookie header를 복사하는 것입니다.

```bash
export LINKEDIN_COOKIE_HEADER='li_at=...; JSESSIONID="ajax:..."; bcookie="..."; bscookie="..."; ...'
linkedin-cli auth-status
```

읽기 명령 실행:

```bash
linkedin-cli read feed --limit 10 --json
linkedin-cli read saved --limit 10 --json
linkedin-cli read profile seungwon-aiden --json
linkedin-cli read search "AI engineer" --limit 10 --json
```

쓰기 명령은 공식 OAuth 토큰이 필요합니다.

```bash
linkedin-cli post text --text "hello from linkedin-cli" --visibility public --dry-run --json
linkedin-cli post text --text "hello from linkedin-cli" --visibility public --json
linkedin-cli post media --text "hello with image" --media image.png --visibility public --json
linkedin-cli post article --text "read this" --url https://example.com/post --dry-run --json
linkedin-cli post reshare urn:li:share:1234567890 --text "worth reading" --dry-run --json
linkedin-cli post update urn:li:share:1234567890 --text "updated text" --dry-run --json
linkedin-cli post get urn:li:share:1234567890 --json
linkedin-cli post list --count 10 --json
linkedin-cli post delete urn:li:share:1234567890 --dry-run --json
linkedin-cli post delete urn:li:share:1234567890 --json
```

긴 글이나 생성된 글은 inline text보다 파일 입력을 권장합니다.

```bash
linkedin-cli post text --text-file draft.md --visibility public --dry-run --json
linkedin-cli post text --text-file draft.md --visibility public --json
```

## 공식 OAuth 토큰 발급

공식 `post.*` 명령은 LinkedIn Developer app과 `w_member_social` 권한이 있는 access token이 필요합니다.

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
linkedin-cli auth oauth-login --json
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

`auth_expired`

- `linkedin-cli auth oauth-login`을 다시 실행합니다.

공식 참고 문서:

- LinkedIn OAuth 2.0 Authorization Code Flow: https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow
- Share on LinkedIn: https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin
- LinkedIn Posts API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api

## 읽기 인증

읽기 인증은 공식 쓰기 OAuth와 분리되어 있습니다.

해결 순서:

1. `LINKEDIN_COOKIE_HEADER`
2. `LINKEDIN_LI_AT` + `LINKEDIN_JSESSIONID`
3. Chrome, Chromium, Brave, Edge, Firefox의 브라우저 cookie 추출

전체 cookie header:

```bash
export LINKEDIN_COOKIE_HEADER='li_at=...; JSESSIONID="ajax:..."; ...'
linkedin-cli auth-status
```

최소 cookie 변수:

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
export LINKEDIN_BROWSER_STATE="$HOME/.config/linkedin-cli/browser-state.json"
```

## 명령 레퍼런스

표준 JSON 명령:

```bash
linkedin-cli auth-status
linkedin-cli auth oauth-login

linkedin-cli read feed --limit 20 --json
linkedin-cli read saved --limit 20 --json
linkedin-cli read profile seungwon-aiden --json
linkedin-cli read search "product manager" --limit 10 --json

linkedin-cli saved list --limit 20 --json
linkedin-cli saved unsave urn:li:activity:123 --json

linkedin-cli post text --text "hello" --visibility public --dry-run --json
linkedin-cli post text --text-file draft.md --visibility public --json
linkedin-cli post media --text "hello with image" --media image.png --visibility public --json
linkedin-cli post article --text "read this" --url https://example.com/post --json
linkedin-cli post reshare urn:li:share:1234567890 --text "worth reading" --json
linkedin-cli post update urn:li:share:1234567890 --text "updated text" --json
linkedin-cli post get urn:li:share:1234567890 --json
linkedin-cli post list --count 10 --json
linkedin-cli post delete urn:li:share:1234567890 --dry-run --json
linkedin-cli post delete urn:li:share:1234567890 --json
```

Legacy 호환 명령:

```bash
linkedin-cli search "product manager" --max 10
linkedin-cli profile seungwon-aiden --json
linkedin-cli profile-posts seungwon-aiden --max 20
linkedin-cli activity urn:li:activity:123
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

## Skills와 Plugin

이 repo는 project-local skill을 포함합니다.

- [`skills/linkedin-cli`](./skills/linkedin-cli)
- [`skills/linkedin-cli-auth`](./skills/linkedin-cli-auth)
- [`skills/linkedin-cli-write`](./skills/linkedin-cli-write)

Claude plugin manifest는 [`.claude-plugin/plugin.json`](./.claude-plugin/plugin.json)에 있습니다.

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
- `LINKEDIN_COOKIE_HEADER`, `li_at`, `JSESSIONID`, access token, client secret, token file을 issue나 PR에 붙이지 않습니다.
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
