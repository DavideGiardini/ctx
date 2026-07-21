> **SUPERSEDED (ctx0 Phase 1).** `stream()` no longer touches the streaming
> flag; every ending is recorded by `end_turn` (see `conversation.md` §Turn
> lifecycle, C106). The C1/C2 test file was deleted; the guard behavior that
> C2 exercised (compression allowed once the turn ends) is covered by C112.

# Contract: `ConversationCore.stream()` clears the streaming flag on any exit

Scope: one behavioral invariant guarding a ~10-line try/finally reshuffle in
`ConversationCore.stream()`. Derived purely from intent, not implementation.

C1. `streaming` returns to `False` even when the pre-stream context build raises
  Given:    A `ConversationCore` whose injected loader raises on `read_file`, with one
            `/include`d `context` node in the view (so the context build actually
            reads a file). A turn has been `submit()`ted (so the in-flight flag is set).
  Expect:   Draining `stream(assistant_node)` propagates the loader's error (an
            exception is raised out of the async generator), AND immediately afterward
            `core.streaming is False`.
  Rationale:Intent states the flag must return to `False` after `stream()` finishes for
            ANY reason, including a failure in the context build before the provider is
            ever contacted. Doing the build outside the flag-managing try/finally would
            leave `streaming` stuck `True` forever.

C2. A stuck flag would block later compression; clearing it keeps compression usable
  Given:    Same core, immediately after the failed `stream()` above. A valid 1-node
            range chosen from `current_view()`.
  Expect:   `commit_compression(start_id, end_id, summary)` succeeds and returns a
            `Node` (does NOT raise `ValueError("cannot compress while a turn is
            streaming")`).
  Rationale:Compression ops refuse to run while `streaming` is True. The whole point of
            clearing the flag on a failed build is that a subsequent compression on a
            valid range is not permanently blocked by a stuck flag.

## Assumptions / ambiguities flagged for a human
- Import path for `ConversationCore` is assumed to be `ctx.conversation.core`. If the
  module lives elsewhere, only the import line needs adjustment; the contract holds.
- C1 and C2 are two facets of the same regression and are exercised together in a
  single test (the scope budget calls for the fewest tests — one).
