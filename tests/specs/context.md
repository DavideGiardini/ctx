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

**C14. A context node whose file fails to load surfaces a VISIBLE error marker; the
rest survives.** *(changed 2026-06-26, Ralph task "Harden build_context against
bad/empty nodes", refs 0007 #1: a failed import used to vanish silently — the file
never reached the model and the UI showed nothing. It is now made visible.)*
Given `[context source_path="missing.txt", user "still here"]` where loading
"missing.txt" raises `FileNotFoundError` (an `OSError`) → build does not raise; the
failed node emits a user-role `context_import` marker whose content references
`"missing.txt"` and carries an error indication (`error`), and never becomes
assistant content; the following `"still here"` user turn still appears.

**C15. A failed context marker coalesces into the adjacent user turn (same rule as a
successful import).** *(changed 2026-06-26 — see C14.)*
Given `[context source_path="missing.txt" (raises), user "my question"]` → exactly one
`role=="user"` dict whose content contains `"my question"`, the source path
`"missing.txt"`, an `error` indication, and the `context_import` marker. The failed
marker must NOT contain a (non-existent) loaded body.

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

**C20. A context node whose loader raises `ValueError` surfaces a VISIBLE error
marker; the rest survives.** *(changed 2026-06-26 — see C14. The injected loader is
the workspace's sandboxed reader, which raises `ValueError` when a path escapes the
context directory — a distinct failure from a missing file (C14, `OSError`), but
treated the same: surfaced, not silently dropped, and never crashing the build.)*
Given `[context source_path="../escape.txt", user "still here"]` where loading
"../escape.txt" raises `ValueError` → build does not raise; output contains a
`role=="user"` dict whose content references `"../escape.txt"` with an `error`
indication and the `context_import` marker, never becoming assistant content; the
`"still here"` user turn still appears.

**C23. Empty `user`/`assistant` nodes produce no message.** *(added 2026-06-26, same
task, ref 0007 #2: a cancelled/failed stream can persist a `content==""` assistant
node; replayed through `build_context` it became `{"role":"assistant","content":""}`,
which several provider APIs reject. Now skipped.)*
A `user` or `assistant` node with `content == ""` yields no message dict for that node
(no output dict has empty content). An empty assistant node between two real user turns
leaves no assistant dict; an empty user node contributes nothing. This applies to plain
message nodes only — a *context* node that successfully loads an empty file body still
emits a marked import (C19, unchanged), and a *failed* context load still emits its
error marker (C14/C20), since both are non-empty.

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

**C24. A dropped node (system) between user-side items does NOT break coalescing.**
*(added 2026-07-03, Sprint 3 task 1; revised 2026-07-06, task 34.)* A node that does
not reach the model (`goes_to_model()` False — e.g. a system breadcrumb) emits nothing
and does **not** act as a boundary: user-side material before it merges with user-side
material after it. Given `[user "u1", system "note", user "u2"]` → ONE `role=="user"`
dict holding "u1" then "u2", separated by a blank line. This upholds the role-alternation
output invariant (no two adjacent same-role dicts) that strict providers require; the
earlier "dropped node is a boundary" rule violated it by emitting two adjacent user
dicts. The compression-summary rendering and its merging with adjacent user material
are contracted in `tests/specs/compression_node.md`. See also
`tests/specs/context_role_alternation.md` for the invariant.

## Adjudication notes
- **A1 (wrapper token):** marker is `context_import`, source path is an attribute. Assert
  substrings, never byte-exact format.
- **A2 (merge joiner):** assert combined-content substrings and relative order only — not the
  exact separator (that would couple to implementation).
- **A4:** system nodes are exclusively UI notices → C4 drops all of them.
- **A5 (unknown roles/types):** no product requirement; C4's drop-path coverage suffices.

## Mutation testing (mutmut)
*(STALE since 2026-06-26 — the load-failure branch changed from a silent skip to a
visible error marker (C14/C20) and empty `user`/`assistant` nodes are now skipped
(C23). The figures below predate that change and need a re-run.)*

Prior run: coverage 100% (lines + branches); mutmut **66 mutants, 59 killed, 7
survivors — all equivalent**, every survivor mutating the *arguments to
`logger.warning(...)`* in the skip branches (log wording / interpolated values only),
not return value or control flow. We deliberately do **not** assert on log text:
logging here is a diagnostic side-channel, not part of the model-facing output, and
asserting exact log strings would couple tests to the implementation. Re-triage the
new branches with `mutmut` in a future pass.
