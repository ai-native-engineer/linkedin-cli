@AGENTS.md

## Claude Code

The project skill auto-loads from `.claude/skills/` (symlink to `.agents/skills/`): `linkedin-cli`.
Codex uses the mirrored project-local alias in `.codex/skills/`; both point to the same
`.agents/skills/linkedin-cli` source. Use it for setup, auth, read, and write workflows. The same
skill ships as a Claude plugin via `.claude-plugin/plugin.json`.
