# 0012 — agent/ is dev-only tooling but currently ships

**Status:** Resolved (Option B implemented — see "Resolution" below).

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

## Resolution (Option B)

- **Location.** `ctx/agent/` moved to the top-level `tools/agent/` package
  (`tools.agent.{harness,snapshot,mcp_server}`). `tools/` is outside the importable
  `ctx` package, so it cannot be bundled into the wheel. As belt-and-suspenders,
  `[tool.hatch.build.targets.wheel] packages = ["ctx"]` makes the shipped package
  set explicit. Layout direction is enforced: `tools/*` may import `ctx.*`; `ctx/*`
  must never import `tools.*` (and no `ctx` module does).
- **Console script removed, not repointed.** `ctx-agent-mcp` is gone from
  `[project.scripts]`. Repointing it at `tools.agent.mcp_server:main` would still
  install a console script in the wheel that `ModuleNotFoundError`s for end users
  (`tools` isn't shipped) — the same class of bug. Dev launch is now
  `uv run python -m tools.agent.mcp_server`; `.mcp.json` / `opencode.json` were
  updated accordingly. The MCP server **name** stays `ctx-agent`, so all
  `mcp__ctx-agent__*` allowlists and qa-tester references are unchanged.
- **`TestProvider` stays in `ctx/core/provider.py`.** It is consumed by
  `tests/conftest.py` and the unit suite — not only the harness — so moving it into
  `tools/` would point core test fixtures at the dev-tooling package (wrong
  direction). It is a tiny in-core test double (the legitimate second `Provider`
  impl) with no `textual_mcp` dependency, so it ships harmlessly and never crashes,
  and keeps its existing mutmut coverage with no path juggling.
- **mutmut coverage preserved.** `[tool.mutmut]` now lists `source_paths =
  ["ctx", "tools"]` and `only_mutate` points at `tools/agent/snapshot.py`, so the
  snapshot renderer keeps its mutation coverage at the new path.
- **Verified with a real `uv build`** — the wheel contains no `ctx/agent/...` and no
  `tools/...`, and its `entry_points.txt` declares only the `ctx` console script.
