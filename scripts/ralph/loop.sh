#!/usr/bin/env bash
# Attended Ralph loop for ctx.
#
# Each iteration is a FRESH `claude` headless session. Durable state lives in the
# PRD file, PROGRESS.md, and git history — never in a context window. The loop
# keeps re-spawning the agent until every PRD task is checked, a completion
# sentinel is printed, or the iteration cap is hit.
#
# Usage:
#   scripts/ralph/loop.sh [PRD_FILE] [MAX_ITERS] [MODEL]
#     PRD_FILE   task list to work through   (default: scripts/ralph/PRD.md)
#     MAX_ITERS  hard cap on iterations       (default: 10)
#     MODEL      model passed to `claude --model`  (default: opus)
#
# This is meant to be run ATTENDED, especially the first times — watch the runs,
# confirm the gate (scripts/check.sh) actually catches bad changes, and only
# trust it unattended once the back pressure is proven.
set -euo pipefail

cd "$(dirname "$0")/../.."  # repo root

PRD="${1:-scripts/ralph/PRD.md}"
MAX_ITERS="${2:-10}"
MODEL="${3:-opus}"
PROMPT_FILE="scripts/ralph/PROMPT.md"
SENTINEL="RALPH_COMPLETE"

# Tools the agent may use without a prompt (headless mode denies the rest).
# The ctx-agent MCP tools are already allowlisted in .claude/settings.local.json.
ALLOWED_TOOLS=(Read Edit Write Grep Glob Bash Task)

# --- Guardrails --------------------------------------------------------------
command -v claude >/dev/null || { echo "error: 'claude' CLI not found on PATH." >&2; exit 1; }
[ -f "$PROMPT_FILE" ] || { echo "error: missing $PROMPT_FILE" >&2; exit 1; }

branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$branch" = "main" ] || [ "$branch" = "develop" ]; then
  echo "error: refusing to run on '$branch'. Create a feature branch first:" >&2
  echo "       git switch -c feat/<your-feature>" >&2
  exit 1
fi

[ -f "$PRD" ] || { echo "error: PRD file '$PRD' not found. Copy scripts/ralph/PRD.template.md and fill it in." >&2; exit 1; }

unchecked() { grep -cE '^[[:space:]]*- \[ \]' "$PRD" || true; }

echo "Ralph loop starting on branch '$branch'"
echo "  PRD: $PRD  ($(unchecked) open task(s))"
echo "  max iterations: $MAX_ITERS"
echo "  model: $MODEL"
echo

# --- Loop --------------------------------------------------------------------
for ((i = 1; i <= MAX_ITERS; i++)); do
  remaining="$(unchecked)"
  if [ "$remaining" -eq 0 ]; then
    echo "==> All PRD tasks checked. Done."
    exit 0
  fi

  echo "==================== iteration $i/$MAX_ITERS ($remaining task(s) left) ===================="

  # Fresh session each time; PROMPT.md tells it to do exactly one task.
  if PRD_FILE="$PRD" claude -p "$(cat "$PROMPT_FILE")" \
       --allowedTools "${ALLOWED_TOOLS[@]}" \
       --model "$MODEL" \
       2>&1 | tee /tmp/ralph-last-iter.log; then
    :
  else
    echo "==> claude exited non-zero on iteration $i. Stopping for review." >&2
    exit 1
  fi

  # Honor the sentinel only when it's on its own line (PROMPT.md: "print the exact
  # line RALPH_COMPLETE on its own line") AND the PRD truly has no unchecked tasks —
  # otherwise an agent merely *mentioning* the sentinel in prose ends the loop early.
  if grep -qE "^[[:space:]]*${SENTINEL}[[:space:]]*$" /tmp/ralph-last-iter.log \
     && [ "$(unchecked)" -eq 0 ]; then
    echo "==> Agent signalled $SENTINEL and all PRD tasks are checked. Done."
    exit 0
  fi
  echo
done

echo "==> Hit iteration cap ($MAX_ITERS) with $(unchecked) task(s) still open." >&2
echo "    Review git log + PROGRESS.md, then re-run to continue." >&2
exit 2
