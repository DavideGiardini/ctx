# Behavioral contract — `ctx/core/conversation.py` :: `ConversationCore`

The oracle of record for `ConversationCore` — the deep module that owns conversation
STATE, command handling, and the streaming lifecycle, coordinating storage, the LLM
provider, and the workspace through their protocols. Authored code-blind from intent
(see `.claude/skills/write-tests`), then human-adjudicated. Tests in
`tests/test_conversation.py` cite these item ids. **When behavior changes, update this
contract first**, then the tests.

All "Expect" clauses describe observable behavior — public state (`nodes`,
`conversation_id`, `conversation_title`, `model`), return values, raised exceptions, and
what `repo.load(...)` returns after a reload — never internal structure or the exact text
of a notice. Notice wording is implementation detail: tests assert on substrings (model
name, error message), role/`node_type`, and `conversation_id`, never full literal strings.

## Wiring & fixtures
Under test: `ConversationCore(repo, test_provider([...tokens...]), workspace)` where
- `repo` = real `ConversationRepository` on a temp-file SQLite DB, already `init()`-ed;
- `test_provider` = factory `(tokens) -> TestProvider` (canned async stream, in order);
- `workspace` = real `Workspace` in a temp dir, already `ensure()`-ed;
- `make_node` = `Node` factory.

Some items need collaborators beyond `TestProvider`; tests may build small in-file fakes
(blind agent has no read tools but can author plain classes):
- a **capturing provider** whose `stream` records the `messages` it was handed (C38);
- a **failing provider** whose `stream` yields a few tokens then raises (C41);
- a **save-counting spy** wrapping `repo` to assert persist-call count (C42).

## Collaborator behaviors referenced (already specced — not re-derived here)
- **StoragePort**: `save(id, title, nodes)` SKIPS any node with `conversation_id == ""`
  (transient notices are never persisted); `load(id)` returns saved nodes in insertion
  order or `[]` for an unknown id. (see `storage.md`)
- **Provider/TestProvider**: `stream(messages, model)` yields its canned tokens in order,
  independent of inputs; `check_connectivity` returns `(True, "ok")`. (see `provider`)
- **build_context(nodes, load_file)**: pure; expands `context` nodes via
  `meta["source_path"]`, drops `system` nodes, turns user/assistant into message dicts.
  (see `context.md`)
- **Workspace**: `ensure()` creates dirs; `read_file` is the loader passed to build_context.

## Contract

### setup()

**C1. `setup()` prepares the environment without error and is tolerant of an
already-prepared one.** Given a freshly constructed core wired to the (already
ensured/init) fixtures → `setup()` raises nothing and the core is usable afterward (a
subsequent `submit` succeeds).

### submit(text) — first message

**C2. First submit assigns a non-empty `conversation_id`.** Given a fresh core
(`conversation_id == ""`, `nodes == []`) → after `submit("…")`, `conversation_id` is a
non-empty string.

**C3. First submit derives the title from the first message (short case).** Given a fresh
core and a first message shorter than `MAX_TITLE_LENGTH` with no newlines → after submit,
`conversation_title == text` exactly.

**C4. First submit flattens newlines in the derived title.** Given a first message with
length ≤ `MAX_TITLE_LENGTH` containing one or more `\n` → `conversation_title` contains no
`\n`; each newline is a space; other characters preserved in order.

**C5. First submit truncates an over-long title to `MAX_TITLE_LENGTH` characters.** Given
a first message strictly longer than `MAX_TITLE_LENGTH` (no newlines) → `len(title) ==
MAX_TITLE_LENGTH` and `title == text[:MAX_TITLE_LENGTH]` (the first MAX_TITLE_LENGTH
characters, by character count). *(adjudicated B: truncation is by characters from the
front; flattening and truncation tested on separate inputs so the test never depends on
their order of application.)*

**C6. First submit appends a user node then an empty assistant node, in that order.**
Given `nodes == []` → after submit, `len(nodes) == 2`; `nodes[-2].role == "user"` with
`content == text`; `nodes[-1].role == "assistant"` with `content == ""`.

**C7. Both appended turn-nodes carry the active `conversation_id`.** Given a fresh core
after first submit → the returned user node and assistant node each have
`conversation_id == core.conversation_id` (non-empty). *(adjudicated H: the empty
assistant node is a real conversation node, not a transient notice — so its reply persists
on stream.)*

**C8. submit returns exactly the two appended nodes as `(user, assistant)`.** Given a
fresh core → `submit` returns a 2-tuple where `user_node is nodes[-2]` and
`assistant_node is nodes[-1]`; roles are `"user"` and `"assistant"`.

**C9. First submit persists the conversation (the user turn is reloadable).** Given a
fresh core after `submit("real text")` against `repo` → `repo.load(conversation_id)`
returns nodes including a `user` node with `content == "real text"`. (The empty assistant
node need not be present — submit persists before appending it; see G.)

### submit(text) — second message (same conversation)

**C10. Second submit keeps `conversation_id` stable.** Given a core after one submit, then
a second submit → `conversation_id` is unchanged (and non-empty).

**C11. Second submit keeps the original title.** Given a first message deriving title T,
then a second submit with different text → `conversation_title == T` (still from the FIRST
message).

**C12. Second submit still appends user + empty assistant.** Given a core after one submit
(length N), then a second submit with `text2` → length increases by 2; `nodes[-2]` is a
`user` node with `content == text2`; `nodes[-1]` is an `assistant` node with `content == ""`.

### set_model(model)

**C13. set_model records the new model.** Given any core → after `set_model("some/other")`,
`core.model == "some/other"`.

**C14. set_model appends a system notice naming the model, as the last node, and returns
it.** Given any core → after `set_model(m)`, `nodes[-1]` is a system-notice node
(`role == "system"`, `node_type == "system"`) whose `content` contains `m` as a substring;
the return value `is nodes[-1]`.

**C15. The set_model notice persists within an active conversation.** *(reversed by the
uniform-persistence policy — see `command-persistence.md` CP1/CP3; canonical tests now live
in `test_command_persistence.py`.)* Given an active conversation, `set_model(m)` → the
appended notice carries the active `conversation_id` and `repo.load(conversation_id)`
contains a node matching the notice's content, so it reappears on resume.

**C16. set_model persists the real conversation (prior real nodes survive).** Given an
active conversation with ≥1 real user node, then `set_model(m)` →
`repo.load(conversation_id)` still returns the prior real user node(s). *(adjudicated C:
set_model always calls persist; with no active conversation that persist is a no-op
(C44) — set_model does not force-create a conversation.)*

### check_connectivity(model) — async

**C17. Success appends and returns a success notice.** Given a provider whose
`check_connectivity` returns `(True, "ok")` → `await check_connectivity(m)` returns a
system-notice node that `is nodes[-1]`, whose content reads as success (distinguishable
from the failure case).

**C18. Failure appends and returns a warning notice mentioning the error.** Given a fake
provider whose `check_connectivity` returns `(False, "<err>")` → the returned node
`is nodes[-1]`, is a system notice, and its content contains `"<err>"` as a substring and
reads as a warning (distinguishable from success).

**C19. The connectivity notice persists within an active conversation.** *(reversed by the
uniform-persistence policy — see `command-persistence.md` CP4; canonical test now lives in
`test_command_persistence.py`.)* The returned notice carries the active `conversation_id`
and a reload of the active conversation contains it.

### new_conversation()

**C20. new_conversation persists the current conversation before resetting.** Given a core
with an active conversation containing a real user node, then `new_conversation()` → the
previously active conversation is still reloadable: `repo.load(old_id)` returns the prior
real user node(s).

**C21. new_conversation resets state to defaults.** Given a core with active id, derived
title, non-default model, non-empty nodes → after `new_conversation()`, `nodes == []`,
`conversation_id == ""`, `conversation_title == ""`, and `model == DEFAULT_MODEL`.

**C22. new_conversation returns a transient notice that is not persisted.** The return
value is a system-notice node with `conversation_id == ""`; after the reset, `nodes` is
empty and the notice exists only as the returned value (for display).

### resume_conversation(conv_id)

**C23. resume of a found conversation adopts its id.** Given a conversation saved under id
K, and a fresh core → `resume_conversation(K)` makes `core.conversation_id == K`.

**C24. resume re-derives the title from the first user message among loaded nodes.** Given
a saved conversation whose first user message had text U → after resume,
`conversation_title` equals the title derived from U under the C3–C5 rule (equals U when
short/newline-free; equals `U[:MAX_TITLE_LENGTH]` when over-long).

**C25. resume replaces in-memory nodes with the loaded nodes and returns them.** Given a
saved conversation with known node contents, and a fresh core → `resume_conversation(K)`
returns a non-empty list equal in length/order/content to storage's nodes for K, and
afterward `core.nodes` is that same list.

**C26. resume of an unknown id returns `[]` (nothing resumed).** Given a never-saved id →
`resume_conversation(unknown)` returns `[]`.

**C27. resume of an unknown id does NOT destroy current in-memory state. — CONTRACT
VIOLATION (BUG-3), test quarantined `xfail(strict=True)`.** *(adjudicated A: "nothing
resumed" means the in-progress conversation is left fully intact — resuming a non-existent
conversation must not silently wipe the user's current work.)* Given a core mid-conversation
(active id `Kcur`, non-empty `nodes`, derived title), then `resume_conversation(unknown)` →
`conversation_id`, `conversation_title`, and `nodes` are all unchanged from before the
call. The current implementation assigns `self.nodes = storage.load(unknown)` (which is
`[]`) before the early return, so `nodes` is wiped to `[]` while `conversation_id`/`title`
keep their old values — a half-destroyed state. The test asserts the intended behavior and
is quarantined `xfail(strict)` — see `tests/specs/FOUND-BUGS.md` (BUG-3).

### include_files(paths)

**C28. include_files ensures a conversation exists when none is active.** Given a fresh
core (`conversation_id == ""`) → after `include_files(["docs/spec.md"])`, `conversation_id`
is non-empty.

**C29. include_files appends one `context` node per path, in order.** Given
`paths = ["docs/a.md", "src/b.py", "notes/c.txt"]` → the count of newly appended nodes
equals `len(paths)`; each has `node_type == "context"`; their order matches `paths`.

**C30. each context node carries its path under `meta["source_path"]`.** For the i-th
appended context node, `node.meta["source_path"] == paths[i]`.

**C31. include_files returns exactly the newly-appended context nodes, in order.** The
return value is a list of length `len(paths)`; each returned node is a context node with
`meta["source_path"] == paths[i]`; the returned nodes are the last `len(paths)` entries of
`core.nodes`, in the same order.

**C32. include_files persists the conversation (context nodes are reloadable).** Given a
fresh core → after `include_files(["docs/spec.md"])`, `repo.load(conversation_id)` returns
≥1 node with `node_type == "context"` and `meta["source_path"] == "docs/spec.md"`.

### add_system_message(content)

**C33. add_system_message appends and returns a system notice with the given content.**
`add_system_message("…")` returns a node whose `content` equals the supplied text, is a
system notice (`role == "system"`, `node_type == "system"`), and `is nodes[-1]`.

**C34. add_system_message persists within an active conversation.** *(reversed by the
uniform-persistence policy — see `command-persistence.md` CP5; canonical test now lives in
`test_command_persistence.py`.)* Given an active conversation, `add_system_message("note")`
→ the appended notice carries the active `conversation_id` and `repo.load(conversation_id)`
contains it.

**C35. the add_system_message notice is transient when no conversation is active
(`conversation_id == ""`).** Raised before any conversation exists, the notice carries an
empty `conversation_id` and is not persisted (storage skips id-less nodes).

### stream(assistant_node) — async generator

**C36. stream yields exactly the provider's token sequence, in order.** Given
`test_provider(["Hello", ", ", "world"])` and a submitted assistant node → collecting the
generator yields `["Hello", ", ", "world"]`.

**C37. stream accumulates tokens into `assistant_node.content`.** After full consumption,
`assistant_node.content == "Hello, world"` (in-order concatenation of all yielded tokens).

**C38. stream assembles context from the PRIOR nodes only (excludes the empty assistant
node).** Given a submit producing `(user_node, assistant_node)` and a capturing provider →
the `messages` handed to the provider include the prior user message and do NOT include the
empty assistant node being streamed into; system notices do not appear; context nodes are
expanded via the workspace loader. *(adjudicated D: observed via a fake provider capturing
its `messages` argument.)*

**C39. stream persists on success (full reply reloadable).** Given a core after submit and
`test_provider(["The ", "answer ", "is ", "42"])`, fully consumed →
`repo.load(conversation_id)` returns an `assistant` node with `content == "The answer is 42"`.

**C40. stream persists on cancellation and re-raises, saving partial content.** Given a
provider that yields one token then blocks awaiting the next; the stream is consumed
inside an `asyncio` task that is cancelled while suspended awaiting the next token (the
realistic mid-stream cancel) → the task raises `CancelledError`, AND
`repo.load(conversation_id)` returns an assistant node whose `content` equals the tokens
streamed before cancellation. *(adjudicated I: see the cancellation-simulation note —
cancellation must be delivered at the generator's await point so `stream`'s
`except CancelledError` actually runs and persists synchronously.)*

**C41. stream persists on provider error and re-raises, saving partial content.** Given a
fake provider whose stream yields some tokens then raises `RuntimeError` → the
`RuntimeError` propagates to the caller, AND `repo.load(conversation_id)` returns an
assistant node whose `content` equals the tokens yielded before the error.

**C42. stream persists exactly once per turn, regardless of outcome.** Using a
save-counting spy wrapping `repo`: across success, cancellation, and error, the spy's
`save` count for the turn is exactly 1 (no double-write, no missing write). *(adjudicated
F: exact-once is only directly falsifiable with a save-counting collaborator; tests wrap
the StoragePort.)* The cancellation case uses the same realistic task-cancel simulation as
C40 (adjudication I).

### persist()

**C43. persist with an active conversation writes the current state.** Given a core with
active `conversation_id` and in-memory changes not yet saved → after `persist()`,
`repo.load(conversation_id)` reflects the current real nodes.

**C44. persist with no active conversation is a no-op.** Given a fresh core
(`conversation_id == ""`) → `persist()` raises nothing, writes nothing retrievable, and
`conversation_id` stays `""`. (This is why set_model/new_conversation can call persist
safely before any real conversation exists.)

### Cross-cutting invariant: system notices are never persisted; context nodes are

**C45. The persistence filter is keyed on `conversation_id`, not "system-ness".** *(updated
under the uniform-persistence policy — breadcrumbs raised inside a conversation now persist,
see `command-persistence.md`.)* Given a breadcrumb raised with NO active conversation (so it
is id-less), then a real `submit(...)` that establishes the conversation and persists →
`repo.load(conversation_id)` returns the real turn but NOT the id-less breadcrumb.

**C46. Context nodes DO persist (the filter is keyed on `conversation_id`, not
"system-ness").** Given an active conversation; `include_files(["docs/spec.md"])`; reload →
the context node (with its `meta["source_path"]`) IS returned, contrasting with C45.

## Adjudication notes
- **A (resume unknown id):** resolved "preserve current state" — an unknown-id resume must
  leave `nodes`/`id`/`title`/`model` intact. Current code wipes `nodes` → C27 is BUG-3,
  quarantined `xfail(strict)`.
- **B (title rule):** truncation is by characters from the front (`text[:MAX_TITLE_LENGTH]`);
  newline→space flattening also applies. The two are tested on separate inputs so no test
  depends on the order of application.
- **C (set_model persist):** set_model always calls persist; with no active conversation
  that persist is a no-op (C44). set_model does not force-create a conversation.
- **D (stream context):** observed with a capturing fake provider; prior user/assistant
  nodes appear, the streaming assistant node does not, system notices are dropped, context
  nodes are expanded.
- **E (notice wording):** not part of the oracle — assert role/`node_type`/substring/
  `conversation_id`, never exact text.
- **F (exactly-once persist):** asserted with a save-counting spy wrapping the StoragePort.
- **G (submit persist timing):** submit persists the user turn before appending the empty
  assistant node; "the empty assistant node is not persisted by submit" is an internal
  sequencing detail and is not pinned (C9 only requires the user turn to be reloadable).
- **H (assistant node identity):** the empty assistant node is a real conversation node
  carrying the conversation_id (C7), not a transient notice.
- **I (cancellation simulation, C40/C42):** an earlier draft injected the cancel with
  `agen.athrow(asyncio.CancelledError())` after manually pulling a token. That is a valid
  probe in the plain build, but its *persist-completion timing* is non-deterministic under
  mutmut's async-generator trampoline instrumentation: `athrow` returned the
  `CancelledError` to the caller before the generator's `except CancelledError: persist()`
  finished, so the partial save landed only during generator finalization/GC — after the
  test reloaded. (Confirmed: the plain build persists synchronously and passes; only the
  instrumented build defers, which would wedge the mutmut baseline.) This is NOT a
  production bug — real mid-stream cancellation delivers the `CancelledError` at the
  generator's await point, where `stream`'s `except` runs synchronously. The tests
  therefore model the realistic case: a provider that yields a token then blocks awaiting
  the next, consumed inside an `asyncio` task that is cancelled while suspended on the next
  `anext`; `await task` then deterministically completes the generator's cancel handling
  (and thus the persist) before the assertion, in both the plain and instrumented builds.

## Contract violations found (quarantined `xfail(strict=True)`, logged in FOUND-BUGS.md)
- **BUG-3 (C27):** `resume_conversation(unknown_id)` assigns `self.nodes = storage.load(id)`
  (`== []`) before its early return, wiping the current in-memory `nodes` while leaving
  `conversation_id`/`conversation_title` set — a half-destroyed state. Intent (adjudicated)
  requires an unknown-id resume to leave the in-progress conversation fully intact.
Production code is untouched; deferred to a separate, human-reviewed fix. `strict=True`
means the test XPASSes (fails) once the code is fixed, forcing removal of the marker.

## Strengthening items added after the mutation gate (kill weak-test survivors)
These pin observable behavior that the first-pass tests left unpinned (each killed
specific surviving mutants; ids in brackets).

**C47. A freshly constructed core starts in the empty/default state.** A brand-new
`ConversationCore` (before any call) has `conversation_id == ""`, `conversation_title == ""`,
`model == DEFAULT_MODEL`, and `nodes == []`. [kills `__init__` 7, 9]

**C48. A new-conversation notice carries non-empty, human-readable content.** The node
returned by `new_conversation()` has a non-empty string `content` (a notice is shown to
the user — exact wording is not pinned, but it is not empty/None). [kills `new_conversation`
8, 11]

**C49. The connectivity success notice names the model.** On success, the notice's
`content` contains the model string as a substring (it reports *what* it connected to).
[kills `check_connectivity` 8]

**C50. resume re-derives the title with newline flattening.** Resuming a conversation
whose first user message contained newline characters → the re-derived `conversation_title`
has its newlines flattened to spaces (same rule as C4). [kills `resume_conversation` 14, 15]

**C51. resume of a conversation with no user message falls back to an empty title.** A
conversation persisted with nodes but no `user` node (e.g. a context-only conversation
created via `include_files` then persisted) → `resume_conversation(id)` adopts the id,
returns those nodes, and sets `conversation_title == ""` (no crash from a missing user
message). [kills `resume_conversation` 7, 9, 19]

**C52. include_files on a fresh core leaves the title empty.** After `include_files(paths)`
on a fresh core with no prior user message, `conversation_title == ""` (a file inclusion
does not invent a title from a sentinel). [kills `include_files` 2]

**C53. Context nodes carry role `"context"`.** Each node appended by `include_files` has
`role == "context"` (in addition to `node_type == "context"`). [kills `include_files`
10, 15, 16]

**C54. stream expands an included file into the model context.** Given a prior context
node whose `source_path` names a file present in the workspace (written under
`workspace.context_dir`), the messages handed to the provider during `stream` contain that
file's content — i.e. the workspace file loader is actually exercised. [kills `stream` 3]

**C55. stream feeds the FULL prior multi-turn history (still excluding the streaming
assistant).** With ≥2 prior turns persisted, the messages handed to the provider on the
next `stream` include both the first and the later user turns (not just the first node),
and never the empty assistant node being streamed into. [kills `stream` 6; strengthens C38]

**C56. stream uses the current model.** The model the core hands to `provider.stream` is
the core's current `model`. [kills `stream` 9]

**C57. include_files with an empty path list appends nothing and returns an empty list.**
*(Including zero files is a content no-op — there are no paths to import, so no `context`
node is created.)* Given a fresh core → `include_files([])` returns `[]`, and afterward
`self.nodes` contains no `context` node added by the call (the node count is unchanged from
before the call). *(Whether an empty include materializes a `conversation_id` is left
unspecified — adjudication note: the firm oracle is "no context node, returns `[]`"; the
zero-node-conversation question is governed by storage C18 and not re-litigated here.)*

## Mutation testing (mutmut)
Gate run scoped with `scripts/mutate.sh run 'ctx.core.conversation.*' 'ctx.core.provider.*'`.

**provider.py** — `TestProvider` mutants are all killed. Every surviving provider mutant is
in `LiteLLMProvider` with status **"no tests"**: the network adapter is out of scope for
unit tests by design (it does real I/O), exactly like `ctx/ui/*`. These are expected,
documented non-targets — not weak tests.

**conversation.py** — after the ADR-0016 graph additions (C67–C80): **184 mutants, ~165
killed, 19 non-killed — all documented-equivalent or pre-existing**, no surviving weak tests.
The graph code (`current_view`/`nodes`/`_append_to_line`/`_all_nodes`/`rewind`/`submit`/
`persist`/`resume_conversation`) is fully pinned; the initial triage surfaced two killable
weak tests in new code that were then killed by adding contract items:
- `__init__` seeding `_active_leaf_id=""` instead of `None` (would make a `submit`-created
  ROOT node's `prev_id` `""`) → **killed by C79** (root `prev_id is None`, survives reload).
- `resume_conversation` turning the `None`-or-not-in-graph fallback `or` into `and` (would
  leave a dangling stored tip in place and project an empty view) → **killed by C80**
  (dangling tip falls back to the last stored node).

Remaining non-killed mutants (all equivalent or pre-existing, none behavioral):
- **New graph code — documented-equivalent (2):**
  - `current_view` (`seen.add(cur)`→`seen.add(None)`): the `seen` set is a defensive
    cycle-guard. For any acyclic chain — every state reachable through the public API or a
    well-formed storage round-trip — it is never consulted meaningfully, so behavior is
    identical. It is distinguishable ONLY by a *cyclic* `prev_id` graph, which no code path or
    well-formed load can produce and which the mutant would only reveal by hanging (not cleanly
    assertable). Equivalent w.r.t. every terminating, API-reachable state.
  - `rewind` (`ValueError(f"…{target_id}")`→`ValueError(None)`): only the error *message* text
    changes; the contract pins "raises `ValueError`", and message wording is explicitly not the
    oracle (adjudication E). C73/C74 assert the raise, not the text. Equivalent.
- **Pre-existing (S1 calibration + wording), not introduced by this session:**
  - `_calibrate` boundary mutants (`<=`↔`<`, `<=0`→`<=1`, `or`→`and`, tolerance `1/TOL`→`2/TOL`,
    `<`/`<=` at the tolerance edges): the calibration tests deliberately use clearly-inside /
    clearly-outside values only and do NOT probe the exact tolerance/zero boundary (calibration
    ambiguity A1), so boundary flips are not distinguished. The clearly-behavioral `_calibrate`
    mutants (adopt-vs-reject a sane/zero/out-of-range usage) ARE killed by C58/C61/C62.
  - `stream` (`count_messages(messages, None)`): the local token estimate for the gauge; with a
    default tokenizer the sum stays positive and the ratio invariant (C59) cancels `local_sum`,
    so calibration is unchanged. Equivalent w.r.t. the calibration contract.
  - `check_connectivity` (provider called with `None` instead of `model`): notice text is built
    from the method parameter and the provider double ignores its argument — no observable diff.
  - `new_conversation` content case/wrapper variants: pure wording — not part of the oracle
    (adjudication E); C48 pins only non-empty content.

## Calibration

The header context-window gauge scales a provider-agnostic LOCAL token estimate
onto the provider's own tokenizer using a calibration factor derived from the
provider's exact `prompt_tokens` for a turn. `ConversationCore.stream` measures
the local sum of the context it sends and passes the provider an `on_usage`
callback; a reported `Usage` is trusted only after a sanity check. The two
observable surfaces are `core.calibration` (a `float | None`) and
`core.last_usage` (a `Usage | None`). Local token counts are tokenizer- and
model-dependent and MUST NOT be hardcoded in tests; the contract pins the formula
indirectly via a ratio invariant (see C59).

C58. Sane usage produces a positive calibration and stores the exact Usage.
  Setup:  Construct `ConversationCore(repo, test_provider(tokens, usage=Usage(...)), workspace)`
          where the `Usage.prompt_tokens` is positive and plausibly close to the
          local token count of a short submitted message (e.g. prompt_tokens ~ 12
          for a few-word context, comfortably within CALIBRATION_TOLERANCE× of the
          local sum). `setup()`, `submit("...")`, then fully consume `stream(assistant)`.
  Expect: `core.calibration` is a finite positive `float` (> 0); `core.last_usage`
          is exactly the `Usage` instance/value that was fed (equal by value, same
          prompt/completion/total token fields).
  Rationale: Intent: when a provider reports sane exact usage, calibration is set
          to `prompt_tokens / local_sum` (a positive float since both are positive)
          and `last_usage` records that turn's reported `Usage`.

C59. Calibration formula is prompt_tokens / local_sum (ratio invariant).
  Setup:  Build TWO independent cores constructed identically (same `repo`-style
          storage state path is per-test, same `workspace`, SAME `tokens` list,
          SAME submitted message text) differing ONLY in the canned
          `Usage.prompt_tokens`: core_a uses prompt_tokens = pa (e.g. 12), core_b
          uses prompt_tokens = pb (e.g. 24). Both values are clearly sane (close to
          the small local sum of a short message, within tolerance). Submit the
          SAME message to each, fully consume each stream.
  Expect: Because the context measured is identical for both turns, `local_sum` is
          identical, so calibration is linear in prompt_tokens:
          `core_a.calibration / core_b.calibration == pa / pb` within a small
          epsilon (e.g. 1e-6 relative). Both calibrations are positive floats.
  Rationale: Pins the formula as `prompt_tokens / local_sum` without depending on
          the exact tokenizer count: dividing the two calibrations cancels the
          shared `local_sum`, leaving the ratio of the prompt_tokens. Uses two
          separate cores so each turn measures the same context (a second submit on
          one core would grow the context and change local_sum).

C60. No reported usage leaves calibration and last_usage at None.
  Setup:  `test_provider(tokens)` with NO `usage` argument (provider never fires
          `on_usage`). Fresh core, `setup()`, `submit(...)`, fully consume stream.
  Expect: `core.calibration is None` and `core.last_usage is None`.
  Rationale: Intent: a provider that reports no usage leaves both values unchanged;
          from the fresh (None) baseline they remain None.

C61. Usage with prompt_tokens == 0 is rejected.
  Setup:  `test_provider(tokens, usage=Usage(prompt_tokens=0, completion_tokens=k,
          total_tokens=k))`. Fresh core, `setup()`, `submit(...)`, consume stream.
  Expect: `core.calibration is None` and `core.last_usage is None`.
  Rationale: Sanity check requires `prompt_tokens > 0`; a zero count is bogus and
          rejected, leaving the prior (None) values unchanged.

C62. Usage with prompt_tokens wildly out of range is rejected.
  Setup:  `test_provider(tokens, usage=Usage(prompt_tokens=10_000_000, ...))` for a
          tiny short-message context whose local sum is on the order of ~10-30
          tokens (so 10_000_000 is far beyond CALIBRATION_TOLERANCE× the local sum).
          Fresh core, `setup()`, `submit("a few words")`, consume stream.
  Expect: `core.calibration is None` and `core.last_usage is None`.
  Rationale: Sanity check rejects a `prompt_tokens` whose ratio to local_sum exceeds
          CALIBRATION_TOLERANCE; a mismatched/buggy provider count must not corrupt
          the gauge, so prior (None) values are left unchanged.

C63. Fresh core has no calibration and no usage.
  Setup:  Construct a `ConversationCore`; do NOT stream any turn (optionally call
          `setup()`). No `submit`/`stream` performed.
  Expect: `core.calibration is None` and `core.last_usage is None`.
  Rationale: Intent: before any streamed turn both values are None (no turn has
          produced a trusted usage yet).

C64. A trusted calibration SURVIVES a later no-usage turn (left unchanged, not reset).
  Setup:  One core. Turn 1: provider returns SANE usage -> calibration/last_usage
          get set. Turn 2 on the SAME core: a fresh provider reporting NO usage
          (the test swaps in a no-usage provider for the second turn, or the core is
          driven through a second turn whose provider never fires on_usage). Fully
          consume each stream.
  Expect: After turn 2, `core.calibration` still equals the positive float set by
          turn 1 (unchanged), and `core.last_usage` still equals turn 1's fed `Usage`.
  Rationale: Intent: a turn with no usage "leaves the previous value unchanged" — a
          previously-set value must persist. Guards against a mutation that resets to
          None on every turn.

C65. A trusted calibration SURVIVES a later bogus-usage turn (left unchanged, not reset).
  Setup:  One core. Turn 1: SANE usage sets calibration/last_usage. Turn 2 on the
          SAME core: provider reports BOGUS usage (e.g. prompt_tokens == 0 or wildly
          out of range) that fails the sanity check. Fully consume each stream.
  Expect: After turn 2, `core.calibration` still equals turn 1's positive float, and
          `core.last_usage` still equals turn 1's fed `Usage` (both unchanged).
  Rationale: Intent: rejected usage "leaves the previous value unchanged" — a bogus
          later turn must not corrupt or reset an already-trusted calibration.

### Intent ambiguities assumed past (flag for human)
- A1. Exact boundary behavior of CALIBRATION_TOLERANCE (inclusive vs exclusive at
  exactly ratio == 10.0 or == 1/10.0) is deliberately NOT tested; per instructions we
  use clearly-inside / clearly-outside values only.
- A2. C64/C65 "same core, second turn" assumes the provider used by a core can be
  changed between turns OR that a second turn can be driven with a different provider.
  If `ConversationCore` binds one provider for its lifetime, the test must instead use
  a single provider configured to fire sane usage on turn 1 and nothing/bogus on turn
  2. The TestProvider factory as described yields a fixed `usage` per construction; if
  per-turn variation is unsupported by the fixture, this needs a small fixture
  enhancement or a provider that varies its on_usage by call count. Flagged.
- A3. "Local sum is the same for the same context" (C59) assumes `stream` measures
  exactly the context built from existing nodes excluding the streamed assistant node,
  and that two identically-constructed cores given the same submitted text build
  identical contexts. If construction injects any nondeterministic/per-instance context
  (e.g. timestamps in the prompt), the ratio invariant could drift; assumed not the case.

## Append-only conversation graph (ADR-0016)

`ConversationCore`'s in-memory state is now the whole append-only node graph, not a flat list.
`current_view()` projects the active line (walk `prev_id` from the tip to the root, reversed →
root-first), and the read-only `nodes` property returns it. `rewind(target_id)` moves the tip back
to an earlier on-line node (inclusive) without deleting the abandoned tail; `submit` after a rewind
diverges (a new sibling off the rewind point). All Expect clauses observe `current_view()`/`nodes`
by id/role/content/order, `rewind`'s return / raised `ValueError`, and what `repo.load(cid)` returns
after a reload — never the private graph structure. Tests compare projected nodes by `.id` (+ role/
content) to avoid coupling to object identity.

**C67. `current_view()` is empty for a fresh conversation.**
Given a fresh core (`setup()` called, nothing submitted) → `current_view() == []` and `nodes == []`.

**C68. `current_view()` is root-first and matches append order on a linear conversation.**
Given a fresh core; submit turn 1 `(u1,a1)`, then submit turn 2 `(u2,a2)` → `current_view()` is
exactly `[u1, a1, u2, a2]` by id/role/content/order — first element is the root `u1`, last is the tip
`a2`.

**C69. `nodes` equals `current_view()` and is recomputed on each access.**
Given a fresh core; submit turn 1 `(u1,a1)` → `nodes == current_view()`. After a further submit turn 2
`(u2,a2)`, a fresh read of `nodes` equals the new longer `current_view()` (`[u1,a1,u2,a2]`) — the
earlier read did not freeze a stale list.

**C70. `rewind` shortens the view to the prefix ending inclusively at the target.**
Given three submitted turns `(u1,a1),(u2,a2),(u3,a3)`, then `rewind(a1.id)` → `current_view() == [u1, a1]`
(by id/role/content/order); its last element is the target `a1`; `u2,a2,u3,a3` no longer appear.

**C71. `rewind` returns the shortened active line.**
Given three turns then `r = rewind(a1.id)` → `r` equals `current_view()` taken immediately after (same
ids/roles/content/order == `[u1, a1]`).

**C72. `rewind` to the current tip leaves the view unchanged.**
Given two turns `(u1,a1),(u2,a2)` (tip `a2`); capture `view_before = current_view()`; then `rewind(a2.id)`
→ `current_view() == view_before` (`[u1,a1,u2,a2]`, same ids/order); nothing dropped.

**C73. `rewind` raises `ValueError` for an id that exists nowhere; state unchanged.**
Given two turns; capture `view_before` → `rewind("nonexistent-node-id")` raises `ValueError`, and
afterward `current_view() == view_before` (unchanged).

**C74. `rewind` raises `ValueError` for an id on an abandoned tail; state unchanged.**
Given three turns; `rewind(a1.id)` (so `u2,a2,u3,a3` become an abandoned tail); submit a divergent turn
`(u4,a4)`; capture `view_before` → `rewind(u3.id)` raises `ValueError` (`u3` is on the abandoned tail,
not reachable from the current tip), and afterward `current_view() == view_before` (unchanged).

**C75. `rewind` survives save/reload — the stored tip is the rewind target.**
Given three turns then `rewind(a1.id)` (which persists), `cid = core.conversation_id`; then a NEW core
`resume_conversation(cid)` → the fresh core's `current_view()` equals `[u1, a1]` by id/role/content/order
— the reloaded tip is the rewind target `a1`, NOT the last-created node `a3`.

**C76. Append-only: the abandoned tail survives in full storage after divergence + reload.**
Given three turns; `rewind(a1.id)`; submit a divergent turn `(u4,a4)`; `cid = core.conversation_id`; then a
NEW core `resume_conversation(cid)` → `repo.load(cid)` (the FULL node set) still contains nodes with ids
`u2.id, a2.id, u3.id, a3.id` (the abandoned tail) with matching content — preserved, not deleted — and
their `prev_id` edges are intact (e.g. `u2.prev_id == a1.id` chains the tail back to the rewind point).
The fresh core's `current_view()` contains none of `u2,a2,u3,a3` (it followed the divergence to `…u4,a4`).
This pins the destructive-rewind failure mode.

**C77. Append-only: `current_view()` after divergence is the new branch only.**
Given the same sequence as C76 (three turns, `rewind(a1.id)`, divergent turn `(u4,a4)`), same core (no
reload) → `current_view() == [u1, a1, u4, a4]` by id/role/content/order — root `u1`, then `a1` (the rewind
point), then the new divergent turn; none of `u2,a2,u3,a3` present.

**C78. Migrated-linear equivalence: the projection matches storage's rowid order end-to-end.** *(adjudicated:
strengthened to exercise a GENUINELY migrated pre-graph DB, per the stated intent — not merely a normally
created linear conversation.)* Given a pre-graph flat DB (built directly via `sqlite3`: a linear conversation
of several nodes, `conversations` without `active_leaf_id`, `nodes` without `prev_id`/`compressed_into`),
pointed at by a core whose `setup()` runs `init()` (migrating it); then `resume_conversation(cid)` →
`[n.id for n in core.current_view()] == [n.id for n in repo.load(cid)]` (same ids in the same order). For a
degenerate single-path (migrated) conversation, walking `prev_id` from tip to root then reversing reproduces
storage's insertion (rowid) order exactly — no reordering, no dropped nodes.

**C79. The root node's predecessor edge is `None` ("NULL = root").** *(added after the mutation gate:
pins the root-is-None invariant for a `submit`-created node — kills the `__init__` mutant that seeds
the initial tip as `""` instead of `None`.)* Given a fresh core; `u1, a1 = submit("first turn")` →
`u1.prev_id is None` (the first node on the line has no predecessor), and after persistence
`repo.load(conversation_id)[0].prev_id is None` (the root edge survives the round-trip as NULL, not an
empty string).

**C80. Resume with a stale/dangling stored tip falls back to the last stored node.** *(added after the
mutation gate: pins the documented "falling back to the last loaded node if absent/dangling" behavior —
kills the `resume_conversation` mutant that turns the `None`-or-not-in-graph fallback condition into
`and`.)* Given nodes `n1→n2→n3` saved directly with `active_leaf_id` set to an id that is NOT among the
stored nodes (a dangling tip) → after `resume_conversation(cid)` into a fresh core, `current_view()` ids
== `[n1.id, n2.id, n3.id]` — the projection falls back to the last stored node as the tip and yields the
full stored line, NOT an empty view.

### current_view() compression folding (ADR-0016 Q1 / A#2 / H3)

**Mechanism (task 15, revised):** folding is resolved by **event enumeration**, not by
following child `compressed_into` pointers. A compression `K` applies iff **no `E` node
targets it** (`E.meta["target"] == K.id`) **and** its whole stored range
(`K.meta["range"]`) lies on the current line. Every C82–C90 fixture therefore carries
`K.meta["range"]` = the ordered folded child ids (the source of truth); the
`compressed_into` pointers they also set are vestigial and never read at runtime (A#3 §3).
This is a **deliberate, recorded** change from the 3a pointer-run resolution — the
scenarios and expected views are unchanged (same observable behavior), only the fixtures'
range meta and the underlying mechanism moved.

**C81. No compression → identical to a plain prev_id walk.** Given a linear chain
a→b→c on the active line, no compression node in the graph, tip = c → `current_view()`
returns ids `[a, b, c]` in order, all `node_type` `"message"`. (Hard backward-compat:
folding must be a no-op when nothing is compressed.)

**C82. Folded tip → view ends with K.** Given chain a→b→c, tip = c, K
(`node_type "compression"`, `prev_id None`, `meta["range"] = [c]`) in the graph →
`current_view()` ids `[a, b, K]`, node_types `["message","message","compression"]`; the
view ends with K.

**C83. Append after a folded tip → [..., K, new].** Given chain a→b→c with K
(`range = [c]`) in the graph; a new message node `new` chained from the real leaf c
(`new.prev_id=c.id`) and made the tip → `current_view()` ids `[a, b, K, new]`; the
freshly appended real node follows K; K's own `prev_id` stays None.

**C84. Middle fold in place.** Given chain a→b→c→d→e, tip = e, K with
`range = [b, c, d]` in the graph → `current_view()` ids `[a, K, e]`, node_types
`["message","compression","message"]`; folded children absent, order preserved.

**C85. Two independent compressions → two K nodes.** Given chain a→b→c→d→e→f, tip = f;
K1 with `range = [b, c]`; K2 with `range = [e]`; d and f unfolded → `current_view()` ids
`[a, K1, d, K2, f]`; two distinct compression nodes appear, with an unfolded tail f
surviving after K2.

**C86. Single-node fold still collapses to K.** Given chain a→b→c, tip = c, K with
`range = [b]` (run length 1) → `current_view()` ids `[a, K, c]`.

**C87. Stale/dangling pointer at a missing K → treated as unfolded.** Given chain a→b→c,
tip = c, `b.compressed_into` = an id NOT present in the graph and no compression node →
`current_view()` ids `[a, b, c]`, all `node_type "message"`; b stays as itself
(enumeration finds no applying K).

**C88. Empty conversation → [].** Given an empty graph and `active_leaf_id None` →
`current_view() == []`.

**C89. Save → reload round-trip preserves folding.** Given chain a→b→c→d→e plus
compression node K (`range = [b, c, d]`), all persisted via `repo.save` with
`active_leaf_id=e`; core resumes the conversation → `current_view()` ids `[a, K, e]`;
folding is derived from persisted graph state (the range meta round-trips).

**C90. Root fold → view starts with K.** Given chain a→b→c, tip = c, K with
`range = [a, b]` → `current_view()` ids `[K, c]`, node_types `["compression","message"]`;
K can appear first despite `prev_id None`.

**C97. Stale `compressed_into` at a real K whose range excludes the node → not folded.**
Given chain a→b→c, tip = c, a compression K in the graph whose `range` points off this
line and `b.compressed_into = K.id` (a stale/wrong pointer) → `current_view()` ids
`[a, b, c]`; enumeration ignores the pointer and K does not apply (range ⊄ line). (This
would fold under the old pointer resolution — the discriminator.)

**C98. Range-only folds without any pointer.** Given chain a→b→c, tip = c, K with
`range = [b]` and `b.compressed_into` left None → `current_view()` ids `[a, K, c]`;
`K.meta["range"]` alone drives folding. (Would NOT fold under pointer resolution — the
reverse discriminator.)

**C99. Expand + re-compress an overlapping range.** Submit two turns, `commit_compression`
the whole tip → K, `expand_compression(K)`, then `commit_compression` the tail `[u2, a2]`
→ K′. `current_view()` contains K′ and **not** K (K's `E` deactivates it; it never
resurrects) while K remains present in `_graph` (append-only, never row-deleted).

_Intent ambiguities flagged by the code-blind author (assumed past):_ non-contiguous
runs sharing the same K each yield their own K occurrence (no de-dup); K takes the run's
slot; a K accidentally on-line (prev_id ≠ None) is a precondition violation, untested.

## Adjudication notes (ADR-0016 graph)
- **Node identity in `current_view()`:** tests compare projected nodes by `.id` (+ role/content), so they
  hold whether the projection returns the same `Node` objects or equal copies.
- **`submit` after `rewind` diverges with fresh ids:** the post-rewind submit appends onto the rewound tip
  (a genuine sibling off the rewind point) with new uuid ids distinct from the abandoned tail — so C76's
  tail-id survival check is unambiguous.
- **`get_active_leaf` authority (C75):** the persisted rewind target is authoritative on reload; the
  "last loaded node" fallback fires only when the stored tip is absent/dangling.
- **C79 (proposed) dropped:** unknown-id resume returning `[]` with current state intact is already
  covered by C26/C27; not re-derived here.

## Turn lifecycle — `end_turn` single door (ctx0 Phase 1)

### Superseded by the turn-lifecycle contract (ctx0 Phase 1)
C39–C42 specified `stream()` as the owner of end-of-turn persistence (full/partial
content saved by the generator's success/cancel/error paths, exactly once). That
ownership moved to `end_turn` (C102–C104, C107 below); the C39–C42 tests were
deleted with this supersession note rather than rewritten, because the new items
pin the same durable observables through the new single door. C1/C2 of
`conversation_streaming_flag.md` (flag cleared by the generator on build failure)
are superseded the same way: the flag is no longer the generator's to clear.


Code-blind contract for the single-owner turn lifecycle: `submit` refuses while a
turn is in flight; `end_turn(node, *, cancelled/error)` is the only place a turn's
ending is recorded (flag lowered, durable mark stamped, then persisted); `stream`
is pure token production (no flag writes, no persists). Tests live in
`tests/test_turn_lifecycle.py`.

**C100. `submit` raises the in-flight flag; only `end_turn` lowers it on the happy
path.** With no turn in flight, `submit(text)` returns `(user_node, assistant_node)`
and `streaming` is True — and stays True until `end_turn` (see C106).

**C101. Second `submit` mid-turn is refused, not queued — side-effect free.** With a
turn in flight, `submit(...)` raises `ValueError`; `streaming` stays True, no new
nodes are appended (a storage reload shows exactly the pre-refusal nodes), and the
live turn can still be ended normally via `end_turn`.

**C102. Clean finish: `end_turn(node)` lowers the flag and persists the full streamed
content, unmarked.** After fully draining a scripted stream, `end_turn(assistant_node)`
→ `streaming` False; the reloaded assistant node carries the full concatenated content
and neither `"interrupted"` nor `"error"` in `meta`.

**C103. Cancel ending: `interrupted` mark and partial content are durable together.**
After a partial stream (blocking provider, some tokens in), `end_turn(node,
cancelled=True)` → `streaming` False; the RELOADED node has `meta["interrupted"] is
True` and the partial content. Asserting on the reloaded copy pins mark-then-persist
ordering. (Zero-token cancels mark identically; dropping the empty node from the view
is a UI decision, out of core scope.)

**C104. Error ending: the error message is durable on the node.** After a failed
stream, `end_turn(node, error="boom")` → `streaming` False; the reloaded node has
`meta["error"] == "boom"`.

**C105. `cancelled` + `error` together raise `ValueError` with no effect at all.**
On a live turn, `end_turn(node, cancelled=True, error="boom")` raises `ValueError`;
`streaming` is still True (validation precedes any effect, mirroring the compression
guards) and the reloaded node carries neither mark.

**C106. `stream` never touches the flag: a full drain leaves the turn in flight.**
Draining `stream()` to exhaustion without calling `end_turn` leaves `streaming` True.
(The invariant that retires the cancelled-before-first-tick stuck-flag bug.)

**C107. `stream` never persists: drained content is invisible in storage until
`end_turn`.** Same drained-but-unended turn: the reload contains the user node with
its text (persisted at `submit`) and does NOT contain the assistant node at all —
`submit` persists with the tip at the user node, so a crash mid-stream resumes
cleanly on the user turn.

**C108. `end_turn` is safe when the flag is already down.** Calling `end_turn(node)`
again after a clean ending: no exception, `streaming` stays False. (Whether a late
second ending could re-stamp is deliberately unconstrained: `end_turn` has a single
caller by design and tracking turn identity would be mechanism nothing needs.)

**C109. Conversation switch mid-turn resets the flag.** With a turn in flight,
`new_conversation()` — or `resume_conversation(<other id>)` — leaves `streaming`
False immediately, before any `end_turn` arrives.

**C110. Stale ending after `new_conversation`: no stamp anywhere, no persist
anywhere.** Turn in flight on conversation A → `new_conversation()` creates B →
late `end_turn(old_node, cancelled=True)`: no exception; `streaming` stays False;
B's stored state is unchanged; no stored node of A carries `"interrupted"`.

**C111. Stale ending after `resume_conversation`: same no-op, error variant.** Turn
in flight on A → resume previously-persisted B → late `end_turn(old_node,
error="provider timed out")`: no exception; B's stored state unchanged; no stored
node of A (nor B) carries `"error"`.

**C112. A cancel/error ending fully releases the single-turn slot.** After
`end_turn(node, cancelled=True)` (or `error=...`), a new `submit` on the same
conversation succeeds, appending the new user node after the marked assistant node.

### Adjudication notes (turn lifecycle)
- **Validation-before-effect (C105):** resolved to "a rejected call changes nothing,
  including the flag" — consistent with `_validate_compress_range`-style guards.
- **Assistant node not persisted at `submit` (C107):** settled design (task 33):
  `submit` persists with the tip at the user node; the assistant node first reaches
  storage via `end_turn`. The blind author's alternative reading was corrected.
- **Old-conversation observable in C110/C111** rephrased to "no stored node carries
  the mark" — on the resume path A's assistant node may legitimately be absent from
  storage (per C107), so the check must not presuppose its existence.
- **Retroactive re-stamp protection rejected (C108):** single-caller discipline (the
  UI's one convergence point) is the guard; turn-identity tracking would be
  speculative mechanism.
