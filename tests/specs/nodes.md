# Behavioral contract: `Node` factory classmethods

Module: `ctx/models/nodes.py` — import as `from ctx.models.nodes import Node`.

These four classmethods are the single source of truth for "construct a node of
kind X correctly". Each encodes exactly one valid field combination so call sites
cannot produce an invalid mix.

Field tuple under contract for every node: `(role, node_type, content,
conversation_id, meta)`, plus the dataclass-supplied unique `id`.

## PRD acceptance floor

N1, N3, N5, N7 below are the acceptance floor: each pins one factory's exact
field combination. N2 (system non-persistence) is also load-bearing per ADR 0014.

---

N1. `user` produces a user message turn
  Given:   content="Summarize the failing test output", conversation_id="conv-42"
  Expect:  role == "user"; node_type == "message"; content == "Summarize the failing
           test output"; conversation_id == "conv-42"; meta == {}.
  Rationale: Docstring specifies role="user", default node_type, given content,
           owning conversation_id, empty meta. This is the user-turn kind.

N2. `assistant` defaults content to the empty pre-stream state
  Given:   conversation_id="conv-42", no content argument
  Expect:  role == "assistant"; node_type == "message"; content == "";
           conversation_id == "conv-42"; meta == {}.
  Rationale: An assistant turn is created before any tokens arrive and filled in as
           it streams; the pre-stream content must be the empty string.

N3. `assistant` accepts explicit content
  Given:   conversation_id="conv-42", content="Here are three approaches:"
  Expect:  role == "assistant"; node_type == "message"; content == "Here are three
           approaches:"; conversation_id == "conv-42"; meta == {}.
  Rationale: Docstring: the given content (empty by default) is used when supplied.

N4. `system` produces a system breadcrumb with no conversation_id (LOAD-BEARING)
  Given:   content="Model set to: claude-opus-4"
  Expect:  role == "system"; node_type == "system"; content == "Model set to:
           claude-opus-4"; conversation_id == "" (the empty default); meta == {}.
  Rationale: System breadcrumbs are session-local UI notices, not durable turns.
           The storage layer skips nodes without a conversation_id, so the empty
           conversation_id is what keeps a system breadcrumb non-persistent. A
           regression threading a conversation_id in would silently change what
           gets persisted. The role AND node_type are both "system" (unlike the
           message kinds whose node_type is "message").

N5. `context` produces a context-import reference
  Given:   source_path="docs/architecture/adr-0014.md", conversation_id="conv-42"
  Expect:  role == "context"; node_type == "context"; content == "Included:
           docs/architecture/adr-0014.md"; conversation_id == "conv-42";
           meta == {"source_path": "docs/architecture/adr-0014.md"}.
  Rationale: Docstring pins all five fields, including the derived human-readable
           content and the meta entry the context builder later loads.

N6. `context` derives content by literal prefixing of the source path
  Given:   source_path="src/ctx/models/nodes.py", conversation_id="c1"
  Expect:  content == "Included: src/ctx/models/nodes.py" exactly (prefix "Included: "
           with one trailing space, then the verbatim source_path).
  Rationale: Content is the literal "Included: " + source_path. Pins the exact
           prefix and that the path is not transformed (basename, normalization, etc.).

N7. `context` stores the exact source path in meta and nowhere mangled
  Given:   source_path="a/b/c.txt", conversation_id="c1"
  Expect:  meta == {"source_path": "a/b/c.txt"} — single key "source_path", value is
           the verbatim source_path.
  Rationale: The context builder loads meta["source_path"]; the value must be the
           path as given, not the prettified content string.

N8. Each call gets a fresh unique id
  Given:   two separate factory calls (any kinds)
  Expect:  the two nodes have distinct, non-empty `id` strings.
  Rationale: id uses the dataclass default_factory (uuid4().hex); factories must not
           pin or share an id.

N9. Distinct calls do not share the same meta dict object (no aliasing)
  Given:   two separate calls to the same factory (e.g. two `user` nodes)
  Expect:  the two nodes' `meta` are not the same object (`a.meta is not b.meta`);
           mutating one node's meta does not change the other's.
  Rationale: Mutable-default aliasing would let one turn's metadata leak into
           another. Each node must own its own meta dict.

N10. context meta is independent per call
  Given:   two `context` calls with different source_paths
  Expect:  each node's meta reflects only its own source_path; the dicts are
           distinct objects.
  Rationale: Same aliasing guarantee as N9, specialized to the factory that actually
           populates meta.

## Intent ambiguities assumed past

- Whitespace in `content` (e.g. leading/trailing spaces in user content) is assumed
  to be preserved verbatim; the docstrings say "the given content" with no trimming.
- For `context`, the docstring says content is "Included: <source_path>"; I read the
  separator as exactly ", " -> "Included: " (the word, a colon, one space). If the
  real intent is a different separator, N6 is the test to adjust.
- No factory is documented to validate or reject inputs (empty content, empty
  conversation_id), so no error-raising behavior is contracted; none is tested.
