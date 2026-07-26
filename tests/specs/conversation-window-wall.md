# Contract — the window wall (oversized `fetch` guard)

Scope: the guard that runs inside `ConversationCore.stream()` when the model calls the
`fetch` web tool, deciding whether the extracted page may be handed back to the model.
Derived from the PRD task and decisions D8 / D10 / D11 — not from reading any code.

This is a ~25-line change, so the contract is deliberately scoped to the clauses of the
acceptance criterion plus the invariants a realistic regression to *those* lines could
break. It is not a full contract for `stream()`, tool dispatch, persistence, or the
search tool. Items dropped on purpose: the shape of `tools` offered to the model, search
(non-fetch) tool behaviour, cancellation, error handling for a backend that raises, and
token-counting accuracy — none of them are touched by this change.

Terminology: "the estimate" is the size of the request the turn *would* send if the page
were handed back: the conversation context built for this turn, plus the live tool
round-trip so far, plus the `role="tool"` message carrying the page. "The window" is
`ctx.core.tokens.model_window(core.model)`.

---

C1. An oversized page is refused rather than handed to the model
  Given:    a turn whose round 1 ends in a `fetch` call on
            `https://blog.rust-lang.org/2024/09/05/Rust-1.81.0.html`; the backend
            returns a page far larger than the window; `model_window()` returns a known,
            small number (e.g. 4000).
  Expect:   the `role="tool"` message answering that `tool_call_id` carries a short
            explanation that contains the substring
            `too large for the remaining context window` and contains the fetched URL,
            and does **not** carry the page text. The page text never appears in any
            message sent to the provider.
  Rationale:D10 forbids silently truncating a page, and a request over the input window
            fails outright, so the only way to keep the turn alive is to answer the call
            with an explanation instead of content. D8 says a refused call takes the same
            shape as a failed one: the model is told, and decides for itself.
  Note:     the documented test seam (`TestProvider.tools_seen`) exposes only the `tools`
            argument, not the messages of each request, so this item cannot be asserted
            directly from the public interface. C2/C3/C4 pin its observable consequences.
            See Ambiguities A1.

C2. A refused fetch leaves a durable system breadcrumb
  Given:    the turn of C1, after `stream()` has been fully consumed.
  Expect:   the conversation line contains exactly one node with
            `node_type == "system"` and `role == "system"` whose `content` contains
            `too large for the remaining context window` and contains the fetched URL;
            and that node is still present, with the same content, when a *separate*
            `ConversationCore` calls `resume_conversation(core.conversation_id)`.
  Rationale:D11 requires the user to be able to see why an answer came up thin, including
            after quitting and resuming — the breadcrumb is durable state on the
            append-only graph, not a transient UI notice. "Exactly one" also pins that
            the refused fetch is not retried (D8: nothing is retried).

C3. A refused fetch appends no page node
  Given:    the turn of C1, after `stream()` has been fully consumed.
  Expect:   no node in the conversation line has `node_type == "context"` (equivalently:
            no node whose `meta["source_path"]` is the fetched URL), and no node anywhere
            in the line contains the page text.
  Rationale:appending the page would inject it into the context of every later turn —
            exactly the overflow the guard exists to prevent. The breadcrumb stands in
            its place and nothing else is added.

C4. The turn survives a refusal and still reaches an answer
  Given:    the turn of C1, where round 2 of the script is a settling text round whose
            tokens are the model's answer.
  Expect:   `stream()` yields that answer text (the concatenation of the yielded chunks
            contains the round-2 sentence), i.e. another round ran after the refusal and
            the generator completed without raising.
  Rationale:D11: the refusal is not a turn-ending error. The model is free to answer from
            what it already has, so a refused fetch must cost the user an answer, not the
            whole turn.

C5. On the success path the page arrives whole
  Given:    a turn whose round 1 calls `fetch` on
            `https://docs.python.org/3/whatsnew/3.12.html`; the backend returns a page
            that fits comfortably under a known window (`model_window()` returns a large
            number); round 2 settles with text.
  Expect:   the conversation line contains a node with `node_type == "context"`,
            `role == "context"`, `meta["source_path"]` equal to the fetched URL and
            `meta["origin"] == "model"`, whose `content` is **byte-for-byte equal** to the
            string the backend returned — no truncation, no ellipsis, no wrapper cap. No
            `node_type == "system"` breadcrumb is appended.
  Rationale:D10: a fetch returns the whole page; the token gauge and manual compaction are
            the user's lever, not a hidden cap. The guard is a wall, not a trimmer — when
            it does not fire it must leave the page untouched.

C6. An unknown window skips the guard entirely
  Given:    the same oversized page as C1, but `model_window()` returns `None` (litellm
            has no metadata for the model — true of the project's current default model).
  Expect:   the fetch proceeds exactly as on the success path: a `node_type == "context"`
            node is appended whose `content` is byte-for-byte equal to the oversized page,
            no `node_type == "system"` breadcrumb is appended, and `stream()` completes
            yielding the round-2 answer. In particular the refusal phrase
            `too large for the remaining context window` appears nowhere in the
            conversation.
  Rationale:this is an accepted, deliberate limitation, not a bug: with no window to
            compare against, the guard has no basis to refuse, so it stays out of the way
            and a genuinely too-big page fails later with the provider's own error. It is
            pinned by a test so that a future change cannot quietly turn "unknown window"
            into "refuse everything" (which would break the default model) or into a
            guessed default window.

---

## Ambiguities (and how I resolved them)

A1. **The model-facing tool result is not observable through the documented interface.**
    C1 is the heart of the behaviour, but the only documented recorder on `TestProvider`
    is `tools_seen` (the `tools` argument), so a test cannot inspect the `role="tool"`
    message that carried the refusal, nor prove the page text never reached the provider.
    I resolved this by testing C1's consequences (C2 breadcrumb content, C3 no page node,
    C4 answer still reached) and *not* by hand-rolling a spy provider — the brief says
    `TestProvider`/`TestSearch` are the only provider/backend a test may use, and a
    subclass overriding `stream()` would couple the test to that method's exact
    signature. **If the model-facing text is meant to be pinned directly, `TestProvider`
    needs to record the `messages` of each call** (e.g. a `messages_seen` list); that is a
    one-line addition to the double and I'd recommend it.

A2. **Whether `on_node` fires for the breadcrumb node is unspecified.** The `stream()`
    docstring says `on_node` is awaited for "each tool node, and the assistant node of
    every round after the first"; a refusal breadcrumb is neither, and D11 only requires
    it to be durable. The tests therefore assert the breadcrumb via `core.nodes` and via
    `resume_conversation`, and assert nothing about `on_node` receiving it. Worth
    deciding: a UI that only renders nodes it is handed through `on_node` would not show
    the breadcrumb until the next reload.

A3. **When the page node is persisted on the success path.** The intent states
    persistence explicitly only for the breadcrumb. The success-path tests therefore
    assert page wholeness on the in-memory line (`core.nodes`) and use
    `resume_conversation` only for the breadcrumb, whose durability is contracted.

A4. **What exactly the window is compared against** (whether the estimate reserves room
    for the model's output, and whether `model_window()` is a total or input-only
    budget). The tests avoid depending on the accounting by choosing values that are
    unambiguous either way: an oversized case ~15x the window, and a success case with a
    small page under a 200k window.

A5. **The exact refusal wording is not contracted.** Only the phrase
    `too large for the remaining context window` and the presence of the URL are asserted,
    always by substring, so the sentence can be reworded freely.

A6. **Whether `end_turn()` must be called for nodes appended during the turn to be
    durable.** The tests do not call `end_turn()`, since D11 describes the breadcrumb as
    persisted by the refusal itself (`add_system_message` "append… and persist"). If
    durability actually depends on `end_turn()`, that is a real gap: a crash or quit
    mid-turn would lose the explanation for a thin answer, which is the one thing the
    breadcrumb exists to survive.
