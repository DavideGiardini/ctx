# Review probes (2026-07-04 post-Sprint-3 review)

Throwaway-but-preserved pytest probes written by the three-agent adversarial review
of the Sprint 3 (`feat/compression`) diff. They seed the regression tests for the
Phase 3d hardening tasks in `scripts/ralph/PRD.md` (tasks 27–32).

**Not part of the gate:** pytest `testpaths = ["tests"]` excludes this directory, so
`scripts/check.sh` neither collects nor requires these. They do pass ruff + mypy.
Run them explicitly with `uv run pytest scripts/ralph/probes/ -q`.

Contents and their contract:

- `test_review_hazards.py` — UI Pilot probes asserting the **correct** behavior
  for tasks 30/31. **Currently red by design** (they reproduce the defects).
  As each fix lands, adapt the relevant probe into a real test under `tests/`
  (house style: real keypresses, `describe_state()` asserts) and delete it here.
  (Task 27's four diff-view-gating probes were promoted into
  `tests/test_app_diff_view.py` on 2026-07-04 and removed from here.)
- `test_adversarial_core.py` — 15 core probes documenting **current** behavior
  (all green). Most pin invariants that already hold (oracle round-trips, seq
  counting, migration idempotence, rewind guards …) and can be mined for extra
  `tests/` coverage. One of them pins a **bug** and must be INVERTED when fixed:
  - `test_dangling_active_leaf_fallback_can_put_k_on_tip` (parking lot, no task) —
    documents the corrupt-DB fallback hazard in `resume_conversation`.
  (Task 28's `test_h2_window_between_submit_and_first_tick` was inverted into
  `tests/test_commit_compression.py::test_events_rejected_in_submit_to_first_tick_window`
  on 2026-07-04 and removed from here.)
- `bench_drift.py` — micro-benchmark behind task 32's numbers (1.6 ms @ 50 turns,
  23 ms @ 200, 151 ms @ 500 per `_node_drift`-style pass). Run directly with
  `uv run python scripts/ralph/probes/bench_drift.py`.

Delete this directory once Phase 3d is complete and its probes have been promoted
or inverted into `tests/`.
