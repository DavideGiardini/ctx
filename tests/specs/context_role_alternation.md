# Behavioral contract — `build_context` role-alternation invariant

Scope: the single invariant that no two adjacent message dicts share a role,
plus the user-run merge rule (with explicit `"\n\n"` separator). This is a tiny
(~13-line) change; broader `build_context` behavior (imports, error markers,
ordering across kinds) is covered by other suites and deliberately NOT re-tested
here.

Global invariant (must hold for every case below):
`for a, b in zip(out, out[1:]): a["role"] != b["role"]`.

---

C1. A dropped node does not split a user run.
  Given:   `[context("A"), dropped-system, context("B")]`, where the system node's
           `goes_to_model()` is False and both context files load to distinct bodies.
  Expect:  Exactly ONE message is returned, `role == "user"`, its content contains
           both loaded bodies, and the two bodies are separated by `"\n\n"`. The
           dropped system emits nothing and does not break the merge.
  Rationale: ADR-0016 removed the "dropped node = coalescing boundary" rule; strict
           providers reject two adjacent user dicts, so the run must stay merged.

C2. Compression summary followed by a user turn merges with a separator.
  Given:   `[compression("SUMMARY"), user("QUESTION")]`.
  Expect:  Exactly ONE message, `role == "user"`. Its content contains a
           `</conversation_summary>` closing tag AND the user text, and the closing
           tag is NOT immediately followed by the user text — a `"\n\n"` separator
           sits between the summary block and the following user text.
  Rationale: The summary and the following user turn are both user-role material and
           must merge into one dict; running the closing tag straight into the user
           text (no whitespace) is the regression being locked out.

C3. Two consecutive plain user nodes merge into one dict with a separator.
  Given:   `[user("FIRST"), user("SECOND")]`.
  Expect:  Exactly ONE message, `role == "user"`, content contains both texts with a
           `"\n\n"` separator between them (never concatenated with no separator, and
           never two adjacent user dicts).
  Rationale: Consecutive user-role material always coalesces; separator preserves
           readability and prevents a same-role adjacency.

C4. An assistant node breaks a user run.
  Given:   `[user("BEFORE"), assistant("REPLY"), user("AFTER")]`.
  Expect:  Exactly THREE messages with roles `["user", "assistant", "user"]`
           (alternating). The material after the assistant starts a fresh user dict
           rather than merging back into the first user message.
  Rationale: The assistant message is the only thing that terminates a user run;
           material after it naturally begins a new user turn.
