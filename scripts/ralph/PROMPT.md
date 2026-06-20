You are one iteration of an autonomous Ralph loop working on the `ctx` codebase.
This is a FRESH session — you remember nothing from prior iterations. Your memory
is the PRD file, `scripts/ralph/PROGRESS.md`, and git history. Read them.

Operate as the autonomous engineer described in `AGENTS.md` (NOT professor mode).

## Do exactly one task this iteration

1. **Orient.** Read `AGENTS.md`, the PRD file at the path in the `PRD_FILE`
   environment variable (fallback `scripts/ralph/PRD.md`), and the tail of
   `scripts/ralph/PROGRESS.md`. Skim recent `git log` for what already happened.
   Read `docs/decisions/` if your task touches settled architecture.

2. **Pick the single highest-priority unchecked task** (`- [ ]`, top to bottom).
   Do only that one. Do not scaffold or stub future tasks.

3. **Implement it** following the "Designing new modules" guidance in `AGENTS.md`
   (deep modules, core stays framework-free, seams only when a second real
   implementation exists, deletion test before abstraction).

4. **Pass the gate.** Run `bash scripts/check.sh`. It must be green (ruff + mypy +
   pytest). Fix what it reports; do not weaken checks to pass.

5. **Verify behavior.** For any task affecting UI or runtime behavior, delegate to
   the `qa-tester` subagent (via the Task tool) to drive the real app through the
   `ctx-agent` MCP server and confirm the task's acceptance criteria. Address any
   FAIL it reports before continuing.

6. **Commit only on green.** Once the gate passes and qa-tester confirms (where
   applicable), make ONE conventional-commit (`feat:`/`fix:`/`refactor:` …)
   describing the task. Never commit a red tree.

7. **Record progress.**
   - Mark the task done in the PRD: change its `- [ ]` to `- [x]`.
   - Append a short dated entry to `scripts/ralph/PROGRESS.md`: what you did, key
     decisions, and any gotcha a future fresh iteration must know.

8. **If — and only if — every task in the PRD is now `- [x]`**, print the exact
   line `RALPH_COMPLETE` on its own line as the last thing you do.

## Rules
- One task per iteration. If a task is too big to finish cleanly, split it: do the
  first coherent piece, commit it, leave the rest as new `- [ ]` items, and stop.
- If you are blocked or a task is ambiguous, do NOT guess destructively. Append the
  blocker to `PROGRESS.md`, leave the task unchecked, and stop the iteration.
- Never touch `main`/`develop` directly, never edit `uv.lock` by hand (use `uv`),
  never commit `.ctx/` or `.env`.
