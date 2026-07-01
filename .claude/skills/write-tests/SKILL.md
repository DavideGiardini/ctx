---
name: write-tests
description: Author high-quality unit tests for a framework-free ctx core module using a code-blind, contract-first pipeline that resists implementation-coupling ("self-validating" tests). Use when the user wants to "write tests for <module>", "add unit tests", or "test ctx/core/<x>". Orchestrates the code-blind test-spec-author subagent, drives a coverage loop, and gates quality with mutmut. Produces tests/specs/<module>.md + tests/test_<module>.py. Does NOT cover the Textual UI (that's the qa-tester / Pilot layer).
---

# Write Tests (contract-first, code-blind)

Author unit tests whose oracle ("what is correct") comes from **intent**, with
objective evidence (mutmut) that the tests actually catch faults. You are the
**orchestrator**: you are the only one allowed to read the implementation, and you
read it for exactly two reasons — to extract the interface to hand the blind agent,
and to *route* coverage/mutation gaps. You never let the implementation become the
source of an assertion's expected value.

## Why this shape
The default failure of AI-written tests is **self-validating tests**: read the code,
assert what it currently does, bake bugs in as "expected behavior." Three orthogonal
layers defend against it, each catching a different failure:

| Layer | Question | Owned by |
|---|---|---|
| Code-blind contract | Are we asserting the **right** thing? | `test-spec-author` (no read tools) |
| Coverage loop | Did we **execute** every branch? | you, routing gaps as *intent questions* |
| mutmut | Is the oracle **strong** enough to catch faults? | `scripts/mutate.sh` + human triage |

## Scope
Framework-free core only: `ctx/core/*`, `ctx/models/*`, `tools/agent/snapshot.py`.
**Not** `ctx/ui/*` — Textual UI behavior is the `qa-tester` / Pilot-driven layer.
One module per invocation. Reuse `tests/conftest.py` fixtures; don't rebuild them.

## Procedure

### 1. Extract the interface (orchestrator reads code)
Read the target module. Pull out **signatures + type hints + docstrings + import
paths** and the conftest fixtures relevant to it. Write a short prose **intent**
statement: what the module is for, its domain concepts, the behaviors it must
guarantee, and the errors it must raise and when. **Do not copy function bodies** —
not into the intent, not into the agent prompt.

### 2. Contract (spawn the blind agent — Task A)
Spawn `test-spec-author` with the interface + intent + fixture list. It returns a
numbered behavioral contract and a list of intent ambiguities it had to assume past.

### 3. Adjudicate the contract (human gate)
Review with the user. Resolve every flagged ambiguity. Sanity-check that each item's
**Expect** reads as intent, **not** a restatement of code. Save the agreed contract to
`tests/specs/<module>.md` with stable ids (C1, C2, …). This is the oracle of record.

### 4. Author tests (spawn the blind agent — Task B)
Give the agent the adjudicated contract + interface + fixtures. The agent writes
`tests/test_<module>.py` **directly** — the project grants it `Write(tests/**)` (scoped
to tests only; it still has no read tools, so it stays blind). Permission rules load at
**session start**, so if the agent's Write is denied, this session predates the rule —
restart the session to enable direct-write (preferred), or use the fallback below.

**Fallback (Write denied):** the agent returns the full content as text and **you persist
those bytes verbatim** to `tests/test_<module>.py`. Two cautions, because the message
transport is lossy:
- It may HTML-escape `<`→`&lt;`, `>`→`&gt;`, `&`→`&amp;` across the *whole* payload (not
  just comments). Decoding these back to their real characters is **allowed** — you are
  recovering the agent's true bytes, not editing (the agent authored `>`, not `&gt;`).
- After persisting, **verify the file is intact** before trusting it:
  `grep -nE '&(gt|lt|amp|quot|#x?[0-9a-fA-F]+);' tests/test_<module>.py` (expect none) and
  `uv run python -m py_compile tests/test_<module>.py` (must pass). A leftover entity or a
  `SyntaxError` means the decode was incomplete — fix the *transport artifact*, re-verify.

Either way the test code is the blind agent's: you do **not** author or edit assertions.
Verbatim means verbatim — no fixing, tweaking, or "cleaning up" while saving. Anything
that needs a real change goes back to the blind agent (step 5).

### 5. Coverage / failure loop (orchestrator routes everything back to the blind agent)
**The orchestrator never edits test code.** You may *see* the implementation and the
test output, but you must not type or change an assertion — that is the one step where
the implementation could leak into the oracle. Every change to a test is made by the
blind agent, fed only intent.

Run coverage, e.g.:
`uv run coverage run --branch --source=<module> -m pytest tests/test_<module>.py && uv run coverage report -m`
(pytest-cov is not installed; use the `coverage` package that ships with mutmut.)

For each uncovered line/branch **and each failing test**, re-pose it to a fresh blind
invocation as a behavior question — *"What should happen when <situation in domain
terms>?"* — **never** describing what the code does or what value it produced. The blind
agent updates the contract item and rewrites its tests (it has `Write`; it regenerates
the test file from the corrected contract). Each item resolves to one of:
- **intended-but-untested** → add/correct a contract item + test;
- **wrong oracle** → a test failed because the *contract item* was wrong (not the code);
  correct the contract from intent and have the blind agent rewrite the test;
- **accidental / dead code** → flag it to the user (maybe delete the code);
- **a real bug** → the code violates the (correct) contract. This is a *finding*, not
  something to fix here (see below).

When a test fails, decide *from intent* whether the code or the oracle is wrong — with
equal skepticism toward both. If the oracle was wrong, fix the **contract** and route the
rewrite to the blind agent; do not hand-edit the test to match observed output. If a gap
or fix can *only* be expressed by describing the code, that is the leak signal — stop and
find the intent.

**A test session NEVER modifies production code.** A confirmed real bug is *quarantined
and logged*, not fixed:
1. Keep the (correct) failing test, marked
   `@pytest.mark.xfail(reason="BUG: <one line> — contract <Cn>; see tests/specs/FOUND-BUGS.md", strict=True)`.
   `xfail` = expected failure, so the suite is green and mutmut can run now; `strict=True`
   means the day the code is fixed the test XPASSes (a failure), forcing the marker's
   removal — the bug can't be silently forgotten. Confirm the test fails for the *expected*
   reason before marking it (don't xfail-mask a broken test).
2. Append an entry to `tests/specs/FOUND-BUGS.md` (module, contract id, expected vs actual
   behavior, the xfail test name) and add a "Contract violations found" note to the
   module's spec.
Fixing the code is a separate, human-reviewed effort done after test-writing — not part
of this pipeline.

### 6. Mutation gate (mutmut) — per module, one process at a time
**Precondition: the WHOLE test suite must be green under mutmut's own invocation.** mutmut
runs the *entire* discovered suite for its baseline (with `-x`, no test-command scoping),
so a single red test in *any* module aborts the gate for *every* module. The glob only
scopes which mutants *execute*, not the baseline. So when modules are authored in parallel,
the gate is the one step with a **global** precondition: do not run any module's gate until
all sessions' tests are green/xfail-stable. **Never relocate or edit another session's test
files** to force isolation — they own those files and may be mid-write; just wait for green.

Two order/isolation traps to know:
- mutmut runs tests in a **fixed order from its `mutants/` copy** (different cwd). A test
  that leaks state can pass under plain `pytest` (so `check.sh` looks green) yet fail the
  mutmut baseline. So "check.sh green" is necessary but not sufficient — a module's tests
  must also be **order-independent** (pass in any order). If they aren't, that's a
  test-isolation defect → route to the blind agent ("make these independent, no shared
  state"); or, if the leak is through *global state in the code*, a real bug → xfail+log.

Once the suite is green: run the gate on **your own module**, so survivors land in the
session that has the context to triage them: `scripts/mutate.sh run 'ctx.<dotted.module>.*'`
(e.g. `ctx.core.storage.*`, `tools.agent.snapshot.*`). The glob scopes which mutants
*execute* without editing config — the survivors that come back are only your module's.

**Each `run` regenerates the whole `mutants/` tree AND re-runs the full baseline suite —
that cost is per-*invocation*, not per-glob.** So if ONE session owns several modules (not the
parallel case), do **one** combined sweep, not N focused runs:
`scripts/mutate.sh run 'ctx.core.storage.*' 'ctx.core.conversation.*'` (mutate.sh forwards all
globs to mutmut). Running them separately pays the regen + full-baseline tax N times for no
benefit. Order modules leaves-first *within* the one sweep; triage all survivors from the
single `mutmut results`.

The single constraint is **concurrency**: mutmut uses one repo-global `mutants/` working
dir + cache and is CPU-heavy, so only **one mutmut process may run at a time**. Runs are
short — parallel sessions just take turns on the gate; never fire two at once.
`[tool.mutmut].only_mutate` is the append-only **union** of landed modules (so every
module's mutants can be generated) — add yours when its tests land; never narrow it for a
focused run (use the glob instead; narrowing clobbers other sessions). Note: mutmut caches
the `mutants/` tree and does **not** invalidate it when `only_mutate` changes, so after
adding your module the cache is stale (the glob would match nothing — "0 files mutated").
`scripts/mutate.sh` deletes and regenerates the tree each `run` to avoid this; if you call
mutmut directly, `rm -rf mutants` first.

**Zero-mutant modules — do NOT add them to `only_mutate`.** Some modules generate *no*
mutants under this mutmut (notably a pure `@dataclass` whose only logic is `@classmethod`
factories, e.g. `ctx/models/nodes.py` — mutmut wraps nothing, so `grep -c mutmut
mutants/<path>` shows only the import line). Adding such a module to `only_mutate` makes its
focused glob abort with `AssertionError: Filtered for specific mutants, but nothing matches`.
Leave it out; its guarantee is the contract + 100% branch coverage, and its behavior is
exercised transitively by the modules that DO get gated (e.g. `nodes` round-trips under
`storage`, its graph edges under `conversation`). Note this in the module spec's
Mutation-testing section instead of forcing a gate that can't run.

Reading results: `mutmut results` lists only the mutants needing attention (survived /
suspicious / timeout) — it does **not** list killed mutants, so a long list is not "0
killed." The authoritative kill/survive tally is the emoji summary line printed at the
end of `run` (`🎉` killed, `🙁` survived); re-run (it's cached/instant) to see it, or use
`mutmut browse`. **Don't pipe `run` straight to `tail`** — the emoji summary prints *before*
the long `results` dump, so `tail` drops exactly the line you want; capture full output to a
file or read `mutmut results` separately.

**A spec's documented survivor count can be stale.** The "N mutants, M survivors" line in a
module's spec reflects the state at the *last* gate run; later-added test sections (e.g. a
calibration block appended in a subsequent sprint) may not have re-run the gate. So if you see
more survivors than the spec claims, first confirm whether they are *pre-existing* (in code you
didn't touch, and equivalent) before treating them as a regression — mutant *numbers* also
shift when the module grows. Only survivors in the code/tests THIS session changed are yours to
kill; refresh the spec's tally when you finish.

Triage every survivor:
- **weak test** → a real output difference no test pins; route it to the blind agent as
  an intent question so it strengthens the test/contract (you don't hand-write assertions);
- **equivalent mutant** → no observable difference (e.g. `get(k, "")`→`get(k, None)` when
  both are falsy and the branch is the same); document & ignore;
- **real bug** → quarantine + log it (xfail/FOUND-BUGS.md), same as step 5.
Re-run until only documented-equivalent mutants survive. Note: lines whose behavior is
currently buggy (covered only by an `xfail` test) won't have their mutants killed — that
is expected; mutation coverage of those lines returns once the bug is fixed and the
`xfail` removed.

**Scope the re-verify to the survivor ids — don't re-run the whole module.** After the blind
agent strengthens a test to kill specific survivors, confirm the kills by running mutmut against
just those mutant ids, not the full glob:
`scripts/mutate.sh run 'ctx.core.conversation.xǁConversationCoreǁresume_conversation__mutmut_7' 'ctx.core.conversation.xǁConversationCoreǁ__init____mutmut_8'`
(copy the ids verbatim from `mutmut results`). This still regenerates the tree + runs the
baseline once, but then executes only those 2 mutants instead of the module's 200+ — seconds vs
minutes. Re-run the full-module glob only for the final clean sweep. (Method-mutant ids use the
`xǁClassǁmethod__mutmut_N` form with the `ǁ` separator; module-level functions use
`x_func__mutmut_N`.)

### 7. Gate green
`bash scripts/check.sh` must pass (ruff, mypy, and the new tests collected & green).
mutmut stays **out** of check.sh — it's the periodic/triage tool.

## Done when
- `tests/specs/<module>.md` exists, items are intent-derived, tests cite ids;
- every branch of the module is covered;
- any real bug found is quarantined (`xfail strict`) and logged in
  `tests/specs/FOUND-BUGS.md` — production code is untouched;
- mutmut shows only documented-equivalent survivors (plus xfail-quarantined bug lines);
- `scripts/check.sh` is green.

## Order across modules
Leaves first (`nodes`, `provider`, `snapshot`, `storage`, `workspace`, `config`),
then `conversation.py` last (the integrator — its collaborators' contracts should
exist first, so it can be specified against their protocols).
