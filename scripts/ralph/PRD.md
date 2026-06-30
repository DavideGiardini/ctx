# PRD — Sprint 1: Token accounting & context budget

## Goal
Fill the two context-budget UI slots that are wired but dead (hardcoded `None`,
never called): the header context-window gauge (`AppHeader.set_context_pct`,
`ctx/ui/widgets/app_header.py`) and the per-node weight `--%`
(`MessageWidget.set_weight_pct`, `ctx/ui/widgets/message_list.py`).
`describe_state()` (`ctx/ui/app.py`) already emits `weight_pct: None` per node — the
slot exists, the number is missing. We add a framework-free deep module
`ctx/core/tokens.py`, a `ui.weight_basis` config flag, and a provider `usage` seam,
then wire real numbers in. **Two denominators:** per-node weight is a *local,
provider-agnostic ratio* (robust because the tokenizer scale factor cancels); the
header gauge is *used ÷ model window*, sharpened by the provider's exact `usage` when
available and marked `~` when it's only an estimate. No DB change. Full design and
rationale: the approved plan at `/home/giardo/.claude/plans/jaunty-enchanting-gizmo.md`.

## Constraints / notes
- Follow `AGENTS.md` "Designing new modules": deep modules, `ctx/core/*` stays
  **framework-free** (zero `textual`), reuse existing seams, deletion test before
  abstraction. `ctx/core/tokens.py` gets **no Protocol seam** (single implementation).
- **Provider-agnostic by design.** `openrouter/google/gemma-…` is only the local-dev
  default; users run any litellm-backed provider. Do **not** special-case any provider.
  The local estimate is the always-available baseline; provider `usage` only sharpens
  absolutes; per-node **%** never depends on a provider.
- **Reuse:** `build_context` (`ctx/core/context.py`) to render nodes to messages;
  `Node.goes_to_model()` (`ctx/models/nodes.py:54`) for routing; `get_config()`
  (`ctx/core/config.py`); litellm `token_counter` / `get_model_info` (already a dep).
- **Shared fixtures** in `tests/conftest.py`: `make_node`, `stub_loader`,
  `test_provider`, `repo`, `workspace`. Reuse them. The `test_provider` factory builds
  `TestProvider(tokens)`, so Task 4's new `usage` arg MUST default to `None`.
- **Code-blind test flow** (PROMPT.md step 4) for new/changed core behavior: write
  signatures + docstrings + stubs, spawn `test-spec-author` with *only* the interface
  + prose intent, get red tests, implement to green. Treat authored tests as fixed.
- **qa-tester harness runs in-process** (`ctx.*` cached): it cannot see code you edited
  *this* iteration, and it cannot perceive layout/spacing. So for UI tasks the
  **mandatory acceptance floor is a deterministic Pilot test** (`App.run_test()`)
  asserting on `describe_state()` fields (the repo has no Pilot tests yet — Task 3
  introduces the first); `qa-tester` is confirmation and may lag one iteration.
- Ref ADRs: `0002` (Provider protocol — Task 4), `0001` (core/ui seam). Task 4
  introduces a real architectural decision (the `usage`-off-the-stream seam shape) —
  **record it as an ADR in `docs/decisions/`** as part of that task.
- This PRD replaces the completed "Deferred cleanups round 2" PRD; its record is in
  `PROGRESS.md` + git. Do not resurrect those tasks.

## Tasks
Top-to-bottom by priority; the loop always takes the topmost unchecked task.
Dependencies are noted; every prerequisite sits above its dependent.

- [x] **1. `core/tokens.py` deep module + code-blind contract tests** — new
      framework-free module `ctx/core/tokens.py` (no Protocol seam). Public surface
      (refine docstrings, then author tests blind): `count_messages(messages, model)
      -> int` (wraps `litellm.token_counter`; the ONLY place the tiktoken fallback
      lives); `per_node_tokens(nodes, model, read_file) -> list[int]` (message-framed
      local estimate per node — render each via `build_context([node], read_file)`;
      `0` when not `goes_to_model()`); `weight_pct(nodes, model, read_file, basis,
      max_input_tokens) -> list[int | None]` (`basis` is `"context"|"window"`);
      `gauge(local_total, max_input_tokens, calibration) -> tuple[int | None, bool]`
      returning `(pct, approximate)` where `approximate` is `True` when `calibration`
      is `None`; `model_window(model) -> int | None` wrapping
      `litellm.get_model_info(model)["max_input_tokens"]` with a graceful fallback
      (unknown model → `None`, never raise). Reuse `build_context`,
      `Node.goes_to_model()`, fixtures `make_node`/`stub_loader`. _Acceptance:_
      `tests/specs/tokens.md` + `tests/test_tokens.py` (code-blind). Contract covers:
      estimate `> 0` for a non-empty `goes_to_model()` node and `0` for a system node;
      `"context"`-basis per-node %s sum to ~100; `"window"`-basis values are `< 100`
      and never sum to 100; calibration changes `gauge` absolutes but the per-node
      `weight_pct` is unaffected (ratio cancels); `model_window` returns `None`
      (no raise) for an unknown model; `gauge` `approximate` is `True` with `calibration=None`.
      `scripts/check.sh` green.

- [x] **2. `ui.weight_basis` config flag** — in `ctx/core/config.py` add
      `"weight_basis": "context"` under the `"ui"` section of `_DEFAULTS` (the existing
      depth-2 `ui` merge already carries nested keys). Coerce an invalid value (not in
      `{"context","window"}`) back to `"context"` in `get_config()`. _Acceptance:_
      extend `tests/test_config.py` + `tests/specs/config.md`: default is `"context"`;
      a valid `"window"` user override is preserved; an invalid value falls back to
      `"context"`. `scripts/check.sh` green.

- [x] **3. UI: per-node weight %** _(deps: 1, 2)_ — in `describe_state()`
      (`ctx/ui/app.py`) replace the hardcoded `weight_pct: None` with values from
      `tokens.weight_pct(nodes, self.core.model, read_file, basis, max_input_tokens)`,
      where `basis = get_config()["ui"]["weight_basis"]`, `max_input_tokens =
      tokens.model_window(self.core.model)`, and `read_file` is the same loader
      `ConversationCore` injects into `build_context` (expose a `read_file` accessor on
      the core if needed — keep core framework-free). Add a `_refresh_weights()` that
      loops the mounted `MessageWidget`s and calls `set_weight_pct(...)`, invoked after
      every node-list change (`submit`, `include_files`, `resume`, `new`). _Acceptance:_
      a deterministic **Pilot test** (`App.run_test()`) drives a user turn + a canned
      assistant reply and asserts `describe_state()["nodes"]` have **numeric**
      `weight_pct` (not `None`), the `"context"`-basis %s sum to ~100, and a system
      breadcrumb node is `0`/`None`. `scripts/check.sh` green. Then `qa-tester`
      (verify-feature, `tools.agent.harness:HarnessApp`) confirms numeric per-node %s
      in `ctx_snapshot` and that they redistribute after `/include`; no
      `textual_check_errors`. (qa-tester may lag one iteration due to the in-process
      cache — the Pilot test is the floor.)

- [x] **4. Provider `on_usage` seam + `stream_options` + TestProvider usage** — in
      `ctx/core/provider.py` define a small `Usage` type (`prompt_tokens`,
      `completion_tokens`, `total_tokens`) and add an optional
      `on_usage: Callable[[Usage], None] | None = None` to the `Provider` protocol and
      both impls. `LiteLLMProvider`: pass `stream_options={"include_usage": True}` to
      `acompletion`; guard the chunk loop so the final usage/empty-`choices` chunk
      doesn't `IndexError` (today `chunk.choices[0].delta.content` assumes a choice
      exists); when `chunk.usage` is present, call `on_usage(Usage(...))`. `TestProvider`:
      add optional `usage: Usage | None = None` to `__init__` (default `None` keeps the
      `test_provider` fixture working) and, after yielding tokens, call `on_usage(usage)`
      only when `usage is not None`. The change is backward-compatible — existing
      `provider.stream(messages, model)` callers stay green. **Record an ADR** in
      `docs/decisions/` for the seam shape (callback chosen over a `StreamChunk` union;
      provider-agnostic). _Acceptance:_ extend `tests/test_provider.py` +
      `tests/specs/provider.md`: with a canned `usage`, `on_usage` fires once with it
      and all tokens still stream; with `usage=None`, `on_usage` never fires; the
      LiteLLM path tolerates a usage/empty-`choices` chunk without crashing.
      `scripts/check.sh` green.

- [x] **5. `conversation.py` calibration** _(deps: 1, 4)_ — in `ConversationCore.stream`
      (`ctx/core/conversation.py:148`) compute the local sum of the context just sent
      (`tokens.count_messages(messages, self.model)`) and pass an `on_usage` callback to
      `self._provider.stream`. On callback, **sanity-check** the usage
      (`prompt_tokens > 0` and within ~10× of the local sum); if sane, store
      `last_usage` and `calibration = prompt_tokens / local_sum`; otherwise leave
      `calibration` unset. Expose `last_usage` and `calibration` (read-only) for the UI.
      Keep `stream` **yielding `str`** (the app is untouched). _Acceptance:_ extend
      `tests/test_conversation.py` (reuse `make_node`, the extended `test_provider`):
      after a turn whose provider returns sane usage, `calibration ≈ prompt_tokens /
      local_sum` and `last_usage` is set; after a turn with `usage=None`, `calibration`
      stays unset; a bogus usage (e.g. `prompt_tokens=0` or wildly out of range) is
      rejected and `calibration` stays unset. No `StoragePort` change →
      `SaveCountingStorage` double untouched. `scripts/check.sh` green.

- [ ] **6. UI: header gauge + `~` marker** _(deps: 1, 5)_ — in `describe_state()`
      (`ctx/ui/app.py`) add gauge fields from `tokens.gauge(local_total,
      tokens.model_window(self.core.model), self.core.calibration)` where `local_total`
      is the summed `per_node_tokens` (or `count_messages` of the full context). Extend
      `AppHeader.set_context_pct` / `_gauge` (`ctx/ui/widgets/app_header.py`) to take an
      `approximate: bool` and render a leading `~` when true (today `_gauge` only takes
      `pct: int | None`). Push the gauge after every node-list change and on
      stream-complete via `self.query_one(AppHeader).set_context_pct(pct, approximate)`.
      Per decision #5: `~` rides only the **absolute** gauge — when there's no
      calibration yet OR the node set changed since the last measured usage (stale);
      per-node **%** never shows `~`. _Acceptance:_ a deterministic **Pilot test**
      asserts `describe_state()` gauge fields: `approximate` is `True` before any usage;
      `False` after a streamed turn with canned usage; `True` again (stale) after a
      following `/include`; an unknown/garbage model (`model_window → None`) degrades to
      `--%`/approximate without crashing. `scripts/check.sh` green. Then `qa-tester`
      confirms the header shows a numeric `%` with a filled bar that moves on `/include`
      and the `~` behaves; no `textual_check_errors`.

- [ ] **7. End-to-end verify (qa-tester, verify-feature)** _(deps: all)_ — run the full
      plan brief against `tools.agent.harness:HarnessApp` (TestProvider wired with a
      canned `usage` so calibration is exercised): (1) snapshot empty → gauge `0%`/`--%`;
      (2) user message + canned assistant turn → numeric `weight_pct` per model-bound
      node, context-basis %s sum ~100, system breadcrumb `0`/`None`, gauge numeric with
      bar; (3) `/include` a workspace file → weights redistribute, gauge moves up, `~`
      reappears until next turn; (4) `/new` → back to empty/`0%`. Negative: empty
      conversation and an unknown model degrade to `~`/`--%`, no crash;
      `textual_check_errors` clean. _Acceptance:_ `qa-tester` reports PASS on all
      checkpoints. This task makes no code changes; if it finds a defect, file it as a
      new `- [ ]` task and stop (do not patch under a green-required commit).

## Out of scope
- Any DB / persistence change (Sprint 2) — no `StoragePort`/schema edits.
- Networked `count_tokens` APIs and HuggingFace/SentencePiece tokenizers (rejected;
  possible later as an opt-in "accurate mode").
- System-prompt / tool nodes (S8/S9) — counted automatically once they exist (the
  module drives off `goes_to_model()`), no rework now.
- Do not touch `main`/`develop`, never hand-edit `uv.lock` (use `uv`), never commit
  `.ctx/` or `.env`. Do **not** commit `docs/Sprint Roadmap.md` or the plan file.
