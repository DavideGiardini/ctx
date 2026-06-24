# 0012 — agent/ is dev-only tooling but currently ships

**Status:** Notes (fix intended — Option B preferred)

## Context

`ctx/agent/` is QA tooling: a "fake users" harness that lets coding agents drive
and stress-test the app (see `ctx/agent/__init__.py`). It is **not** meant to be
part of the product an end user downloads. The current packaging does not enforce
that intent.

## Observation

For someone who `pip install`s `ctx`:

- **The code ships.** There is no `[tool.hatch.build]` exclude, so hatchling
  bundles the whole `ctx/` package — including `ctx/agent/` — into the wheel.
- **A command ships.** `[project.scripts]` declares `ctx-agent-mcp =
  "ctx.agent.mcp_server:main"`, so the end user gets a `ctx-agent-mcp` executable
  on PATH. (`[project.scripts]` always installs; it can't be gated by a dependency
  group.)
- **But it can't run.** `ctx/agent/mcp_server.py` imports `textual_mcp`, and
  `textual-mcp-server` is a **dev-only** dependency. So the shipped command crashes
  with `ModuleNotFoundError` for end users.

Net: dev tooling leaks into the product, in a broken state.

`TestProvider` (`ctx/core/provider.py`) is part of this picture — its only
consumers are the agent harness and the tests, never the end-user runtime. Its
location is coupled to where the harness lives, not to the core.

## Direction

**Option B (preferred): move `agent/` out of the importable package.** Relocate the
tooling to a top-level dir outside `ctx/` (e.g. `tools/`), so it is structurally
impossible to ship; update the import paths in `.mcp.json`, `AGENTS.md`, and the
harness/loader strings. Makes "agents are not part of the product" a fact of the
layout, not a build flag. `textual-mcp-server` stays dev-only (correct already).

Option A (fallback, minimal): keep `agent/` under `ctx/` but add a wheel `exclude`
and drop `ctx-agent-mcp` from `[project.scripts]` (launch via `python -m
ctx.agent.mcp_server` in dev).

When fixing, also decide `TestProvider`'s home (it currently still ships inside
`ctx/core/provider.py`), and **verify with a real `uv build`** — inspect the wheel
contents to prove `agent/` is excluded rather than assume it.
