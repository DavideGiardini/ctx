# Contract: `ctx.core.tokens`

Framework-free token accounting for the context-budget UI.

## Oracle of record

The oracle is the **stated intent** of the public interface, not any implementation.
This module produces numbers for two distinct UI slots:

- A **per-node weight column** that is a *local, provider-agnostic ratio* (a node's
  local estimate over a denominator). Because both numerator and denominator come
  from the same local tokenizer, the tokenizer's scale cancels, so the percentage is
  stable even when the local estimate is only approximate. It never carries a
  calibration factor.
- A **header gauge** that is an *absolute* figure (tokens used over the model window),
  optionally sharpened by a provider's exact usage ratio (`calibration`), and flagged
  `approximate` when no such anchor exists.

The module is pure (no I/O, no state). File contents reach it via an injected
`read_file` loader. Counting funnels through litellm's `token_counter` /
`get_model_info`, which means exact counts are model-dependent and callers must not
assume exactness — so the contract asserts **relationships** (ordering, sign,
parallelism, ratios, tolerances) rather than pinned magic numbers.

Tolerances chosen (justified inline where used):
- `"context"`-basis non-None percentages sum to ~100. Each entry is an independently
  rounded int, so for an `n`-nonzero-node conversation the rounding error is bounded
  by roughly ±n. For the 2–3 node conversations under test we assert `95 <= sum <= 105`.
- `gauge` calibration of `2.0` "roughly doubles" `pct_used` vs `None`. Since both go
  through the same rounding, we assert the calibrated value is strictly greater and
  approximately `2x` (within ±2 percentage points of `2 * raw`).

## Contract

C1. **count_messages of empty list is zero.**
  Given:    `messages == []`, `model == "gpt-4"`.
  Expect:   returns `0`.
  Rationale: An empty conversation has nothing to count; the docstring states "An
             empty list counts as 0."

C2. **count_messages of a non-empty list is positive.**
  Given:    a single role/content message dict (e.g. a user message with real prose),
            `model == "gpt-4"`.
  Expect:   returns an `int > 0`.
  Rationale: Real content consumes tokens; the count must be a positive integer.

C3. **count_messages is monotonic in content length.**
  Given:    two message lists where one carries clearly more text than the other,
            same `model`.
  Expect:   the longer-content count is strictly greater than the shorter-content
            count (and both are >= the empty count of 0).
  Rationale: More tokens for more content; the local estimate must track content size
             so the UI weights are meaningful.

C4. **per_node_tokens is parallel to input.**
  Given:    a list of N nodes, a model, and a `read_file` loader.
  Expect:   returns a list of exactly N ints (one per input node, same order).
  Rationale: Docstring: "one int per input node ... Result list is parallel to nodes."

C5. **A non-empty goes_to_model node contributes a positive count.**
  Given:    a user message node with real content.
  Expect:   its per-node entry is `> 0`.
  Rationale: PRD acceptance floor: estimate `> 0` for a non-empty model-bound node.

C6. **A system breadcrumb contributes 0.**
  Given:    a `system` breadcrumb node (`goes_to_model()` is False).
  Expect:   its per-node entry is `0`.
  Rationale: PRD acceptance floor: a node that does not reach the model contributes 0.

C7. **A model-bound node that renders empty contributes 0.**
  Given:    a user node with empty content (`content == ""`).
  Expect:   its per-node entry is `0`.
  Rationale: Docstring: "a model-bound node that renders to nothing ... contributes 0."

C8. **A context node is counted by its resolved file body, not its label.**
  Given:    a context node whose `meta["source_path"]` resolves (via the loader) to a
            large body, alongside a tiny user node; counted with the same model.
  Expect:   the context node's entry `>` the tiny user node's entry, AND `> 0`.
  Rationale: Docstring: a context node "is counted by its RESOLVED FILE CONTENT
             (loaded through read_file), not its 'Included: …' label." A large body
             must dominate a one-word message.

C9. **weight_pct is parallel to input.**
  Given:    a list of N nodes, any valid basis and denominator.
  Expect:   returns a list of exactly N entries (each `int | None`), in input order.
  Rationale: Docstring: "one entry per input node."

C10. **A zero-token node maps to None weight under both bases.**
  Given:    a conversation containing a system breadcrumb (zero-token) plus model-bound
            nodes; evaluated under `"context"` and under `"window"` (with a positive
            window).
  Expect:   the breadcrumb's entry is `None` in both cases; the model-bound entries
            are non-None ints.
  Rationale: Docstring: "A node whose local estimate is 0 ... maps to None."

C11. **context-basis non-None percentages sum to ~100.**
  Given:    a 2–3 node conversation of distinct, non-empty model-bound nodes,
            `basis == "context"`, `max_input_tokens` irrelevant (may be None).
  Expect:   summing the non-None entries yields a value in `[95, 105]`.
  Rationale: PRD acceptance floor; the context denominator is the sum of all local
             estimates, so shares sum to 100 modulo independent integer rounding.

C12. **context-basis with an all-zero conversation yields all None (no ZeroDivision).**
  Given:    nodes whose total local estimate is 0 (e.g. only a system breadcrumb),
            `basis == "context"`.
  Expect:   every entry is `None`; no exception raised.
  Rationale: Docstring: "If that sum is 0, every entry is None." Must not divide by 0.

C13. **window-basis percentages are each < 100 for a small conversation.**
  Given:    a small 2–3 node conversation, `basis == "window"`,
            `max_input_tokens == model_window("gpt-4")` (a large positive int).
  Expect:   every non-None entry is `< 100`.
  Rationale: PRD acceptance floor: a small conversation does not fill the window.

C14. **window-basis non-None values do NOT sum to 100.**
  Given:    same small conversation as C13, `basis == "window"`.
  Expect:   the sum of non-None entries is well under 100 (we assert `< 100`, and
            strictly less than the corresponding context-basis sum).
  Rationale: PRD acceptance floor: window shares answer a different question than
             conversation shares and the conversation rarely fills the window.

C15. **window-basis with max_input_tokens None yields all None.**
  Given:    any node list, `basis == "window"`, `max_input_tokens is None`.
  Expect:   every entry is `None`; no exception raised.
  Rationale: Docstring: "If max_input_tokens is None (or 0), every entry is None."

C16. **window-basis with max_input_tokens 0 yields all None.**
  Given:    any node list, `basis == "window"`, `max_input_tokens == 0`.
  Expect:   every entry is `None`; no exception raised (no ZeroDivision).
  Rationale: Docstring explicitly groups `0` with `None` for the window denominator.

C17. **weight_pct is independent of any provider anchor.**
  Given:    `weight_pct` takes NO calibration argument.
  Expect:   the per-node column is computed purely from local estimates; there is no
            way to make it depend on a provider usage ratio. Tested as a structural
            fact: identical inputs always produce identical output, and the signature
            carries no calibration parameter.
  Rationale: PRD: the weight column is provider-agnostic; the tokenizer scale cancels
             in the ratio so a calibration anchor cannot and must not move it.

C18. **gauge approximate is True when calibration is None.**
  Given:    `gauge(local_total>0, max_input_tokens>0, calibration=None)`.
  Expect:   the returned `approximate` boolean is `True`.
  Rationale: PRD/docstring: no provider anchor yet, mark with `~`.

C19. **gauge approximate is False when calibration is supplied.**
  Given:    `gauge(local_total>0, max_input_tokens>0, calibration=<a float>)`.
  Expect:   the returned `approximate` boolean is `False`.
  Rationale: PRD/docstring: a calibration ratio means the absolute is anchored.

C20. **gauge calibration scales pct_used (~doubling for calibration 2.0).**
  Given:    a fixed `local_total` and `max_input_tokens`; compute the gauge with
            `calibration=None` and with `calibration=2.0`.
  Expect:   the calibrated `pct_used` is strictly greater than the uncalibrated one and
            approximately `2x` it (within ±2 percentage points of `2 * raw`).
  Rationale: PRD acceptance floor: calibration scales the absolute total used.

C21. **gauge with unknown window yields (None, ...) and does not raise.**
  Given:    `gauge(local_total>0, max_input_tokens=None, calibration=None)`.
  Expect:   `pct_used is None`; no exception. (`approximate` still follows C18 → True.)
  Rationale: Docstring: unknown window → pct_used None, UI degrades to `--%`.

C22. **gauge pct_used is NOT clamped above 100.**
  Given:    `local_total` strictly greater than `max_input_tokens`,
            `calibration=None`.
  Expect:   `pct_used > 100`.
  Rationale: Docstring: "it is NOT clamped, so a context larger than the window
             reports above 100."

C23. **gauge pct_used is monotonic in local_total.**
  Given:    two calls with the same `max_input_tokens` and `calibration`, where the
            second `local_total` is strictly larger.
  Expect:   the second `pct_used` is strictly greater than the first.
  Rationale: A bigger context consumes a bigger share of a fixed window.

C24. **model_window returns a positive int for a known model.**
  Given:    `model == "gpt-4"`.
  Expect:   returns an `int` that is `> 0`.
  Rationale: PRD: a known model has a known input window. (We do not pin the exact
             number — only that it is a positive int.)

C25. **model_window returns None for an unknown model and never raises.**
  Given:    `model == "totally/nonexistent-model-xyz"`.
  Expect:   returns `None`; no exception raised.
  Rationale: Docstring: every unknown/absent case degrades to None, never raises.

## Intent ambiguities assumed past

- **Rounding mode** for percentages (`round` vs floor) is not specified. The contract
  asserts only relationships and tolerances (C11, C13, C20), never an exact rounded
  value, so the suite is robust to either choice.
- **`gauge` return type when window is known**: the docstring says `pct_used` is
  "(rounded) percentage", implying an `int`. We assert numeric ordering/ratio rather
  than the exact type, so a return of `int` or `float` both pass; if the team wants
  `int` enforced, add a `type()` check.
- **Whether `weight_pct` percentages can themselves exceed 100 under `"context"`**:
  not relevant for the tested multi-node conversations (each share < 100), so not
  asserted as a hard bound; only the sum tolerance (C11) is asserted.
- **Exact magnitude relationship of context vs window sums (C14)**: we assert the
  window sum is strictly less than the context sum, which holds whenever the window
  exceeds the conversation total (true for gpt-4 + a tiny conversation).
