# Tests

This is the home of the **deterministic test layer** that `scripts/check.sh` runs on
every commit. It has two halves: unit tests of the framework-free core (`ctx/core/*`)
through its interfaces, and Pilot-driven tests that drive the real TUI headless (the
`test_app_*.py` family) — the deterministic counterpart to the agent-driven MCP QA.

## How tests are authored here

Unit tests are written with a **contract-first, code-blind** method (the
`/write-tests` skill + the `test-spec-author` subagent) that resists tests which
merely mirror the implementation ("self-validating" tests). The flow per module:

1. The orchestrator hands a **code-blind** agent only the module's interface
   (signatures + docstrings) and a prose statement of intent — never the bodies.
2. That agent produces a numbered **behavioral contract**, committed under
   `tests/specs/<module>.md` (the oracle of record; tests cite item ids like `# C3`).
3. Tests are authored from the contract; a coverage loop closes any gaps by asking
   *intent* questions (never by describing the code).
4. `scripts/mutate.sh` runs **mutmut** to prove the assertions actually catch faults;
   surviving mutants are triaged (weak test / equivalent / real bug). mutmut is a
   periodic tool, deliberately **not** part of `scripts/check.sh`.

See `tests/specs/context.md` for a worked example.

## What belongs here

- **Unit tests** of the framework-free core (`ctx/core/*`) through its interfaces:
  `ConversationCore`, `ConversationRepository` (use `:memory:`), the pure
  `build_context`, `Workspace` (use a temp dir), and the `Provider` protocol via
  `TestProvider`.
- **Pilot-driven tests** of the TUI (`test_app_*.py`). Drive
  `tools.agent.harness:HarnessApp` (or `ChatApp` wired with `TestProvider`) through
  Textual's `App.run_test()` / `Pilot`, press keys, and assert on `describe_state()`.
  This is the home for repeatable "MCP smoke" coverage; the `qa-tester` subagent
  handles the exploratory/LLM-driven side.

## Shared Pilot scaffolding

The `test_app_*.py` family used to hand-copy ~420 lines of setup across ~19 files
(the copies had already started to diverge). That scaffolding now lives in two
shared homes — **reuse them; do not re-declare a 20th private copy:**

- **`tests/conftest.py`** — the fixtures and provider *doubles*. The `app_factory`
  fixture builds a wired `ChatApp` (`app_factory(provider=…, tokens=…, usage=…)`);
  the provider classes (`TestProvider`/`RecordingProvider`/`BlockingProvider`/
  `ErroringProvider`, …) are imported from here (`from conftest import …`). conftest
  is auto-discovered by pytest and is **not** meant to be imported as a module, so
  only fixtures and classes go here — not plain helper functions.
- **`tests/pilot_helpers.py`** — the importable keystroke/turn *choreography*
  functions (`from pilot_helpers import …`): `two_turns` / `turn` (submit + drain),
  `wait_until` / `wait_until_streaming` (bounded spin on a live worker),
  `open_editor_on_range(pilot, *, downs=3)` and `compress_range(app, pilot, summary,
  *, downs=3)` (the `downs` knob sizes the folded range — `downs=1` for the 2-node
  variants), and `select_tip_in_edit` (the mode-guarded double-Esc that re-selects
  the tip after a commit).

**Deadlock trap:** a `BlockingProvider` blocks forever on its gate, so it must
**never** drive a setup turn that is awaited to completion (`two_turns`/`turn` drain
fully) — that deadlocks the whole run. Set up with the scripted default provider and
swap the blocking one in only for the single turn under test (see its docstring).

## Conventions

- `pytest` with `asyncio_mode = "auto"` (configured in `pyproject.toml`) — async
  test functions need no decorator.
- Reuse the existing harness (`tools/agent/harness.py`) and snapshot renderer
  (`tools/agent/snapshot.py`) rather than rebuilding fixtures.
