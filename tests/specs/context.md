# Behavioral contract — `ctx/core/context.py` :: `build_context`

The oracle of record for `build_context(nodes, load_file) -> list[dict]`. Authored
code-blind from intent (see `.claude/skills/write-tests`), then human-adjudicated.
Tests in `tests/test_context.py` cite these item ids. **When behavior changes,
update this contract first**, then the tests.

`build_context` translates an ordered list of `Node`s into the `messages` array
(`[{"role", "content"}, …]`) sent to the LLM. Only model-bound material appears:
user turns, assistant turns, and imported context (as user material). The injected
`load_file(source_path) -> str` keeps it pure (no filesystem I/O of its own).

## Contract

**C1. Happy path: a user/assistant exchange round-trips in order.**
Given `[user "What is X?", assistant "X is Y"]` → output is exactly
`[{"role":"user","content":"What is X?"}, {"role":"assistant","content":"X is Y"}]`,
in that order, content verbatim.

**C2. A user node is forwarded with role "user".**
Given `[user "hello"]` → exactly `[{"role":"user","content":"hello"}]`.

**C3. An assistant node is forwarded with role "assistant", as its own message.**
Given `[user "hi", assistant "hey there"]` → the second dict equals
`{"role":"assistant","content":"hey there"}`.

**C4. System notice nodes are dropped entirely.** *(adjudicated: system = UI-only,
always dropped — there is no model-bound system prompt through this function.)*
Given `[system "Model set to Opus", user "hello"]` → `[{"role":"user","content":"hello"}]`;
no output dict has role "system"; `"Model set to"` appears in no content.

**C5. A context node expands to imported file content as user material.**
Given `[context source_path="notes.txt"]`, loader `{"notes.txt":"the file body"}` →
exactly one dict, `role=="user"`, whose content contains the substrings `"the file body"`,
`"notes.txt"`, and `"context_import"` (marked as imported).

**C6. Context wrapping surfaces source + content (observable substrings, not byte-exact).**
Same as C5 → the user dict's content includes both `"notes.txt"` and `"the file body"`.
The context node's *own* `content` field (e.g. an `"Included: …"` label) does **not**
leak into the output — only the loaded file content does. *(resolves A6)*

**C7. Context immediately followed by a user question merges into ONE user message.**
Given `[context source_path="doc.md", user "summarize this"]`, loader `{"doc.md":"DOC BODY"}` →
a single `role=="user"` dict containing both `"DOC BODY"` and `"summarize this"`, with the
imported content appearing before the question text. Not two separate user dicts.

**C8. Context with no following user message is emitted as a standalone user message.**
Given `[context source_path="solo.txt"]`, loader `{"solo.txt":"SOLO BODY"}` → exactly one
`role=="user"` dict whose content contains `"SOLO BODY"` and `"solo.txt"`.

**C9. Context merges into the next USER message, never into an assistant message.**
Given `[context source_path="a.txt", assistant "prior answer", user "now my question"]`,
loader `{"a.txt":"A BODY"}` → no assistant dict contains `"A BODY"`; `"A BODY"` appears in a
`role=="user"` dict.

**C10. Two adjacent user nodes combine into one user message.**
Given `[user "part one", user "part two"]` → a single `role=="user"` dict containing both,
with `"part one"` before `"part two"`. Not two user dicts.

**C11. An assistant turn between two user turns prevents the merge.**
Given `[user "u1", assistant "a1", user "u2"]` → three dicts
`[user "u1", assistant "a1", user "u2"]`; the two user turns are not merged.

**C12. Overall ordering is preserved across mixed node types.**
Given `[user "u1", assistant "a1", context source_path="c.txt", user "u2"]`,
loader `{"c.txt":"C BODY"}` → a user dict with "u1", then an assistant dict with "a1", then
a user dict containing both "C BODY" and "u2", in that relative order.

**C13. Empty input yields empty output.**
Given `[]` → `[]`.

**C14. A context node whose file fails to load is skipped; the rest survives.**
Given `[context source_path="missing.txt", user "still here"]` where loading "missing.txt"
raises `FileNotFoundError` (an `OSError`) → build does not raise; output contains a
`role=="user"` dict containing `"still here"`; the failed node contributes no
`"context_import"` text.

**C15. A failed context node does not corrupt or force-merge an adjacent user turn.**
Given `[context source_path="missing.txt" (raises), user "my question"]` → exactly
`[{"role":"user","content":"my question"}]` — no wrapper text, no source path, no partial body.

**C16. A context node missing its `source_path` is skipped.**
Given `[context with meta lacking "source_path", user "after"]` → build does not raise;
output contains a `role=="user"` dict with content `"after"`; nothing is marked as imported
for the malformed node.

**C17. Multiple imports each load their own path and stay ordered within the merged run.**
*(corrected during the coverage loop: the original "two separate dicts" oracle contradicted
C10 — with no assistant turn to break the run, all adjacent user-side material coalesces into
one user message. The real guarantee is per-path loading + ordering, not separate dicts.)*
Given `[context source_path="one.txt", user "q1", context source_path="two.txt", user "q2"]`,
loader `{"one.txt":"ONE","two.txt":"TWO"}` → a single `role=="user"` dict containing "ONE",
"q1", "TWO", "q2", "one.txt", "two.txt"; in conversation order
`ONE < q1 < TWO < q2`, with each import preceding its own question. No assistant turn means no
message boundary; an assistant turn between the pairs would split them (see C11).

**C18. Purity: identical inputs → identical output; inputs not mutated.**
Calling twice with the same `nodes` and loader returns equal lists (`==`); the input list and
its `Node` objects are unchanged afterward; the only side effect is calls to `load_file`.

**C19. A successfully-loaded but EMPTY file still produces a marked import.** *(adjudicated:
a successful empty load ≠ a failed load — emit the empty wrapper so the model knows the file
exists and is empty.)*
Given `[context source_path="empty.txt", user "go"]`, loader `{"empty.txt":""}` → build does not
raise; a single `role=="user"` dict whose content contains `"go"`, `"empty.txt"`, and
`"context_import"`.

**C20. A context node whose loader raises `ValueError` is skipped; the rest survives.**
*(The injected loader is the workspace's sandboxed reader, which raises `ValueError` when a
path escapes the context directory — a distinct failure from a missing file (C14, `OSError`).
A rejected/escaping import must be skipped exactly like a failed read, not crash the build.)*
Given `[context source_path="../escape.txt", user "still here"]` where loading
"../escape.txt" raises `ValueError` → build does not raise; output contains a `role=="user"`
dict containing `"still here"`; the rejected node contributes no `"context_import"` text.

**C21. A context node is imported as USER material regardless of its own declared role.**
*(adjudicated A5 extended: a "context" node's `role` field is irrelevant — imported file
content is always user-side material. A context node declared with `role="assistant"` must
NOT become an assistant message.)*
Given `[context source_path="a.txt" with role="assistant", user "q"]`,
loader `{"a.txt":"A BODY"}` → no assistant dict contains `"A BODY"`; `"A BODY"` appears in a
`role=="user"` dict (merged with `"q"`, per C7).

**C22. A context node whose `source_path` is the empty string is skipped.**
*(An empty `source_path` is "no source", indistinguishable from an absent one (C16) — there
is nothing to import.)*
Given `[context with meta {"source_path": ""}, user "after"]` → build does not raise; output
contains a `role=="user"` dict with content `"after"`; nothing is marked as imported for the
empty-source node. (Distinguishes "no source" from `source_path is None`.)

## Adjudication notes
- **A1 (wrapper token):** marker is `context_import`, source path is an attribute. Assert
  substrings, never byte-exact format.
- **A2 (merge joiner):** assert combined-content substrings and relative order only — not the
  exact separator (that would couple to implementation).
- **A4:** system nodes are exclusively UI notices → C4 drops all of them.
- **A5 (unknown roles/types):** no product requirement; C4's drop-path coverage suffices.

## Mutation testing (mutmut)
Coverage is 100% (lines + branches). mutmut: **66 mutants, 59 killed, 7 survivors —
all equivalent.** Every survivor mutates the *arguments to `logger.warning(...)`* in the
two skip branches (missing `source_path`; load failure) — log wording / interpolated
values only. They do not change the return value or control flow, so they are equivalent
with respect to this behavioral contract. We deliberately do **not** assert on log text:
logging here is a diagnostic side-channel, not part of the model-facing output, and
asserting exact log strings would couple tests to the implementation. Re-triage only if a
future change makes the warnings contractual (e.g. surfaced to the user).
