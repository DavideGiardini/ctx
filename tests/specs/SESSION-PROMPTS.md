# Per-session kickoff prompts for `/write-tests`

Paste-ready prompts for the remaining framework-free test work, compressed into **four
sessions** (ordered leaves-first, the integrator `conversation` last). Each prompt
carries the **intent** — the code-independent description of what a module is *for* —
which is the part a human vets and the orchestrator hands to the code-blind
`test-spec-author`. The orchestrator still reads each module to extract exact
signatures; it must **not** paste bodies into the blind agent, and (per policy) **never
edits test code** — failures and gaps route back to the blind agent as intent questions.

`context.py` is already done — see `tests/specs/context.md` for the worked example.

**When a test finds a bug:** good — that's the method working. A failing test means code
and contract disagree; adjudicate from intent. If the *oracle* was wrong, the blind agent
corrects it. If the *code* is wrong, **do not fix it here** — mark the (correct) test
`@pytest.mark.xfail(strict=True)` with a reason, log it in `tests/specs/FOUND-BUGS.md`,
and move on. `xfail` keeps the suite green so mutmut still runs; fixing the code is a
separate, reviewed effort. Test sessions only ever add tests/specs.

**Running these in parallel:** the authoring (contract → tests → coverage → xfail/log →
ruff/mypy/pytest green) is fully parallel-safe. The **mutmut gate is not** — it has a
*global* precondition: mutmut runs the whole discovered suite for its baseline (with `-x`),
so it can only run once **every** module's tests are green/xfail-stable under mutmut (a
red test anywhere aborts the gate for everyone). And mutmut's tests run in a fixed order
from a copied dir, so a state-leaking test can pass `check.sh` yet fail the mutmut baseline
— tests must be order-independent. So: finish all the authoring in parallel, then run the
per-module gates (`scripts/mutate.sh run 'ctx.<dotted.module>.*'`) — **one mutmut at a
time** (shared `mutants/` dir, CPU-heavy), each session triaging its own survivors. Never
relocate/edit another session's test files to force isolation. `[tool.mutmut].only_mutate`
is the append-only union — add your module when its tests land, never narrow it.

## Why four sessions, not one per file
We test where **logic can break**, not once per file. Modules vary in logic density, so
effort is right-sized: the two heaviest (`storage`, `conversation`) get their own
session; the two smaller-logic modules (`config`, `workspace`) share one; `snapshot`
(a rich pure formatter) gets one.

## What we deliberately DON'T test (and why)
- **`ctx/models/nodes.py` (`Node`)** — a plain `@dataclass` with no logic, validation,
  or side effects. Established practice says don't test trivial data classes / getters
  / auto-generated record behavior, and coverage-for-its-own-sake ("the Dodger") is an
  anti-pattern. `Node` is protected **transitively**: `storage`'s round-trip test and
  the `context`/`conversation` tests all build and consume `Node`s, so a wrong default
  or shape breaks *those* immediately — that's where the real coverage lives.
- **`LiteLLMProvider`** — does real network I/O; out of scope for unit tests (belongs to
  integration / manual QA). Don't mock litellm internals just to hit a coverage number.
- **`ctx/ui/*`** — the Textual UI is the Pilot / `qa-tester` layer, not unit tests.

---

## Session 1 — `tools/agent/snapshot.py` :: `render(state) -> str`

```
/write-tests tools/agent/snapshot.py

Intent: render() turns the raw dict from ChatApp.describe_state() into a compact,
stable, diffable text block (~100 tokens) for an agent to read between actions. It is
a pure presentation function — all truncation/compaction lives here so the UI class
stays free of AI-presentation concerns. Stability matters: the structure is fixed so
snapshots diff cheaply, and noise lines are omitted when not meaningful.

Behaviors to cover:
- First line is always present: `mode=<mode> focus=<focus> streaming=<yes|no>
  model=<model>`. The streaming boolean renders as the literal "yes"/"no".
- Optional lines appear ONLY when meaningful: title (only if truthy); input (only if
  there is input text OR an open command menu); footer (only if present); detail (only
  if present); colors (only if present).
- Nodes header: `nodes=<count>`, plus ` selected=[<i>]` only when selected_index is set.
- Per node line: a `*` marker if selected (else space), a `~` marker if truncated
  (else space), then `[<index>] <role> <content>`; a `  (file: <source_path>)` suffix
  if the node has source_path; a `  w=<n>%` suffix if it has weight_pct.
- Content is collapsed to a single line (runs of whitespace → one space) and truncated
  to 80 chars, with a trailing "…" when it overflows. Test the boundary (exactly 80 vs
  81 chars).
- Empty nodes list → just the header lines, no node lines.

INTENT QUESTION to resolve: `mode` and `model` are read as required keys (a snapshot
always has them) while everything else is optional. Confirm that a state dict missing
mode/model is "never happens / may raise" rather than a case render() must tolerate.
```

---

## Session 2 — `ctx/core/config.py` + `ctx/core/workspace.py`

Two independent, smaller-logic modules grouped only because each is light — **prefer a
fresh conversation per module** (cleaner context and sharper attention for each; the
pipeline re-reads the skill + `conftest.py` each time, so starting clean is nearly free).
Running both in one conversation is fine but not recommended. Blindness is unaffected
either way — the blind subagents spawn fresh and never inherit the orchestrator's context.

### 2a. `config.py` :: `get_config()`

```
/write-tests ctx/core/config.py

Intent: get_config() returns the EFFECTIVE configuration = built-in defaults overlaid
with the user's overrides from ~/.config/ctx/config.json. It must never crash: a missing
or malformed config file falls back to defaults. Overrides are merged per-section, not
wholesale-replaced, so a user who sets one color keeps the other default colors.

TESTABILITY NOTE: get_config() reads a module-level CONFIG_PATH (~/.config/ctx/
config.json), so it is not injectable like the other core modules. Tests must isolate
it by monkeypatching `ctx.core.config.CONFIG_PATH` (and CONFIG_DIR) to a temp file via
pytest's monkeypatch/tmp_path. Flag for the user whether config should be refactored to
take an injected path (consistent with ADR-0004/0005); if so, that's a separate change.

Behaviors to cover:
- No config file present → returns the defaults.
- A config file with PARTIAL overrides merges per section: top-level keys are updated;
  `colors` is merged key-by-key over the default colors (unspecified colors keep their
  defaults); `ui` is merged, and `ui.truncation_lines` is merged key-by-key over the
  default truncation lines.
- A config file that is invalid JSON, or unreadable, → returns the defaults WITHOUT
  raising.
- The returned dict is a copy at the top level — mutating the result must not corrupt
  the next call's defaults.

INTENT QUESTION: the top-level copy is shallow; decide whether deep isolation of the
returned config is part of the contract or out of scope.
```

### 2b. `workspace.py` :: `Workspace`

```
/write-tests ctx/core/workspace.py

Intent: Workspace owns the `.ctx/` workspace layout and SAFE file access for context
imports. It removes the global Path.cwd() dependency by taking its root explicitly.
Use the `workspace` fixture from conftest.py (a temp-dir root with .ctx/ created), or
build Workspace(tmp_path) directly when you need the pre-ensure() state.

Behaviors to cover:
- The path properties locate things correctly relative to the root: workspace_path =
  <root>/.ctx, context_dir = <root>/.ctx/context, db_path = <root>/.ctx/conversations.db.
- ensure() creates .ctx/ and .ctx/context/ and is idempotent (no error if they exist);
  it returns the workspace path.
- list_files() returns the RELATIVE (posix) paths of text files under the context dir,
  sorted, searching recursively into subdirectories. It returns [] if the context dir
  doesn't exist. It SKIPS files that aren't valid UTF-8 (binary) and files it can't read.
- read_file(rel_path) returns a context file's text content.
- SECURITY (the key behavior): read_file raises ValueError if the resolved path escapes
  the context directory (e.g. a "../.." traversal); raises FileNotFoundError if the file
  doesn't exist.

Use real temp files (write a small text file and a bytes/binary file) so the UTF-8 skip
and the path-escape guard are exercised with realistic data.
```

---

## Session 3 — `ctx/core/storage.py` :: `ConversationRepository` (StoragePort)

```
/write-tests ctx/core/storage.py

Intent: ConversationRepository is durable persistence for conversations and their
nodes (SQLite), behind the small StoragePort interface (init/save/load/list/get_last).
Use the `repo` fixture from conftest.py (a temp-FILE SQLite DB, already initialized).

IMPORTANT: do NOT use ":memory:" — the repository opens a fresh connection per method,
and an in-memory DB is private to its connection, so init()/save()/load() would each
get a separate empty database. The `repo` fixture uses a temp-file path for this reason.

Behaviors to cover:
- init() creates the schema and is idempotent (safe to call repeatedly).
- save(conversation_id, title, nodes): creates the conversation if new, or updates its
  title (and updated_at) if it already exists. It REPLACES the conversation's nodes
  (saving again does not duplicate them).
- Nodes whose conversation_id is empty are NOT persisted (system notices are skipped).
- A round-trip preserves every persisted Node's fields: id, conversation_id, role,
  content, node_type, and meta (meta survives JSON serialization, including nested
  values). (This is also what transitively protects ctx/models/nodes.py.)
- load(conversation_id) returns the nodes in their original insertion order; returns
  [] for an unknown id.
- list() returns one dict {id, title, updated_at} per conversation, ordered most-
  recently-updated first.
- get_last() returns the most-recently-updated conversation's id, or None when empty.

INTENT QUESTIONS to resolve: (a) is "nodes returned in insertion order" a guaranteed
part of the contract? (b) Saving the same conversation with a changed title should
update it — confirm. These are behavior decisions, not "what the code does".
```

---

## Session 4 — `ctx/core/conversation.py` :: `ConversationCore` (the integrator — LAST)

This session also folds in the few `TestProvider` checks (it's used here anyway).

```
/write-tests ctx/core/conversation.py

FIRST, a small add-on (does not need its own session): TestProvider in
ctx/core/provider.py is the deterministic test double. Add ~3 tests for it in
tests/test_provider.py (or alongside): stream(messages, model) yields exactly the
tokens it was constructed with, IN ORDER; the output does NOT depend on messages/model;
an empty token list yields nothing; check_connectivity returns (True, "ok"). It is
async (asyncio_mode=auto). LiteLLMProvider is out of scope (network).

THEN the main module:

Intent: ConversationCore is the deep module that owns conversation STATE, command
handling, and the streaming lifecycle, coordinating storage, the LLM provider, and the
workspace through their protocols. Its contract references the behaviors of
storage/provider/workspace/build_context, which are now already specced.

Wire it from conftest fixtures: ConversationCore(repo, TestProvider([...]), workspace).
(repo = temp-file DB; provider = a TestProvider with canned tokens; workspace = temp dir.)

Behaviors to cover (derive precise oracles with the blind agent):
- setup() ensures the workspace and initializes storage.
- submit(text): on the FIRST message it starts a conversation — assigns an id and
  derives the title from that message (truncated to a max length, newlines flattened to
  spaces); appends a user node, persists, then appends an empty assistant node; returns
  (user_node, assistant_node).
- set_model(model): records the model and appends a "Model set to <model>" system
  notice; persists.
- new_conversation(): persists the current one, then resets nodes/id/title/model to
  empty/defaults; returns a system notice.
- resume_conversation(id): loads the conversation's nodes from storage; if there are
  none it returns [] (nothing resumed); otherwise it adopts the id and derives the title
  from the first user message.
- include_files(paths): ensures a conversation exists, appends one context node per path
  (carrying meta source_path), persists, and returns the new nodes.
- add_system_message(content): appends a system notice node (NOT persisted on its own).
- stream(assistant_node): assembles the model context from the prior nodes (using the
  workspace file loader), streams tokens from the provider into assistant_node.content,
  and persists on success, cancellation, AND error.

System notices (model-set, connectivity, new-conversation) carry no conversation_id and
therefore are not persisted by storage — keep that consistent with the storage contract.

stream() and check_connectivity() are async. INTENT QUESTIONS likely needed: exact title
length/derivation rule; persistence-on-cancel/error guarantees; what resume does to the
current in-memory state when the id is unknown.
```
