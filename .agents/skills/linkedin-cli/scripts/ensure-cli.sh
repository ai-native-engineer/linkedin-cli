#!/usr/bin/env bash
# Ensure the `linkedin-cli` command is on PATH, installing `agent-linkedin` if missing.
# Idempotent (skips when already present) and safe (no sudo; prefers uv).
#
# Note: the PyPI dist name is `agent-linkedin`; it provides the `linkedin-cli` command.
# When working inside the repo you do not need this at all — use `uv run linkedin-cli ...`.
set -euo pipefail

if command -v linkedin-cli >/dev/null 2>&1; then
  echo "linkedin-cli already installed: $(command -v linkedin-cli)"
  exit 0
fi

# Preferred: PyPI via uv.
if command -v uv >/dev/null 2>&1; then
  if uv tool install agent-linkedin; then exit 0; fi
fi

# Fallback: pipx if available.
if command -v pipx >/dev/null 2>&1; then
  if pipx install agent-linkedin; then exit 0; fi
fi

# Local repo fallback (covers offline / pinned index cutoff / pre-propagation).
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." 2>/dev/null && pwd || true)"
if command -v uv >/dev/null 2>&1 && [ -n "${repo_root}" ] && [ -f "${repo_root}/pyproject.toml" ]; then
  if uv tool install "${repo_root}"; then exit 0; fi
fi

# Remote repo fallback.
if command -v uv >/dev/null 2>&1; then
  if uv tool install "git+https://github.com/ai-native-engineer/linkedin-cli"; then exit 0; fi
fi

echo "ERROR: could not install linkedin-cli. Install uv (https://docs.astral.sh/uv/)," >&2
echo "       or run inside the repo with 'uv run linkedin-cli'." >&2
exit 1
