# Ralph loop

An **attended** autonomous coding loop for `ctx`. It re-spawns a fresh `claude`
headless session for each task in a PRD until the PRD is complete — progress lives
in the PRD file, `PROGRESS.md`, and git history (the technique from Geoffrey
Huntley's "Ralph Wiggum loop").

## Files
- `loop.sh` — the orchestrator (branch guard, iteration cap, completion detection).
- `PROMPT.md` — the recurring instruction handed to each fresh session.
- `PRD.template.md` — copy to `PRD.md` and fill in right-sized tasks.
- `PROGRESS.md` — append-only memory across iterations.

## How to run
1. Create a feature branch — the loop refuses to run on `main`/`develop`:
   ```
   git switch -c feat/my-feature
   ```
2. Copy the template and write your tasks:
   ```
   cp scripts/ralph/PRD.template.md scripts/ralph/PRD.md
   ```
   Each task must fit one fresh session and carry a concrete acceptance criterion.
3. Run, attended:
   ```
   scripts/ralph/loop.sh                 # uses scripts/ralph/PRD.md, cap 10
   scripts/ralph/loop.sh path/to/PRD.md 6
   ```

## What each iteration does
Picks the topmost unchecked task, implements just that, runs `scripts/check.sh`
(ruff + mypy + pytest — the **back pressure**), delegates behavioral checks to the
`qa-tester` subagent (real app via the `ctx-agent` MCP server), commits only on
green, ticks the task in the PRD, and appends to `PROGRESS.md`. When all tasks are
`- [x]` it prints `RALPH_COMPLETE` and the loop exits.

## Guardrails
- Branch guard (no `main`/`develop`), hard iteration cap, commit-only-on-green.
- Fresh context per iteration prevents hallucination accumulation.
- The loop stops if `claude` exits non-zero so you can review.

**Start attended.** Watch the first runs and confirm the gate actually rejects bad
changes before considering longer unattended runs. The stronger the back pressure
(notably the planned Pilot-driven pytest layer — see `tests/README.md`), the more
you can trust it.
