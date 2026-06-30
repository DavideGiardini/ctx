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

**conversation.py** — 166 mutants killed; the authoritative `mutmut results` lists exactly
6 non-killed, all documented-equivalent below (no surviving weak tests, no timeouts). The
C47–C56 strengthening also converted six previously timing-out `stream` mutants
(`build_context(None,…)`, dropped args, `content -= token`) into clean assertion-kills: the
new file-loading (C54) and multi-turn (C55) stream tests exercise those lines without the
cancellation tests' readiness-wait, so the mutation surfaces as a fast assertion failure
instead of a hang. The remaining non-killed mutants are:
- **Documented-equivalent survivors (no observable behavior change):**
  - `submit` (assistant `content=""` dropped): `""` is the `Node.content` default, so the
    node is identical.
  - `check_connectivity` (provider called with `None` instead of `model`): the notice text
    is built from the method parameter `model`, and the provider double's result is
    independent of its argument, so there is no observable difference.
  - `new_conversation` content case/wrapper variants (`"started…"`, `"STARTED…"`,
    `"XX…XX"`): pure wording changes — notice wording is explicitly **not** part of the
    oracle (adjudication E); C48 pins only that the content is non-empty.
  - `include_files` (context node `content="Included: {path}"` dropped): the context node's
    `content` is vestigial — `build_context` replaces it via `meta["source_path"]`, so it is
    not behaviorally observable through the core's contract.

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
