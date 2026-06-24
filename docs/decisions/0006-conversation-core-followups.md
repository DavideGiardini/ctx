# 0006 — ConversationCore observations

**Status:** Notes (no action required)

## Context

Two things we noticed while reading `ctx/core/conversation.py` and
`ctx/core/storage.py`. Neither is a bug and neither needs changing. They're
recorded only so the understanding isn't rediscovered from scratch later.

## Observations

### 1. `stream()` is positionally coupled to `submit()`

`ConversationCore.stream()` builds the LLM context with `self.nodes[:-1]`, which
relies on the last node being the empty assistant placeholder that `submit()`
appended. It's an implicit ordering contract the type system doesn't enforce —
fine as long as `submit()` then `stream()` is the only call sequence, which it is.

Worth keeping in mind: if that coupling ever became inconvenient, the assistant
node could instead be excluded by identity (`[n for n in self.nodes if n is not
assistant_node]`) — same behavior, no reliance on position. Not a change to make
now, just the escape hatch if the invariant ever gets in the way.

### 2. The persistence model fits today, and has a feature-shaped horizon

`ConversationRepository.save()` is full-replace (`DELETE` all nodes for the
conversation, then re-insert). For today's flat-list snapshot model this is
correct, simple, and impossible to desync, and saves fire ~once per human action
so the re-write cost is negligible — including as conversations grow. The
efficiency angle is settled: full-replace is the right call.

The thing to remember is *why* it might change one day, and it isn't speed — it's
features. Branching, compression, the `:history`/reversal log, and
cross-conversation imports (Product Concept §4–5) each lean on an assumption this
model makes: that a conversation is a flat ordered list, that a node belongs to one
conversation, that order = `rowid`, that `DELETE` is safe because we rebuild, and
that current state is all we store. `DELETE FROM nodes` in particular is the
opposite of "nothing is truly deleted." So if those features arrive, expect the
persistence *model* to shift (soft-delete + a node graph with edges + an
append-only operation log) rather than `save()` merely getting faster. Stable node
UUIDs, the open `meta` dict, and the `StoragePort` seam mean that shift would be an
additive migration, not a rewrite — which is exactly why there's nothing to do
ahead of time.

### 3. `DEFAULT_MODEL` is hardcoded in the core; it belongs in config

`DEFAULT_MODEL = "openrouter/google/gemma-4-26b-a4b-it"` lives in
`conversation.py`. The model resolves fine — the point is *placement*. The
framework-free core hardcodes a specific provider/model string while `config.py`
already owns user-overridable settings. The default model would sit more naturally
there (a user-settable default), with `conversation.py` reading it rather than
defining it. Worth doing when we next touch config: drop the constant here and
source the default from `config.py`.

### 4. `new_conversation()` silently reverts the model to default

`/new` resets `self.model = DEFAULT_MODEL`, discarding whatever model you had
switched to. Possibly intentional, but undocumented: switching model and then
starting a new conversation drops you back on the default with no notice.

### 5. Smaller modeling notes

- **Title derivation is duplicated.** `content[:MAX_TITLE_LENGTH].replace("\n", " ")`
  appears in both `_ensure_conversation` and `resume_conversation`; a shared helper
  would stop the two from drifting.
- **A conversation can be persisted with an empty title** — e.g. only `/include`d
  files, or a resume with no `user` node. It self-heals on the first real message
  (empty string is falsy), so it's an edge case, not a defect.
- **`content` is overloaded.** It's the real payload for `user`/`assistant` nodes,
  but a human label (`"Included: …"`) for `context` nodes, whose actual payload
  lives in `meta["source_path"]` + lazy load. Reading `.content` generically means
  different things per `node_type`.

### 6. The persist policy is implicit and lives in no single place

Whether a given command calls `persist()` is decided independently inside each
method. No docstring, comment, or single definition states the policy, and nothing
flags a method that makes a different choice — a new command could add or omit a
`persist()` call and nothing would complain. The behavior is fine today; the point
is that the policy is a convention carried in the individual methods rather than
expressed anywhere.

Ways to firm it up, weakest to strongest:

- **Document it.** A class-level note on when a command persists. Makes the rule
  discoverable; doesn't prevent mistakes.
- **Pin it with tests.** Assert, per command, whether a save happened. Fits this
  repo's contract + mutmut style — detection rather than prevention, but mutation
  testing is built to catch a flipped persist decision.
- **Make it structural (Rung 3).** Route node additions through a single choke
  point — e.g. an internal `_add(node)` helper that owns the persist decision — so
  individual commands no longer each decide it. The policy then lives in one place
  and a new command can't diverge from it by accident.

Today, with a small stable set of commands, the structural version would be an
abstraction ahead of its need (deletion test). It earns its place once more node
kinds arrive and the persist rules stop being uniform.
