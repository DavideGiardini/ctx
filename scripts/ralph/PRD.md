# PRD — Shared Pilot test scaffolding (conftest extraction)

## Goal
Extract the ~420 lines of Pilot test scaffolding duplicated across the
`tests/test_app_*.py` family into shared homes, so the suite has one copy of each
helper instead of ~19 hand-synced ones (already diverging — see the inconsistent
`if mode == "edit": escape` workarounds). This is the "Test choreography helpers"
item from `docs/Code Quality Review 2026-07.md` and the first step of ctx0 Roadmap
Phase 1: the turn-lifecycle work that follows will add new Pilot tests, and they
must be written against shared helpers, not a 20th copy of the duplication.

## Constraints / notes
- **Behavior-preserving refactor only.** No product code (`ctx/**`) changes. No new
  test cases, no deleted test cases — every task's floor is: the same tests are
  collected and all pass. Capture the collected count with
  `uv run pytest --collect-only -q | tail -1` *before* migrating and compare after.
- **Placement (decided, don't relitigate):** fixtures and provider double *classes*
  go in `tests/conftest.py` (the pattern exists — `_VaryingProvider` already lives
  there); keystroke-choreography *functions* go in a new importable
  `tests/pilot_helpers.py` (plain functions don't belong in conftest, which is not
  meant to be imported from).
- Shared helpers are used by many files, so give them real docstrings; keep names
  un-prefixed (`BlockingProvider`, not `_BlockingProvider`) since they are now a
  shared surface.
- **Deadlock trap (must go in `BlockingProvider`'s docstring):** an always-blocking
  provider must never be used for setup turns that fully drain — a turn awaited to
  completion against a gate that is never set deadlocks the whole pytest run. Setup
  turns use the default scripted provider; the blocking one is only for the turn
  under test.
- Migrate mechanically; do NOT "improve" test logic while moving it. Where an
  existing copy genuinely diverges from the common shape, either parameterize the
  shared helper (preferred when the divergence is one knob, e.g. range width) or
  leave that copy in place — never force-fit.
- No qa-tester runs needed anywhere in this PRD: test-only changes have no runtime
  surface; `scripts/check.sh` green IS the verification.
- `tests/README.md` documents conventions; task 4 updates it so future sessions
  know the shared scaffolding exists.

## Completed
- [x] 1 — Shared provider doubles in `tests/conftest.py` (bodies in `PRD-done.md`)
- [x] 2 — Shared app factory in `tests/conftest.py` (bodies in `PRD-done.md`)
- [x] 3 — Turn/submit choreography in `tests/pilot_helpers.py` (bodies in `PRD-done.md`)
- [x] 4 — Compress-via-editor choreography in `tests/pilot_helpers.py` (bodies in `PRD-done.md`)

## Tasks

_All tasks complete._

## Out of scope
- Any change under `ctx/**` — this PRD touches only `tests/` (and `tests/README.md`).
- The turn-lifecycle work itself (core `end_turn`, submit refusal, UI convergence,
  cancel coverage) — that is Phase 1's main body, done in-conversation after this
  loop, NOT here.
- New test cases or coverage improvements — same tests before and after.
- `tools/agent/**` (the qa-tester harness) — untouched.
- The `HarnessApp`-based files (`test_visual_states.py`, `test_message_row.py`,
  `test_message_list_meta_layout.py`) — they don't share these shapes; leave them.
