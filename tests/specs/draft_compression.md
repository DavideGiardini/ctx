# Behavioral contract — `ConversationCore.draft_compression`

Source of intent: ADR-0016 Amendment #6 (supersedes the old "Q10c" contract).
Code-blind: derived from the interface + prose intent, never from the implementation.

`draft_compression(start_id, end_id, prompt=None) -> AsyncIterator[str]` streams an
AI-drafted summary of a contiguous forward-view range. It is a meta-operation: it
validates the range, frames exactly two messages `[system, user]`, streams the
provider's tokens, and mutates/commits nothing. The generator body (validation +
empty-span check) runs on first iteration, so failures raise `ValueError` only once
iteration begins.

Marker constants: `OPEN_COMPRESS_MARKER` = `"<compress_this>"`,
`CLOSE_COMPRESS_MARKER` = `"</compress_this>"`.

---

C121. Exactly two messages, roles `["system", "user"]` in that order.
  Given:    a valid range in an active line, a provider that records the messages list.
  Expect:   the provider is handed a list of length 2; message[0].role == "system",
            message[1].role == "user".
  Rationale:Amendment #6 reframes the draft as a system instruction + a single user
            transcript. The two-message [system, user] shape is the core of the fix.

C122. A non-blank `prompt` becomes the SYSTEM message verbatim.
  Given:    `draft_compression(..., prompt="Please summarize this range concisely.")`.
  Expect:   the system message content equals exactly that custom string.
  Rationale:The user-editable prompt IS the whole system prompt (no longer a trailing
            user turn).

C123. A None or whitespace-only prompt falls back to DEFAULT_COMPRESSION_PROMPT.
  Given:    `prompt=None`, and separately `prompt="   "` (whitespace only).
  Expect:   in both cases the system message content equals DEFAULT_COMPRESSION_PROMPT.
  Rationale:Blank instruction must not send an empty system message; the default is the
            intended instruction. Whitespace-only is treated as blank.

C124. USER message is the whole active line as one transcript, target range marked.
  Given:    line `[u1, a1, u2, a2]`; draft a MIDDLE range (just `u2`) so there is both
            before-context (u1/a1) and after-context (a2).
  Expect:   the user message contains OPEN_COMPRESS_MARKER and CLOSE_COMPRESS_MARKER;
            the marked node's verbatim text ("second user message") appears BETWEEN the
            two markers; and an out-of-range node's text ("first user message") also
            appears in the user message, positioned BEFORE the open marker.
  Rationale:The model must see before + marked + after context in one user message so it
            never leads with a bare assistant turn and knows which threads continued.

C125. An empty marked span is refused BEFORE any provider call.
  Given:    a fresh, un-streamed assistant node `a3` (content == "") as the sole range
            `draft_compression(a3.id, a3.id)`.
  Expect:   raises ValueError; the provider is never invoked (recorder.called is False).
  Rationale:There is nothing to compress; drafting a summary of nothing is meaningless.

C126. Yields exactly the provider's tokens, in order.
  Given:    a valid range and a provider streaming ["Sum", "mary", " text"].
  Expect:   the async iterator yields ["Sum", "mary", " text"] in that exact order.
  Rationale:draft_compression is a pass-through stream of the drafted summary.

C127. The gauge is never touched, even when the provider reports Usage.
  Given:    a valid range, provider streams a token then fires Usage(50,10,60).
  Expect:   last_usage, calibration, and usage_generation are identical before and after
            the draft is fully consumed.
  Rationale:A draft is a meta-operation, never a gauge anchor; it must not calibrate.

C128. Range validation happens BEFORE any provider call.
  Given:    (a) unknown start_id, (b) unknown end_id, (c) reversed range (start after end).
  Expect:   each raises ValueError and the provider is never invoked.
  Rationale:Bad ranges must fail fast without spending a provider call.

C129. Drafting during a live stream (H2 guard) raises ValueError.
  Given:    a stream in progress (core.streaming is True).
  Expect:   draft_compression on a valid range raises ValueError.
  Rationale:Meta-operations are forbidden while the conversation is streaming.

C130. A fully-consumed draft mutates no conversation state.
  Given:    a valid range, draft consumed to completion.
  Expect:   current_view node ids are identical before and after; no node is added.
  Rationale:Drafting commits nothing; committing is the separate commit_compression.

C131. A range containing a compression node is refused (flat guard).
  Given:    a committed compression node K in the view; draft a range spanning K.
  Expect:   raises ValueError; the provider is never invoked.
  Rationale:Compression nodes may not be re-compressed; the slice must be flat.

---

## Intent ambiguities assumed past (flag for human)

- **Gauge attribute names.** The contract assumes the gauge is observable via
  `core.last_usage`, `core.calibration`, `core.usage_generation` (named in the intent).
  If these are private/renamed, C127 needs adjusting.
- **Message object shape.** The intent guarantees "roles [system, user]" but not whether
  each message is a dict (`{"role","content"}`) or an object (`.role`/`.content`). Tests
  accept either form via a small accessor helper.
- **Whole-line boundaries.** C124 assumes the "whole active line" is exactly the
  `current_view()` node list rendered in order; if extra system framing is injected into
  the user transcript, the before/after-context assertions still hold (they only check
  membership + ordering, not exact equality of the full transcript).
