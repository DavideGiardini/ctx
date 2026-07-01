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

## Append-only graph edges (ADR-0016)

`Node` gained two nullable graph-edge fields, `prev_id` and `compressed_into`, both
defaulting to `None`. `prev_id` is the predecessor on the active line (None = root;
siblings sharing a prev_id are branches); `compressed_into` points at the compression
node that folds this one (None until compression exists). Both default to None so the
factories and every existing call site are unaffected — edges are wired later by the
conversation core, never by the factory. These items cover ONLY the two new fields and
their interaction with the factories + dataclass semantics.

N11. `user` factory leaves both edges None
  Given:   Node.user(content="What is the capital of France?", conversation_id="conv-42")
  Expect:  node.prev_id is None AND node.compressed_into is None.
  Rationale: Factories are unaware of graph edges; a freshly built user node carries no
           predecessor and no compression link.

N12. `assistant` factory leaves both edges None
  Given:   Node.assistant(conversation_id="conv-42", content="Paris.")
  Expect:  node.prev_id is None AND node.compressed_into is None.
  Rationale: The assistant factory sets no edges; edges are the caller's concern.

N13. `system` factory leaves both edges None
  Given:   Node.system(content="You are a helpful assistant.", conversation_id="conv-42")
  Expect:  node.prev_id is None AND node.compressed_into is None.
  Rationale: Same as N11 for the system factory.

N14. `context` factory leaves both edges None
  Given:   Node.context(source_path="docs/architecture.md", conversation_id="conv-42")
  Expect:  node.prev_id is None AND node.compressed_into is None.
  Rationale: Same as N11 for the context factory.

N15. Bare `Node()` default-constructs both edges as None
  Given:   Node() with no edge arguments supplied
  Expect:  node.prev_id is None AND node.compressed_into is None.
  Rationale: Both fields default to None so factories and existing call sites are
           unaffected; default construction must not invent a predecessor or a
           compression target.

N16. `prev_id` round-trips an explicit non-None value
  Given:   Node(prev_id="node-abc123") constructed with an explicit predecessor id
  Expect:  node.prev_id == "node-abc123" read back identically; compressed_into remains
           None (not supplied).
  Rationale: prev_id is an ordinary dataclass field storing the line predecessor; a value
           passed in must be retained exactly.

N17. `compressed_into` round-trips an explicit non-None value
  Given:   Node(compressed_into="compression-node-xyz789")
  Expect:  node.compressed_into == "compression-node-xyz789" read back identically;
           prev_id remains None (not supplied).
  Rationale: compressed_into is an ordinary dataclass field pointing at the folding
           compression node; a value passed in must be retained exactly.

N18. Both edges round-trip together when both supplied
  Given:   Node(prev_id="node-parent-001", compressed_into="node-compress-002")
  Expect:  node.prev_id == "node-parent-001" AND node.compressed_into == "node-compress-002".
  Rationale: The two fields are independent; supplying both retains both exactly with no
           interference.

N19. Edges are assignable after construction
  Given:   a node with default edges (e.g. make_node()), then node.prev_id and
           node.compressed_into assigned afterwards
  Expect:  the assigned values are read back exactly.
  Rationale: Edges are set later by the caller (the conversation core); the fields must be
           plain mutable dataclass attributes so the core can wire the graph after the
           factory returns.

N20. `prev_id` participates in dataclass equality (differing prev_id ⇒ unequal)
  Given:   two nodes field-for-field identical (same explicit id, conversation_id, role,
           content, node_type, meta, compressed_into) EXCEPT one has prev_id="node-A" and
           the other prev_id="node-B"
  Expect:  the two nodes compare unequal (a != b).
  Rationale: prev_id is an ordinary dataclass field and must be included in __eq__; nodes
           on different lines must be distinguishable. *(adjudicated: tests fix a shared
           explicit `id` — `id` defaults to a fresh uuid4().hex, so isolating the edge's
           effect on equality requires equal ids and identical other fields.)*

N21. `compressed_into` participates in dataclass equality (differing ⇒ unequal)
  Given:   two nodes field-for-field identical (shared explicit id) EXCEPT one has
           compressed_into="node-C" and the other compressed_into="node-D"
  Expect:  the two nodes compare unequal (a != b).
  Rationale: compressed_into is an ordinary dataclass field and must be included in __eq__;
           a compressed node must be distinguishable from an un/differently-compressed one.

N22. Nodes identical including both edges compare equal
  Given:   two nodes with the SAME explicit id, conversation_id, role, content, node_type,
           meta, prev_id ("node-P"), and compressed_into ("node-Q")
  Expect:  the two nodes compare equal (a == b).
  Rationale: When every field including both edges matches, __eq__ reports equality; the new
           fields must not spuriously break equality of otherwise-identical nodes.

## Intent ambiguities assumed past

- Whitespace in `content` (e.g. leading/trailing spaces in user content) is assumed
  to be preserved verbatim; the docstrings say "the given content" with no trimming.
- For `context`, the docstring says content is "Included: <source_path>"; I read the
  separator as exactly ", " -> "Included: " (the word, a colon, one space). If the
  real intent is a different separator, N6 is the test to adjust.
- No factory is documented to validate or reject inputs (empty content, empty
  conversation_id), so no error-raising behavior is contracted; none is tested.

## Mutation testing (mutmut)
`ctx/models/nodes.py` is intentionally **not** in `[tool.mutmut].only_mutate`: this mutmut
version generates **zero mutants** for the module (a pure `@dataclass` whose only logic lives
in `@classmethod` factories + `goes_to_model`; no trampolines are produced), so a focused run
`'ctx.models.nodes.*'` errors with "nothing matches" and there is nothing to gate. The
guarantees here are the contract (N1–N22) + 100% branch coverage. The graph-edge fields
(N11–N22) are also exercised end-to-end under the storage round-trip (storage.md C28/C29) and
the conversation graph tests (conversation.md C67–C78), whose modules *are* mutation-gated.
