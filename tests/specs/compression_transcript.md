# Behavioral contract — `build_compression_transcript`

Module: `ctx/core/context.py`
Signature: `build_compression_transcript(nodes: list[Node], range_ids: list[str], load_file: Callable[[str], str]) -> str`

Derived purely from the docstring + PRD acceptance criteria + ADR-0016 A#6. This is a
SMALL pure renderer; the contract is scoped to what a realistic regression to this
helper could break (the 5 acceptance items plus the two format/edge invariants the
docstring pins).

## Assumptions I had to make (flag for adjudication)
- **A1 (label capitalization).** The docstring writes blocks as `"{Role}:\n{body}"` and
  gives literal examples `User:` / `Assistant:`. I assume the label is the role
  Title-cased: `user -> "User:"`, `assistant -> "Assistant:"`, and that a context node
  and a committed compression are BOTH emitted with the `User:` label (their
  "model-facing role" per the docstring). Tests assert the label substring, not the
  exact byte layout, except where noted.
- **A2 (block body join).** The label and body are on separate lines (`"{Role}:\n{body}"`),
  so the body text appears in the transcript verbatim on the line(s) after its label.
  Tests assert the body substring is present and correctly ordered, not exact newline
  counts.
- **A3 (separator).** "Blocks are separated by a blank line." Tests do not pin the exact
  separator bytes beyond ordering relationships, to avoid over-coupling.
- **A4 (empty-span layout).** For an empty marked span the two marker lines are emitted
  as "an adjacent empty pair". I interpret this as: `<compress_this>` appears, then
  `</compress_this>` appears, with NO block body text between them (whitespace only).

## Contract items

C1. Marked range appears between the marker lines.
  Given:    nodes = [user "before", user "middle", user "after"], range_ids = [middle.id].
  Expect:   `<compress_this>` appears before "middle" and `</compress_this>` appears
            after "middle" (index(open) < index("middle") < index(close)); both markers
            present exactly.
  Rationale: Acceptance #1 — the model must see precisely which nodes to compress,
             bracketed by the markers.

C2. Out-of-range nodes sit outside the markers, on the correct side.
  Given:    same setup as C1.
  Expect:   index("before") < index(`<compress_this>`) and
            index("after") > index(`</compress_this>`).
  Rationale: Acceptance #2 — before/after context frames the range so the model does
             not treat the instruction as a naked meta-request.

C3. A `context` node contributes its loaded file body, not the "Included:" label.
  Given:    a single `Node.context("src/service.py", conv)` whose id is in range_ids;
            load_file maps "src/service.py" -> "class Service:\n    pass".
  Expect:   the file body "class Service:" appears in the transcript; the literal
            "Included:" does NOT appear; the block is labeled `User:`.
  Rationale: Acceptance #3 + docstring — model sees the actual imported content, not the
             UI breadcrumb; context's model-facing role is user.

C4. A committed compression `K` contributes its summary text.
  Given:    a single `Node.compression("Earlier the user set up auth and DB config.", conv,
            range_ids=[])` whose id is in range_ids.
  Expect:   the summary text "Earlier the user set up auth and DB config." appears; the
            block is labeled `User:`.
  Rationale: Acceptance #4 + docstring — a prior compression node re-enters the transcript
             as its summary, with user model-facing role.

C5. A `system` breadcrumb emits nothing.
  Given:    nodes = [user "keep before", system "INTERNAL BREADCRUMB XYZ", user "keep after"].
  Expect:   "INTERNAL BREADCRUMB XYZ" does NOT appear anywhere in the transcript, while
            "keep before" and "keep after" both do.
  Rationale: Acceptance #5 + docstring — non-`goes_to_model` nodes (system/expand) are
             dropped entirely.

C6. Turn blocks are labeled by role and bodies are ordered under their label.
  Given:    nodes = [user "question about pricing", assistant "here is the pricing"],
            range_ids empty (or covering neither uniquely).
  Expect:   "User:" appears and precedes "question about pricing"; "Assistant:" appears
            and precedes "here is the pricing"; the user block precedes the assistant
            block in node order.
  Rationale: Docstring — `user`/`assistant` turns are labeled `User:`/`Assistant:` in
             node order (A1).

C7. Empty marked span still emits both markers as an adjacent pair.
  Given:    nodes = [user "context before", user "" (empty body, dropped)], range_ids =
            [empty_node.id]; the only in-range node produces no block.
  Expect:   both `<compress_this>` and `</compress_this>` appear; the text between them
            (stripped) is empty (no block body); "context before" appears above the open
            marker.
  Rationale: Docstring — empty-span callers must be able to detect that nothing was
             produced; empty-body blocks are dropped, but the marker pair remains.
