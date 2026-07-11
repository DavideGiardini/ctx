# Code Quality Review & Locality Roadmap — `ctx` @ `feat/compression`

> Review + design session, July 2026. Judged against the `/codebase-design`
> deep-module framework and the repo's own ADRs. Branch `feat/compression`,
> 89 commits ahead of `develop` (the whole Sprint 3 compression feature).
> No code was changed in this session — review and design only.

---

## Overall verdict

An **unusually disciplined codebase**: real seams with two adapters each
(Provider, StoragePort, injected `read_file`), a framework-free core, exemplary
deep modules (`workspace.py`, `reconstruction.py`), 705 contract-traceable tests,
and clean UI↔core seam discipline. The debt is concentrated in two areas — the
**streaming-turn lifecycle** and **duplicated single-source-of-truth rules** —
both of which get more expensive once Sprint 4 branching lands.

## Problems

### Critical

- **Nothing prevents submitting a message mid-stream** (`app.py:1319` +
  `conversation.py:335`). The input bar stays focused during a stream, so a
  second Enter launches a second concurrent worker. Consequences compound: the
  first stream's `finally` clears `_streaming` while the second turn is live,
  **unmasking the H2 compression-safety guard** (ADR-0016 A#3 §2); the second
  turn's context is built from the first assistant node's still-growing content,
  so its `ctx_hash` digests partial content and is **persisted immutably** — a
  permanent, unverifiable "reconstruction may be inexact" warning. Found
  independently by both the core and UI agents; confirmed in source.

### Major

- **Streaming-lifecycle cluster**: `/new` and `/resume` orphan the live stream
  worker (burns tokens, terminal `persist()` fires against the *now*-loaded
  conversation, unmasks H2 again); the streaming flag can stick `True` if the
  worker is cancelled before its first tick (blocks all compression ops); a
  provider error leaves an invisible empty node at the tip forever (error text
  lives only on the widget, not `node.content`); the UI mutates `Node.meta`
  (`interrupted`/`error`) past the core's seam, *after* the core already
  persisted, so durability is accidental; Ctrl+C during a draft exits the whole
  app; `@work` defaults mean a storage/rewind exception crashes the app.
- **The fold rule is implemented twice** — `conversation.py` (`_active_folds` +
  run-collapse loop) and `reconstruction.py` (`_fold`). This is the dual-truth
  disease ADR-0016 A#3 §3 was written to kill, reincarnated as duplication.
- **The truncation map has already diverged** (verified): `message_row.py:27`
  maps `"compression" → "assistant"`; `app.py:36` lacks the entry, so
  `describe_state()` reports a different truncation for K nodes than the screen
  renders.
- **AGENTS.md has provably rotted** (the `draft_compression` paragraph describes
  pre-task-47 behavior CONTEXT.md explicitly supersedes); unbounded runtime deps
  (the real `textual>=8.2.7` floor lives only in a uv override that never reaches
  wheel metadata); CI pins no Python version; the Ralph loop has no
  per-iteration timeout.

## Locality and Design

### Message-rendering redesign (accepted)

The proposal — replace four emergent spacing mechanisms (base margin, pass-start
margin, selection margin→padding rewrite, per-context height overrides) with
**"geometry computed once from the nodes; state only recolors"** and a thin
separator widget at turn boundaries — is sound and net-**negative** complexity
(one new concept, `separator`, retiring four mechanisms plus their compensation
CSS). It's a better architecture *even without the bugs*: it gives the "one blank
between turns" rule a single owner (locality), decouples the state axis from the
geometry axis permanently (orthogonality), moves spacing guarantees from
agent-judged visual fixtures to deterministic DOM assertions (cheaper test
layer), and completes a design stance `MessageRow` already committed to ("the row
owns no interaction state").

**Amendment 1, resolved:** the reframed invariant — *"a row owns no spacing,
ever; each context's container owns geometry"* — was adopted in full. The
maintainer **rejected fixed diff slots** in favor of **measured heights +
symmetric per-region padding** (`max(left, right)` on both panes). I conceded:
my amendment conflated the invariant (deterministic per-region alignment, equal
pane heights — the thing tasks 50/51 depend on) with one mechanism for achieving
it (fixed slots), and the `ui.truncation_lines` argument is decisive — fixed
slots pad a one-word "Yes" to N rows at cap 5 and have no defined height at
`"auto"`, so they were never a general model.

Two cautions on the measured-height design:

1. The left pane's `border-right: solid $surface` makes it one cell narrower
   than the borderless right pane, so "shared-by-id blocks match their right-side
   twins" is **false by one cell today** — identical text can wrap differently.
   Make the pane chrome symmetric before relying on twin-width equality.
2. Reusing the conversation-list's known heights in the diff reintroduces the
   exact ownerless-cross-context invariant the redesign kills (diff correctness
   would silently depend on `app.css`'s layout of a different screen). **Measure
   in-place instead** — the cost is one layout pass over a few dozen widgets,
   measured once per open — and add a deterministic **DOM alignment assertion**
   (every region's first widget has the same y-offset in both panes) as the
   tripwire that replaces the visual fixture.

### Turn lifecycle (major)

Not a bug list, a *missing owner*. "One turn in flight, with a clean start and
end" is emergent from ≥6 places that must agree: `core._streaming` (set in
`submit()`, cleared only in `stream()`'s generator `finally`), the UI's
`_stream_worker` + `_streaming_node`, `on_worker_state_changed` matching workers
*by name*, guards at only 3 of the core's ~8 mutators, and cancel/error/drop
policy split across `app.py` and `conversation.py`. Every critical/major
streaming finding is two of these disagreeing.

**A turn is not a node.** It's the ephemeral *generation episode* — one
`submit → stream` cycle — anchored on its assistant node but not equal to it (the
node is the durable artifact; the turn is the live process that fills it). Same
category as "highlighted": transient session state that is *about* a node, keyed
to it, but lives off it and never persists. Its only durable trace is a mark left
at its ending (interrupted/error).

**The fix is a set of functions on existing objects — no new class, no new
model.** Single ownership ≠ a new object; here it's achieved by *disciplining*
what exists. (Contrast the separator widget, which earned an object because the
gap needed DOM identity + reconciliation; a turn is one flag + one node-ref + a
few transitions, which a class would only wrap in ceremony.) The product decision
settles the structure: **refuse a second submit, don't queue** → turns stay
singular → a flag suffices. Queuing (turns become plural, need identity/ordering)
or a swappable worker would be what finally earns an object; neither exists today.

Shape:

- **Core owns the fact.** `submit()` *refuses* (raises, mirroring
  `_validate_compress_range`) while `_streaming` is true — the authoritative
  backstop no caller can bypass. A new `end_turn(node, *, cancelled/error)` clears
  `_streaming`, stamps the durable ending mark, and persists, so `stream()` stops
  touching the flag entirely (delete its redundant set + `finally`). This pulls
  the `meta["interrupted"]`/`meta["error"]` writes *into* the core (fixing
  accidental durability) and unifies the abnormal-ending policy in one place — the
  aborted-turn candidate below folds in here.
- **UI owns the mechanism.** The worker + node references stay UI-side (Textual
  objects can't cross into framework-free core — this split is deliberate, not
  smear: the *fact* has one home, the *machinery* another). The single
  convergence point is `on_worker_state_changed`: it fires on **all** terminal
  transitions — SUCCESS, ERROR, and CANCELLED *including a cancel before the
  worker's first tick* — which is exactly why the flag-clear must move here from
  the generator's `finally` (a coroutine cancelled before it starts never runs its
  own `finally` — the stuck-flag bug). This one handler calls `core.end_turn`,
  drops an empty node, refreshes the gauge. `/new` and `/resume` cancel the stream
  worker too (today they orphan it); Ctrl+C cancels a live draft instead of
  exiting.
- **UI check is the derived read.** `on_input_bar_submitted` reads `core.streaming`
  and, if streaming, shows a hint and returns *without clearing the input*, so
  typed-ahead text survives. This needs `InputBar.action_submit` to stop clearing
  `self.value` unconditionally (it clears *before* posting `Submitted` today):
  clearing becomes a consequence of *acceptance*, owned by the app.
- **Pin the load-bearing assumption with a test:** that `on_worker_state_changed`
  really does fire `CANCELLED` when a worker is cancelled before its first tick.
  The robust-clear design rests entirely on it.

Keep it minimal — no queuing, retry, or turn-history. One turn, its worker, its
three endings. The moment it grows a feature nothing needs, it's a speculative
seam.

### Aborted-turn policy (major)

**Decision: Option B — keep the aborted node, mark it durably, render from the
mark.** A turn that ends abnormally (provider error, or a cancel after some tokens
streamed) stays where it happened; a persisted flag on the node (`meta["error"]` /
`meta["interrupted"]`) records that it failed, and the renderer reads that flag, so
the failure is visible in place and survives a reconcile and a resume. The rejected
alternative (A) retired the aborted node and announced the failure elsewhere (a
transient hint or a separate breadcrumb node) — cleaner in that no hollow assistant
turn is ever persisted, but it can't show "this specific turn failed, right here" a
week later, which is the property we wanted.

Today there is no single answer to "what does an aborted turn leave behind." Four
endings each decided it independently: a clean finish keeps its content; an *empty*
cancel is retired off the active line (task 48); a *partial* cancel is kept with its
partial content; an error keeps an **empty** node at the tip with the error text
written only onto the widget — so any later reconcile (commit, expand, deep-dive) or
a resume re-renders from the empty `node.content` and the message vanishes, leaving a
blank `▌` row forever.

**Why it's a locality candidate — and what actually gets localized.** Not the four
endings: a clean finish, an empty cancel, a partial cancel, and an error legitimately
produce different outcomes, and merging those *decisions* would be wrong. What has no
home is the one *procedure* every ending shares — lower the streaming flag, record
durably what the turn became, persist. Those three steps are scattered across three
files (the flag clears in `stream()`'s `finally`, or never if the worker is cancelled
before its first tick; the mark is stamped by the UI in `_stream_response`; the
persist runs in the core's except branch), so no function embodies "what ending a
turn means," and you can only verify a turn ends correctly by tracing all three and
checking they jointly cover every case.

**The scattering already produced the bug that breaks Option B.** The error path
stamps `meta["error"]` *after* the core persisted, so the durable mark B relies on is
never actually written to disk — quit right after an error and it is gone. That
ordering mistake is only *possible* because "stamp the mark" and "save" live in
different places; inside one ending function they are adjacent lines and cannot be
reversed.

**Shape — folds into `end_turn` (turn-lifecycle candidate above).** `end_turn(node,
outcome)` is the single door every ending passes through: it lowers the flag and
persists (shared, always — and persist always runs *after* the mark), and branches on
`outcome` only to stamp the ending-specific mark. This pulls the `meta` writes out of
the UI and into the core, so their durability is guaranteed rather than accidental.
Two things stay deliberately outside it: the renderer must display a node from its
*persisted* mark, not one-shot widget text (that is what retires the vanish-on-resume
ghost), and the UI keeps the separate call on whether an *empty* cancel is dropped off
the active line (task 48) — a view decision, not part of the durable ending. Deciding
this while building `end_turn` costs almost nothing; deferring it means opening the
same seam a second time to add the endings that were skipped.

### Fold unification (major)

**Frame it as policy vs mechanism, not "duplicated code."** Folding is one
*mechanism* parameterized by one *policy*:

- **Mechanism** (fixed, must never vary): walk the line, find each active `K`
  whose recorded range lies on it, collapse each contiguous run of that `K`'s
  children into the `K`.
- **Policy** = the *predicate*: a pure `Node -> bool` on a single compression
  node answering **"is this `K` active?"** (`True` ⇒ its summary stands in the
  view and its children disappear; `False` ⇒ it's ignored and its children show
  verbatim). This is the *only* thing that legitimately differs between callers —
  now vs as-of. Two flavors: the now-rule (`k.id not in expanded` — no `E`
  targets it at all) and the as-of rule (`k.created_seq < turn_seq and k.id not
  in expanded_before` — the now-rule with a `created_seq` time-cut so a turn only
  sees `K`s that predate it and expands that predate it).

  The predicate is **only** the "is it active" question. Whether the range even
  lies on this line is a *separate*, fixed check inside the mechanism (gate 2),
  not part of the predicate — which is why the predicate is safe to call on any
  compression node in the graph, including off-line ones.

`reconstruction.py` models the split correctly: `_fold` is the mechanism, the
predicate is a parameter, three call sites pass three predicates.
`conversation.py` does **not**: `_active_folds` + the collapse loop in
`current_view` is the same mechanism with the now-policy *welded in*. So the
precise defect isn't "some code is duplicated" — it's that **one copy fuses
policy into mechanism while the other separates them, leaving the mechanism in
two hand-synced copies.** Reconstruction already did the hard part (isolating the
predicate); the live path just didn't adopt it.

**Why the fusion is dangerous — the thing that will change is the policy.** S4's
branch-local expand rewrites the predicate ("no `E` targets it" → "no `E` *on
this line* targets it"). In the well-factored world that's a one-line edit to one
predicate; as things stand it's an edit to `now_prefix`'s predicate **and** a
matching edit inside conversation's welded copy, which must agree. And nothing
guards that agreement: the `ctx_hash` tripwire checks *then-vs-now for one turn*,
never *live `current_view` vs `now_prefix` consistency* — so a fork between the
two fold copies makes the conversation fold one way and the drift/diff view fold
another, silently, and on the rare occasions the tripwire fires it always blames
"reconstruction" even when the live copy is the buggy one. This is exactly the
dual-truth failure A#3 §3 killed for data, re-entering through code.

**Fix.** Make the live path adopt the split reconstruction already has: delete
`_active_folds` + the inline collapse loop; have `current_view` build the
now-predicate from its own state and call the one `_fold`
(`_fold(list(self._graph.values()), line, applies=lambda k: k.id not in
expanded)`). After this all three call sites are the same shape — *build a
predicate from local state, call the one mechanism* — and a future policy change
touches only predicates, in a place where being wrong is caught. Low-risk: both
sides are pure with existing tests, and you're deleting a special case, not
inventing an abstraction.

**Decision — Option A (fold-only).** The shared `_fold` **stays in
`reconstruction.py`**; `current_view` imports it. Cheapest coherent move:
`conversation.py` already imports reconstruction (for `hash_context`), and
`hash_context` *already* runs on the live path at generation — so a pure
reconstruction primitive being called live is a pattern already present here, not
a new violation. A vs B is genuinely low-stakes and reversible: the valuable work
(separating predicate from mechanism, deleting the duplicate) is identical either
way; A vs B only decides which file one function's source sits in, a five-minute
move later if it ever wants its own home.

**The walk is deliberately left duplicated.** `_active_line` (conversation) and
`_strict_ancestors` (reconstruction) are the same defensive prev_id walk seeded
at different nodes, but the walk carries *no policy*, S4 doesn't touch it, and the
two copies aren't diverging — so it fails all three build-now tests on its own.
It was the only thing that would have justified a neutral module (Option B: a
`walk` + `_fold` "pure projections over the graph" home); choosing A means the
walk stays put. Revisit only if a future change gives the walk its own forcing
event.

**One load-bearing obligation A carries.** Once `current_view` calls `_fold`,
reconstruction.py's "**never on the live generation pipeline**" banner is false as
written and a future reader could "fix" the live call back out. The change isn't
done until that banner is rescoped to say what it actually means: the *as-of
oracles* (`context_at_generation`, `now_prefix`, `has_drift`, `diff_regions`,
`reconstruction_warning`) never run live; the pure primitives (`_fold`,
`hash_context`) are callable anywhere. Treat this doc edit as part of the change,
not an afterthought.

### Test choreography helpers (major)
~400 lines of duplicated Pilot scaffolding (`_app`, `_BlockingProvider`, the
compress-via-editor keystroke sequence) across 19 files, already diverging (the
inconsistent `if mode == "edit": escape` workarounds). Pure extraction into
conftest — no protocol break, no interface decision. The separator-widget of the
test suite; safe to hand to a Ralph iteration unsupervised.

### Model-facing-form extraction (mid)
`build_context`'s per-type rendering and `_transcript_block` are two hand-synced
copies of "what does this node look like to the model," same file — tolerable
alone, so don't do it standalone. But S4's import nodes add a node type, forcing
the rule to be taught in both places. Do the extraction *as the preamble* to that
S4 work.

### Typed `meta` accessors (low - defer)
Full version (accessors for every key across four modules + specs + tests)
protects against a typo class specs and mutmut already largely cover, on a small
stable key set. Do only the 20% that's real — resolve the unregistered
`interrupted`/`error` keys (really a #1/#3 concern anyway). Revisit if S4
multiplies the vocabulary.

### StoragePort read collapse  (low - defer)
Benefit mostly aesthetic — four connections vs one is irrelevant for local
single-process SQLite; torn-read risk is theoretical when the app is its own only
writer. Cost (protocol break through `SaveCountingStorage`, storage specs,
migration tests, harness) is real. Fold into S4's branch-delete/session-undo
work, which forces storage changes anyway.

### ViewStack — schedule as S4's first task (close call)

Invariants currently hold; the tax is "expensive to keep holding," which alone
doesn't justify refactoring working guards on spec. What tips it: S4's sub-chat
design *adds new view states to precisely this cluster* (`mode`, deep-dive stack,
diff view, escape priority ladder). Retrofitting a state machine mid-sprint under
feature pressure is the worst timing; building it as S4 groundwork with the new
states known-but-unbuilt is the best. If S4 lands no new surfaces, it stays
unbuilt with no regret.

### The through-line (re-run this yourself)

- **Build** when there's **bug pressure now** (#1, #3), a **forcing event on the
  calendar** (#2, #5, ViewStack-at-S4), or **duplication already diverging** (#4).
- **Defer** when benefit is theoretical and ripple cost is real (#6, #7).
- Let the **next forced touch** of the code carry the deferred refactor for free.
- **Don't** reify an invariant that still has only one reader (e.g. a
  `SelectionModel` today) — the one-adapter rule applies to invariants too.
