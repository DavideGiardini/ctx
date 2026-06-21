# Tests

This is the home of the **deterministic test layer** — the required next step in
hardening `ctx`'s back pressure. The first unit tests have landed
(`test_context.py`), so `scripts/check.sh` now runs them for real; the historical
"no tests collected" pass-through is dormant.

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
- **Pilot-driven smoke tests** of the TUI — the deterministic counterpart to the
  agent-driven MCP QA. Drive `ctx.agent.harness:HarnessApp` (or `ChatApp` wired
  with `TestProvider`) through Textual's `App.run_test()` / `Pilot`, press keys,
  and assert on `describe_state()`. This is the proper home for repeatable "MCP
  smoke" coverage; the `qa-tester` subagent handles the exploratory/LLM-driven side.

## Conventions

- `pytest` with `asyncio_mode = "auto"` (configured in `pyproject.toml`) — async
  test functions need no decorator.
- Reuse the existing harness (`ctx/agent/harness.py`) and snapshot renderer
  (`ctx/agent/snapshot.py`) rather than rebuilding fixtures.
