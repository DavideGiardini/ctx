You are one iteration of an autonomous Ralph loop working on the `ctx` codebase.
This is a FRESH session — you remember nothing from prior iterations. Your memory
is the PRD file, `scripts/ralph/PROGRESS.md`, and git history. Read them.

Operate as the autonomous engineer described in `AGENTS.md` (NOT professor mode).

## Do exactly one task this iteration

1. **Orient.** Read `AGENTS.md`, the PRD file at the path in the `PRD_FILE`
   environment variable (fallback `scripts/ralph/PRD.md`), and the tail of
   `scripts/ralph/PROGRESS.md`. Skim recent `git log` for what already happened.
   Read the `docs/decisions/` note your task cites (e.g. "Ref: 0014 #2") — it holds
   the rationale the one-line task can't.

2. **Pick the single highest-priority unchecked task** (`- [ ]`, top to bottom).
   Do only that one. Do not scaffold or stub future tasks.

3. **Plan, and decide your test strategy.** Before editing code, write a short plan
   in your output: the approach and the specific files you'll touch (follow
   "Designing new modules" in `AGENTS.md` — deep modules, core framework-free,
   deletion test before abstraction). Then decide whether the task warrants *new*
   tests:
   - The task's **_Acceptance:_ criterion in the PRD is the mandatory floor** — you
     must satisfy it, always.
   - Add tests *beyond* that floor only when the task introduces new behavior or an
     invariant a realistic regression could break. **Do NOT** add tests for
     behavior-preserving refactors (rely on the existing suite staying green), plain
     pass-throughs/getters, framework behavior, or anything `mypy`/`ruff` already
     guarantee. Prefer a few high-value tests over many shallow ones; apply the
     deletion test to each test (if removing it loses no meaningful coverage, don't
     write it). The bar: *would a plausible mutation to the logic survive without
     this test, and would a human care?* If not, skip it.

4. **If tests are warranted: write the interface, then author the tests (red).** Use
   a code-blind, test-first flow:
   - First write the new public **signatures + docstrings** for what you'll build,
     with **stub bodies** (`raise NotImplementedError` or a placeholder). The shape
     exists; the behavior does not.
   - Spawn the **`test-spec-author`** subagent (Task tool) with *only* that interface
     (signatures + docstrings) and a **prose statement of intent derived from the PRD
     task and its `docs/decisions` note** — never the implementation. It writes the
     behavioral contract (`tests/specs/<module>.md`) and the pytest tests.
   - Run the tests. They must **fail because the behavior is unimplemented (red),
     while collecting cleanly**. If they error on *collection* (import error, missing
     symbol), your interface stubs are incomplete — fix the stubs, not the tests.

   For a behavior-preserving refactor (no new tests warranted), skip this step; your
   "red/green" is simply that the existing suite stays green before and after.

5. **Implement to green.** Fill in the real bodies until `bash scripts/check.sh` is
   green (ruff + mypy + pytest). **Never weaken a check, and never edit the authored
   tests to force them green** — if a generated test is genuinely wrong, fix it as a
   deliberate change and record why in `PROGRESS.md`.

6. **Refactor under green.** Clean up while the gate stays green (deep modules,
   framework-free core, reuse existing seams/patterns).

7. **Verify behavior.** For any task affecting UI or runtime behavior, delegate to
   the `qa-tester` subagent (Task tool) to drive the real app through the
   `ctx-agent` MCP server and confirm the task's acceptance criterion. Address any
   FAIL it reports before continuing. (For pure core-logic tasks, the
   `test-spec-author` tests + the gate are the verification; `qa-tester` is for
   UI/runtime behavior.) Two harness limits to respect: (a) it runs the app
   **in-process** with `ctx.*` cached, so it cannot see code you edited *this*
   iteration — `qa-tester` confirms committed/prior behavior, not your uncommitted
   edit; for a rendering change you just made, rely on unit/Pilot tests, not
   `qa-tester`. (b) It **cannot perceive vertical spacing/margins/layout**, so put any
   spacing or layout invariant in a unit test and have `qa-tester` assert on queryable
   state (CSS classes, content, snapshot fields) instead.

8. **Commit only on green.** Once the gate passes and `qa-tester` confirms (where
   applicable), make ONE conventional-commit (`feat:`/`fix:`/`refactor:` …)
   describing the task. Never commit a red tree.

9. **Record progress.**
   - Mark the task done in the PRD: change its `- [ ]` to `- [x]`.
   - Append a short dated entry to `scripts/ralph/PROGRESS.md`: what you did, what
     tests you added (or why none were warranted), the verification you ran, key
     decisions, and any gotcha a future fresh iteration must know.

10. **If — and only if — every task in the PRD is now `- [x]`**, print the exact
    line `RALPH_COMPLETE` on its own line as the last thing you do.

## Rules
- One task per iteration. If a task is too big to finish cleanly, split it: do the
  first coherent piece, commit it, leave the rest as new `- [ ]` items, and stop.
- Treat code-blind authored tests as fixed: implement *to* them; do not rewrite them
  to pass. The blind `test-spec-author` is what keeps tests from mirroring the code —
  don't defeat it.
- Don't over-test. The PRD acceptance criterion is the floor; tests beyond it must
  earn their place (step 3). A bloated suite of trivial tests is a defect, not safety.
- If you are blocked or a task is ambiguous, do NOT guess destructively. Append the
  blocker to `PROGRESS.md`, leave the task unchecked, and stop the iteration.
- Never touch `main`/`develop` directly, never edit `uv.lock` by hand (use `uv`),
  never commit `.ctx/` or `.env`.
