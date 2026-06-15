# LinkedIn Terms and Automation Guardrail

Use this template when a LinkedIn workflow involves unofficial reads, browser automation, scraping,
bulk cleanup, saved-post draining, or account-risk warnings.

## Official References

- LinkedIn User Agreement: https://www.linkedin.com/legal/user-agreement
- LinkedIn prohibited software and extensions: https://www.linkedin.com/help/linkedin/answer/a1341387

## Short Assessment Template

```md
## LinkedIn automation risk assessment

- Workflow: <read/feed/saved-post cleanup/posting/commenting/etc.>
- Surface: <official API / unofficial browser session / Playwright fallback / manual UI>
- Volume: <single action / small sample / repeated loop / bulk operation>
- Current account state: <normal / authwall / checkpoint / automation warning / restriction warning>
- Credentials handling: <no secrets printed / token from OAuth file / browser state / manual login>

### Terms risk

LinkedIn restricts scraping, bots, crawlers, browser extensions, and unauthorized automated access.
This workflow is <low / medium / high> risk because <reason>.

### Decision

- Proceed only if: <condition>
- Stop if: LinkedIn shows an automation, suspicious-activity, account-risk, checkpoint,
  restriction, or "review tools" warning.
- Fallback: <manual LinkedIn UI / official API / no action>
```

## Hard Stop Conditions

Stop all LinkedIn automation immediately if any of these appears:

- automation or suspicious-activity warning
- account-risk, checkpoint, restriction, or temporary lock warning
- "review tools" warning
- repeated login challenge, authwall, or session invalidation
- signs that the user is being asked to acknowledge automation policy compliance

When a hard stop condition appears:

1. Terminate running Playwright/browser automation processes.
2. Do not bypass the warning.
3. Do not re-login through automation.
4. Do not continue the same bulk workflow in the same session.
5. Report what was already backed up or mutated.
6. Recommend manual review in LinkedIn's official UI.

## Allowed Low-Risk Pattern

- Official LinkedIn API commands with OAuth.
- `--dry-run --json` before generated publishing or mutations.
- One-off read or mutation when the user explicitly asks and the session is healthy.
- Low-frequency manual-support workflow where the user performs final action in the official UI.

## Disallowed Pattern

- Bulk saved-post draining or bulk unsave through browser automation.
- Repeated browser page loops that click LinkedIn controls.
- Scraping many posts, comments, profiles, or reactions through a logged-in web session.
- Continuing after LinkedIn displays an automation or restriction warning.
- Printing cookies, tokens, passwords, or browser storage state while debugging.

## Recommended User-Facing Response Template

```md
LinkedIn displayed an automation/account-risk warning, so I stopped the automation.

What I did:
- Stopped running browser automation processes.
- Preserved the local backup created so far at `<path>`.
- Did not attempt to bypass the warning or re-login through automation.

Why:
- LinkedIn's User Agreement and Help Center restrict scraping, bots, browser extensions, and
  unauthorized automated access.
- Continuing may increase the risk of account restriction.

Next safe step:
- Use LinkedIn's official UI manually.
- If an official API path exists for the exact task, review that separately before proceeding.
```
