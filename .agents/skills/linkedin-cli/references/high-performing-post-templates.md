# High-Performing Korean LinkedIn Story Templates

Use this file when drafting or reviewing Korean LinkedIn posts, especially
builder notes, AI workflow posts, CLI/tooling stories, saved-post analysis, and
operator essays.

Do not copy source posts verbatim. Use the observed posts to infer structure,
pacing, evidence, and story shape. Keep source facts verified before publishing.

## Data Basis

Local sources checked on 2026-06-15:

- Skim DB: `/Users/seungwonan/Dev/3-tool/skim/data/skim.db`
- LinkedIn rows in `posts`: 2,549
- Korean-content LinkedIn rows: 2,145
- Saved LinkedIn backup:
  `/Users/seungwonan/Library/Mobile Documents/iCloud~md~obsidian/Documents/llm-wiki/raw/personal/linkedin-saved-posts/20260615-070311/saved-posts.jsonl`
- Saved backup rows: 1,568
- Skim rows overlapping saved-post IDs: 109
- PDF reference folder:
  `/Users/seungwonan/Library/Mobile Documents/com~apple~CloudDocs/PDF`

Reaction score:

```text
reaction_score = likes + comments * 4 + reposts * 8
```

Korean story score used for inspection:

```text
korean_story_score =
  reaction_score
  + story-marker bonus
  + author-consistency bonus
  + saved-overlap bonus
```

Story markers used only as a rough screen:

- personal scene: `저는`, `제가`, `지난`, `어제`, `오늘`, `처음`
- tension: `문제`, `실수`, `한계`, `답답`, `위험`, `하지만`, `그런데`
- transformation: `예전`, `지금`, `결과`, `줄었`, `바뀌`, `만에`, numbers
- system: `시스템`, `구조`, `워크플로우`, `원칙`, `가이드`, `에이전트`
- proof: concrete names, tools, companies, counts, artifacts, links, repos

## Core Finding

The strongest Korean LinkedIn posts are not technical explanations.

They are small stories with a strong operating lesson:

```text
일어난 일
-> 왜 이상했는지
-> 내가 무엇을 바꿨는지
-> 그 결과 어떤 관점이 생겼는지
-> 독자가 가져갈 수 있는 원칙
```

For Aiden, this means a `linkedin-cli` post should not start with CLI features,
OAuth, command groups, or scraping boundaries. Start with the human situation:

- saved posts piled up
- useful ideas became hard to find
- AI could not read what the human had saved
- a CLI was built to pull that knowledge into the local workflow
- a LinkedIn automation warning forced the product boundary to become explicit

## Korean Top Signal

Top Korean posts by story-weighted score, deduped structurally:

| Rank | Pattern | What made it work | Use for Aiden |
|---:|---|---|---|
| 1 | Authority + provocative thesis | Credible background, hard claim, then system proof | Use when making a strong claim about AI workflows |
| 2 | Before/after workflow compression | Old time, new time, error source, specialist-agent system | Use when showing saved-post cleanup or AI knowledge reuse |
| 3 | Practical checklist with high pain | Clear pain, exact file/tool, numbered usage | Use only after the story earns the checklist |
| 4 | Non-expert transformation | Zero-baseline protagonist, concrete result after a short time | Use for education and workshop posts |
| 5 | Build log with real cost | Time, constraint, usage limit, money, fatigue, artifact | Use for development diaries |
| 6 | Problem-to-system essay | Broken approach, why it fails, new operating model | Use for CLI/product thesis |
| 7 | Resource giveaway with origin | Why the resource was made, who needed it, what is inside | Use for templates or open docs |
| 8 | Market movement from field scene | Event/meeting/community scene, then broader read | Use when tying tool work to AX/agent trends |

The best-performing Korean examples usually contain at least four of these:

- specific protagonist
- uncomfortable problem
- visible artifact
- quantified or named proof
- changed belief
- short paragraph rhythm
- practical takeaway

## Author Consistency Signal

Single viral posts are noisy. For drafting defaults, prioritize authors who
posted repeatedly and still averaged strong reactions.

| Author | Korean posts | Avg score | 500+ hits | 1,000+ hits | Structural lesson |
|---|---:|---:|---:|---:|---|
| Jeongmin Lee | 40 | 487.1 | 10 | 8 | Practical AI/operator posts with saved-resource framing |
| Seungpil Lee | 31 | 346.2 | 6 | 4 | External signal + simple explanation + why it matters |
| Goobong Jeong | 53 | 227.9 | 6 | 2 | Community/movement framing and reflective operator thesis |
| 한성국 | 17 | 541.4 | 4 | 2 | Tool education, checklists, direct usage value |
| Jiin Lee | 8 | 721.0 | 2 | 2 | Non-expert transformation and resource origin story |
| Seeyong Lee | 14 | 295.9 | 2 | 1 | Complex system explained through decision structure |
| Kyunghun Lee | 15 | 263.0 | 2 | 1 | Organization-level AI adoption framed as a mistake/turning point |
| 조여준 Ethan Cho | 25 | 179.8 | 2 | 1 | Emotional market reflection with a clear human stance |

Interpretation:

- `Resource/checklist` is frequent, but it can become shallow if it starts as
  a lead magnet.
- `Authority thesis` and `before/after system` have stronger average scores.
- `Build log + consequence` is the best fit for Aiden's `linkedin-cli` story.
- The most durable format is not "I built a tool." It is "I hit a real workflow
  problem, built around it, then learned where the boundary is."

## Pattern Distribution

Heuristic scan of the top 100 Korean reaction-ranked posts:

| Signal | Count | Median read |
|---|---:|---|
| Listicle/explainer | 68 | Works for saved value, but needs a strong first line |
| Resource/checklist | 46 | Performs well when the resource is concrete |
| Problem/tension | 46 | Needed for comments and dwell time |
| Field scene | 46 | Gives credibility and makes the post feel lived |
| Market movement | 41 | Works when tied to a concrete observation |
| Build log | 37 | Strong fit for developer/tooling posts |
| Authority thesis | 12 | Less frequent, higher average score |
| Before/after system | 7 | Less frequent, highest average score among story formats |

Primary structure estimate in the same cohort:

| Primary format | Count |
|---|---:|
| Resource/checklist | 32 |
| Authority thesis | 12 |
| Problem-to-system | 11 |
| Scene build log | 10 |
| Market movement | 9 |
| Build log | 8 |
| Before/after system | 7 |
| Listicle/explainer | 3 |
| Other | 8 |

Draft implication:

- Use listicles for follow-up posts, not the first story post.
- Use resource/checklist only after explaining why the resource had to exist.
- Use before/after or build-log structure when the post is about a tool you made.

## PDF Cross-Check

This is a synthesis from local writing/storytelling PDFs, not a quote bank.

| Source | Relevant principle | LinkedIn writing implication |
|---|---|---|
| `무기가_되는_글쓰기_ocr.pdf` | Readers scan the top first; product description alone does not persuade; the customer journey matters | Do not open with feature lists. Put the strange event or user pain at the top |
| `일_잘하는_사람은_글을_잘_씁니다_ocr.pdf` | Know the reader, use easy structure, add story when persuasion is needed | A LinkedIn post needs a reader-facing reason, not just a maker-facing explanation |
| `스토리_설계자_ocr.pdf` | Customers are not primarily interested in the seller; message must enter the customer's desire/problem | Make the reader feel "this is my saved-post/AI workflow problem" |
| `무조건_팔리는_스토리_마케팅_기술_100_ocr.pdf` | Unexpected events move emotion; a story needs protagonist and obstacle | The LinkedIn warning screenshot is a hook, but the obstacle is the platform boundary |
| `Ship-30-for-30-KOR.pdf` | Publish repeatedly, observe data, increase specificity, define audience | Use repeated post feedback; write for AI builders/operators, not everyone |
| `Dont Be Such a Scientist.epub` | Narrative begins when a problem appears; plain information is weaker than problem-solution movement | Use ABT: I saved a lot AND wanted reuse, BUT AI could not read it, THEREFORE I built the CLI |
| `왜의_쓸모.pdf` | Reasons are social and contextual; the right "why" depends on the audience | Explain why this matters to builders and educators, not only why it was technically interesting |

## Template 1: Incident-Led Build Story

Best fit for the `linkedin-cli` post.

Use when there is a screenshot, warning, bug, account-risk moment, surprising
failure, or uncomfortable boundary.

```text
[Unexpected incident.]
[Short emotional reaction or action.]

사실 제가 하려던 건 [misunderstood thing]이 아니었습니다.

문제는 더 개인적이었습니다.

[Ordinary world: repeated behavior.]
[Why that behavior became a problem.]

사람은 [action]했는데,
AI는 [cannot-use state]였습니다.

그래서 [artifact/tool/workflow]를 만들기 시작했습니다.

처음 목표는 단순했습니다.
[Plain-language goal.]

그런데 만들다 보니 질문이 생겼습니다.
[Boundary question.]

기술적으로 되는 것과
해도 되는 것은 다릅니다.

그래서 이 도구의 방향은 [not automation]이 아니라
[knowledge/workflow/safety thesis]가 됐습니다.

[Final broader lesson.]
[Soft CTA for next post.]
```

Synthetic `linkedin-cli` example:

```text
링크드인을 자동화하려던 게 아니었는데,
링크드인에게 자동화 경고를 받았습니다.

처음엔 조금 웃겼고,
바로 멈췄습니다.

제가 만들던 건 DM 자동 발송 도구도 아니고,
좋아요 자동화도 아니고,
댓글 매크로도 아니었습니다.

문제는 더 개인적이었습니다.

저는 좋은 글을 너무 많이 저장합니다.
링크드인에 저장하고,
X에 저장하고,
스레드와 레딧과 유튜브에도 저장합니다.

그런데 필요할 때는 거의 못 찾습니다.

분명히 봤고,
분명히 저장했고,
언젠가 써먹으려고 했는데

정작 필요할 때는 제 머리에도 없고,
AI도 읽을 수 없습니다.

사람은 저장했는데,
AI는 못 읽는 상태.

이게 싫어서 linkedin-cli를 만들기 시작했습니다.

목표는 단순했습니다.

앱 안에 갇힌 저장글을
내 로컬 작업 환경과 AI가 다시 쓸 수 있는 형태로 꺼내오는 것.

그런데 만들다 보니 더 중요한 질문이 생겼습니다.

어디까지 자동화해도 되는가?

기술적으로 되는 것과
해도 되는 것은 다릅니다.

그래서 이 CLI의 방향도 더 분명해졌습니다.

많이 클릭하는 도구가 아니라,
내가 쌓아둔 정보를 다시 쓸 수 있게 만드는 도구.

그리고 위험한 선을 넘기 전에
멈출 줄 아는 도구.

SNS 자동화 툴을 만들고 싶은 게 아닙니다.

매일 흘려보내는 좋은 정보들을
내 AI가 다시 사용할 수 있게 만들고 싶습니다.
```

Do not add technical details before the reader cares:

- Avoid early `read.*`, OAuth, cookies, API groups, GraphQL, browser session.
- Mention implementation only as proof later: local backup, JSON/DB, search,
  summary, dry-run, guardrail.

## Template 2: Before/After System Compression

Use when a workflow got faster, safer, or more reusable.

```text
예전엔 [task] 하나에 [old cost]가 걸렸습니다.

지금은 [new cost]로 끝납니다.

차이는 [tool name]이 아니었습니다.
[operating principle]이었습니다.

문제는 [old failure mode]였습니다.

그래서 구조를 바꿨습니다.

1. [system step]
2. [system step]
3. [system step]

결과는 [measured or observed result].

제가 배운 건 이겁니다.
[portable lesson]
```

Use for Aiden:

- saved posts cleanup
- lecture proposal drafting
- AI course material reuse
- local knowledge workflows

## Template 3: Authority Thesis With Proof

Use when Aiden can speak from direct operator experience.

```text
저는 [role/context]를 하고 있습니다.

솔직하게 말하면,
[provocative but defensible claim].

과장처럼 들릴 수 있습니다.
그런데 [specific scene/proof]를 보면 생각이 달라집니다.

제가 본 문제는 [surface belief]가 아니었습니다.
[real mechanism]이었습니다.

구조는 이렇습니다.

1. [mechanism]
2. [mechanism]
3. [mechanism]

그래서 [audience]에게 필요한 건 [recommendation]입니다.
```

Good for:

- AI education philosophy
- agent workflow design
- content archive systems
- "prompt is not the product, context is" style claims

## Template 4: Non-Expert Transformation

Use for education, workshops, and student/client stories.

```text
[Audience/person]은 처음에 [zero-baseline state]였습니다.

[Concrete limitation.]

그래서 처음부터 [advanced topic]을 가르치지 않았습니다.
[first simple step]부터 했습니다.

그리고 [time period] 뒤,
[visible artifact/result]가 나왔습니다.

중요한 건 [tool]이 아니었습니다.
[changed belief or capability]였습니다.

이 사례를 보면서 배운 점은 [lesson].
```

This is the strongest education template because the protagonist is not the
teacher. The protagonist is the learner whose state changes.

## Template 5: Resource With Origin Story

Use when sharing a guide, checklist, template, or repo.

```text
[Resource]를 만들었습니다.

처음부터 공유하려고 만든 건 아니었습니다.

[Specific person/team/myself]이 계속 [problem]에서 막혀서
내부용으로 먼저 만들었습니다.

안에는 [contents]가 있습니다.

이걸 쓰면 좋은 상황:
- [situation]
- [situation]

쓰면 안 좋은 상황:
- [bad fit]

필요하신 분들을 위해 [delivery method]로 정리해두겠습니다.
```

Rule:

- Never open with "무료 배포합니다" unless the resource itself is the story.
- Open with the problem that forced the resource to exist.

## Template 6: Field Scene To Market Read

Use after events, workshops, community meetings, client sessions, or tool demos.

```text
[Specific place/event/time]에서 [scene]을 봤습니다.

겉으로 보면 [surface interpretation]처럼 보였습니다.
하지만 제가 본 건 [deeper pattern]이었습니다.

[Concrete observations.]

이게 중요한 이유는 [market/workflow implication]입니다.

앞으로 [audience]는 [new behavior]를 해야 합니다.

저는 그래서 [personal next action]을 하고 있습니다.
```

Good for:

- AX education market
- agent tooling adoption
- Korean builder community
- corporate AI workflow shifts

## Draft Review Checklist

Score every draft before publishing.

| Criterion | Pass condition |
|---|---|
| Incident | The first 2 lines contain a concrete event, artifact, result, or contradiction |
| Protagonist | Someone changes: Aiden, a student, a team, a client, or a builder |
| Obstacle | There is a real problem, boundary, risk, or friction |
| Action | The post shows what was built, changed, tested, or decided |
| Result | There is a number, artifact, screenshot, named tool, or observed change |
| Lesson | The ending gives a portable operating principle |
| Reader fit | The reader can see why this matters to their workflow |
| Restraint | Technical details appear only after the story earns them |
| Integrity | No fake scarcity, fake numbers, or copied phrasing |

Hard fail:

- It starts with a definition.
- It starts with a feature list.
- It explains implementation before the problem.
- It says "이게 중요합니다" before showing why.
- It has a hook, but no protagonist or change.

## Default Recommendation For Aiden

For Aiden's Korean LinkedIn posts, use this priority:

1. Incident-led build story for CLI/tooling/product posts.
2. Before/after system compression for workflow wins.
3. Non-expert transformation for education and workshop posts.
4. Authority thesis with proof for opinionated AI workflow posts.
5. Resource with origin story for templates, guides, repos, and checklists.
6. Field scene to market read for events and community observations.

For the `linkedin-cli` story specifically:

- Primary structure: Incident-led build story.
- Secondary structure: ABT plus STAR.
- Hook: LinkedIn automation warning screenshot.
- Real protagonist: Aiden trying to make saved knowledge usable by AI.
- Real obstacle: saved content trapped inside platforms, plus automation-risk
  boundary.
- Real artifact: `linkedin-cli` and local saved-post backup.
- Product thesis: not "automate LinkedIn", but "turn social knowledge into a
  local AI-readable workflow without crossing unsafe platform boundaries."

