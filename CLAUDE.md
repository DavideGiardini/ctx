# ctx

A terminal chat application (Textual TUI) that streams LLM responses via `litellm` —
a "conversation IDE." Supports model switching, context-file inclusion, conversation
persistence on an append-only node graph, range compression/summarization, and a
two-mode UI (insert vs. edit).

## Environment & running
- Python ≥3.11, managed with `uv` (`uv.lock` committed). Build backend: `hatchling`.
- Install: `uv sync`. Run: `uv run ctx` (or `uv run python -m ctx.main`).
- Needs a `.env` with `OPENROUTER_API_KEY` (or another litellm-supported key). The app
  does **not** load `.env` itself — litellm reads the env directly.
- Logs: `~/.local/state/ctx/ctx.log`. User config: `~/.config/ctx/config.json`.

## Workspace
- Each working dir gets a local `.ctx/` at runtime (gitignored): `conversations.db`
  (SQLite, WAL) for history, and `context/` where you drop text files to `/include`.
- In-app commands: `/new`, `/resume`, `/include`, `/model <model>`.

## Quality gate
Run before every commit (CI and the Ralph loop call it too):
- `bash scripts/check.sh` — ruff + mypy + pytest in one shot.
- Individually: `uv run ruff check .` (`--fix` to autofix), `uv run mypy .`, `uv run pytest`.
- Install the hook: `uv run pre-commit install`.

Do **not** weaken the gate to make it pass — fix what it reports. Don't hand-edit
`uv.lock`; use `uv sync` / `uv add` / `uv remove`.

## Implementing changes
`scripts/ralph/` holds an autonomous "Ralph loop" that runs tasks in fresh sessions.
It is **not** the default workflow — decide together, per change, whether to split the
work into Ralph-loop iterations or implement it directly in-conversation.

## Architecture map
Layered — the layering is an invariant, not a suggestion:
- `ctx/core/` — framework-free domain logic (conversation state, provider seam,
  storage, context building, token accounting). **Zero `textual`
  imports.** New domain logic goes here.
- `ctx/ui/` — a thin Textual adapter over core (the dual-pane shell).
- `ctx/models/` — shared types (`Node`: one chat turn or context reference).
- `ctx/main.py` — tiny entry point / composition root.
- `tools/agent/` — headless QA tooling, **outside** the shippable `ctx` package.

Invariants worth not breaking:
- The conversation is an **append-only node graph** — never mutate or delete nodes;
  append. Rewind / compression / expand are all non-destructive (ADR 0016).
- `ctx` must **never** import from `tools/`. Tooling imports from `ctx`, never the reverse.
- Protocol seams exist only where a second real impl does: `Provider`/`TestProvider`
  (ADR 0002), `StoragePort`/`ConversationRepository` (ADR 0003), injected `Workspace`
  (ADR 0005).
- `Node` factory classmethods (`Node.user`/`.assistant`/`.system`/`.context`/
  `.compression`/`.expand`) are the single source of truth for each kind's shape —
  construct through them, not the bare dataclass (ADR 0014). `Node.goes_to_model()`
  is the single definition of which nodes reach the LLM.

The **why** behind the shape lives in `docs/decisions/` (ADRs) — read those rather than
re-deriving. For current internals, read the code; this file does not narrate them.

## Designing new modules
Deep-module philosophy (see ADRs):
- **Prefer deep modules** — a simple interface over substantial implementation. If the
  interface is about as complex as the impl, it's shallow: fold it in or deepen it.
- **The interface is the test surface.** Don't extract a pure function *only* to test it
  while the real bug lives in how it's called — keep logic where it has locality.
- **Keep core framework-free** (see the map).
- **Inject a Protocol seam only when a second real implementation exists** — one adapter
  is hypothetical, two is real.
- **Deletion test before adding an abstraction:** would deleting it concentrate
  complexity (good) or just scatter it (don't add it)?

For deeper refactors, run the `/improve-codebase-architecture` skill.

## Comments: sparse anchors, not narration
Let code, types, and docstrings carry the obvious, and ADRs carry the *why*.
- Don't restate the code or re-argue a settled decision inline — reference the ADR.
- Comment only the genuinely tricky or bug-prone, and anchor those with `AIDEV-NOTE:` /
  `AIDEV-TODO:` / `AIDEV-QUESTION:` (≤120 chars) so they're greppable and a future agent
  knows the note guards something subtle.

## Agent-driven testing (headless)
The app can be driven and observed without a terminal via the `ctx-agent` MCP server
(`tools/agent/mcp_server.py`). **Default to delegating behavioral QA to the `qa-tester`
subagent** (modes: stress-test / verify-fix / verify-feature) — it owns the
snapshot→act→check loop and keeps that token-heavy traffic out of your context.

Two harness traps to design around:
- **In-process, cached imports.** The server imports `ctx.*` once; relaunching the app
  does *not* reload edited code. Never edit code and UI-verify it in the same session —
  verify in a later session (fresh server) or after a `/mcp` reconnect.
- **It can't see layout.** No computed margins; screenshots are unreliable. Assert on
  queryable state (CSS classes, content, `ctx_snapshot`); put spacing/layout invariants
  in unit tests, not qa-tester.

## Keep this file current
When you change the *structure* — add/remove/rename a top-level module, move a
responsibility across the core/ui seam, add a seam, or change an invariant — update the
map above in the same change. For a decision worth not re-litigating, add an ADR. Don't
re-introduce module-by-module implementation narration here; it rots, and that's what
the code and ADRs are for.
