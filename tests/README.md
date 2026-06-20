# Tests

This is the home of the **deterministic test layer** — the required next step in
hardening `ctx`'s back pressure. It is intentionally empty for now (no tests have
been written yet); `scripts/check.sh` treats "no tests collected" as a pass until
the first test lands, then the gate tightens automatically.

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
