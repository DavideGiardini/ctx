# Ralph progress — ctx0 Phase 4: built-in web search

Append-only memory across loop iterations. Prior runs are archived:
ctx0 Phase 2 Part A (the subtraction pass) at
`scripts/ralph/archive/ctx0-phase2-subtraction/PROGRESS.md`; shared Pilot test
scaffolding at `scripts/ralph/archive/conftest-scaffolding/PROGRESS.md`;
Sprint 3 at `scripts/ralph/archive/sprint3/PROGRESS.md`.

<!-- Each iteration appends a dated entry here (PROMPT.md step 8): what it did, tests
added or why none, verification run, key decisions, and any gotcha a future fresh
iteration must know. -->

## 2026-07-26 — task 1: search backend seam + litellm `search` adapter

**What shipped.** New `ctx/core/search.py`: frozen `SearchHit`, `SearchError`, the
`SearchBackend` Protocol (`async search(query) -> list[SearchHit]` for now; task 2
adds `fetch`), `LiteLLMSearch` over `litellm.asearch`, the canned `TestSearch`
double, and `search_available()`. Plus the `"search"` config section
(`provider`/`max_results`/`max_tool_calls`) with the same re-merge treatment the
other sections get in `get_config()`.

**Tests.** Code-blind `test-spec-author` run produced `tests/specs/search.md`
(C1–C8) and `tests/test_search.py`. I pruned its C4 test (empty result set → `[]`)
as a shallow duplicate of C2's mapping path — recorded as a `Status:` line under C4
in the spec rather than silently dropped. Six tests remain, one per acceptance
clause plus the provider-reaches-the-backend check. Two test-infra fixes, neither
touching a contract: the local exception double was renamed `…Error` for ruff N818,
and `TestSearch` is imported `as CannedSearch` because pytest tries to collect any
module-level `Test*` class in a test module and warns on the constructor (this is
why `TestProvider` never warns — it is only imported in `conftest.py`, which is not
collected. Task 8 puts the search double in `conftest.py`, so the alias is only
needed in `tests/test_search.py`).

**One existing test deliberately changed.** `tests/test_config.py::test_c3_baseline_shape`
pinned the exact top-level key set of the defaults, so a new section makes it fail
by construction. Widened it to include `"search"` and amended `tests/specs/config.md`
C3 (which had already drifted — it did not mention `"import"` either) with an
explicit amendment note pointing the search-section contract at `specs/search.md` C8.

**Key decision — how `search_available()` knows which env var.** litellm does *not*
expose a provider→key-name mapping we can query: `ProviderConfigManager.get_provider_search_config()`
eagerly imports all thirteen backend configs and **blows up in this venv**
(`litellm.llms.brave.search.transformation` needs `dateutil`, which we don't ship).
So `search.py` carries an explicit `_API_KEY_ENV` table (13 entries, harvested from
each backend's `get_secret_str("…")` call). A backend mapped to `None` needs no key
(duckduckgo); a provider name absent from the table reports unavailable, so a typo'd
config line quietly offers no tools instead of tools that always fail (D4).
**Gotcha for a future iteration:** do not "improve" this by calling into
`ProviderConfigManager` — it raises `ModuleNotFoundError` here.

**Verification.** `bash scripts/check.sh` green (679 passed). No `qa-tester` and no
rendering: pure core with no UI surface this iteration, per PRD notes and PROMPT.md
step 7.
