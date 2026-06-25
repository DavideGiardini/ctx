# Behavioral contract — `tools/agent/snapshot.py` :: `render`

The oracle of record for `render(state: dict) -> str`. Authored code-blind from
intent (see `.claude/skills/write-tests`), then human-adjudicated. Tests in
`tests/test_snapshot.py` cite these item ids. **When behavior changes, update this
contract first**, then the tests.

`render` is a PURE presentation function. Given the raw state dict produced by
`ChatApp.describe_state()`, it returns a compact, stable, diffable multi-line text
block (~100 tokens) that an AI agent reads between actions. All truncation/compaction
lives here so the UI class stays free of AI-presentation concerns. The output is a
newline-joined block whose **structure is fixed**: lines always appear in the same
relative order, and a "noise" line is OMITTED entirely when its data is not meaningful
(rather than rendered blank), so two snapshots taken between actions diff cheaply.

Where intent fixes an exact format (the first line, the streaming literal, the node
markers, the file/weight suffixes) it is byte-exact contractual. Where intent only says
a composite line "summarizes"/"surfaces" data (the command-menu segment, the detail
line, the colors legend) tests assert observable presence/substrings of the meaningful
VALUES plus the omit/placeholder rule — never exact labels or punctuation, which are
unfixed presentation wording.

## Contract

### First line & top-level optional lines

**C1. First line always present, exact format.**
- Given: valid state `mode="chat"`, `focus="input"`, `streaming=False`, `model="gpt-4o"`, no nodes.
- Expect: first line is exactly `mode=chat focus=input streaming=no model=gpt-4o`. Always emitted regardless of which optional keys are present.

**C2. `streaming` renders as `yes`/`no`, never `True`/`False`.**
- Given: two states differing only in `streaming` True vs False.
- Expect: first line contains `streaming=yes` (True) or `streaming=no` (False); `True`/`False` never appear in that segment.

**C3. `focus` rendered as-is, including when key absent.**
- Given: (a) `focus="nodes"`; (b) no `focus` key.
- Expect: (a) first line contains `focus=nodes`; (b) the first line still has a `focus=` segment rendering the none-ish value (`focus=None`), not an omitted segment — the first line is fixed at four `key=value` segments. *(adjudicated: focus is rendered as-is; absence is a none-ish value, not a dropped segment.)*

**C4. `title` line present iff title truthy.**
- Given: (a) `title="Refactoring plan"`; (b) `title=""`; (c) no key.
- Expect: (a) output contains a line including `Refactoring plan`; (b)/(c) no title line at all.

**C5. `input` line present iff input non-empty OR command menu open.**
- Given: (a) `input="explain this"`, no menu; (b) `input=""`, no menu; (c) `input=""`, menu open; (d) no `input` key, menu present.
- Expect: (a) input line present, includes `explain this`; (b) no input line; (c) input line IS present though input empty (menu open); (d) input line present.

**C5e. The input line surfaces the input text itself, and a menu does not replace it.**
- Given: `input="filter text"` AND a command menu open.
- Expect: the input line contains the input text `filter text` AND the menu's selected entry — opening a menu adds the menu segment alongside the input value; it does not drop/overwrite the input value.

**C5f. No input line when input is absent (no key) and no menu.**
- Given: a state with no `input` key and no `command_menu`.
- Expect: no input line at all (an absent input is "no input text", same as empty — C5b).

**C5g. Absent input renders as empty, never the word "None".**
- Given: no `input` key but a command menu open (so the input line is shown).
- Expect: the input line shows an empty input value — the literal `None` does not appear in the input line.

**C6. `footer` line present iff footer truthy.**
- Given: (a) `footer="3 changes pending"`; (b) `footer=""`; (c) no key.
- Expect: (a) line including `3 changes pending`; (b)/(c) no footer line.

**C7. `detail` line present iff non-empty detail dict.**
- Given: (a) `detail={"view":"diff","node_index":2,"pane_mode":"none","locked":True}`; (b) `detail={}`; (c) no key.
- Expect: (a) exactly one detail line observably reflecting fields (contains `diff` and the index `2`); (b)/(c) no detail line. Byte-exact format NOT asserted. (Internal structure pinned by C30–C45.)

**C8. `colors` line present iff non-empty colors dict.**
- Given: (a) `colors={"user":"cyan","assistant":"green"}`; (b) `colors={}`; (c) no key.
- Expect: (a) exactly one colors line containing each role and value; (b)/(c) no colors line. (Completeness pinned by C46.)

### Nodes header

**C9. Nodes header always present, reports count.**
- Given: (a) three node dicts; (b) `nodes=[]`; (c) no `nodes` key.
- Expect: (a) a line beginning `nodes=3`; (b)/(c) a line beginning `nodes=0`. Present in all cases.

**C10. Header `selected=[<i>]` segment present iff `selected_index` set.**
- Given: (a) `selected_index=1`, two nodes; (b) `selected_index=None`; (c) no key.
- Expect: (a) header line contains `selected=[1]`; (b)/(c) no `selected=` segment.

### Per-node lines

**C11. Per-node line leading markers are two fixed-width chars.**
- Given: single node `selected=False`, `truncated=False`, role `user`, index 0, content `hello world`.
- Expect: line begins with two leading spaces then `[0] user` (role left-padded) then `hello world`. Both marker positions occupy exactly one char so columns stay aligned.

**C11b. A node with no source_path and no weight has nothing appended after its content.**
- Given: single minimal node (index/role/content set; no `source_path`, no `weight_pct`).
- Expect: the node line ENDS with the node's content — there is no trailing text after it (the file/weight suffixes are present only when their data is, per C15/C16, so a bare node's line terminates at its content).

**C12. Selection marker `*` when selected, space otherwise.**
- Given: two nodes — A `selected=True`, B `selected=False`, both `truncated=False`.
- Expect: A's line's char[0] is `*`; B's char[0] is a space; char[1] (truncation) is a space for both.

**C13. Truncation marker `~` when truncated, space otherwise.**
- Given: two nodes — A `truncated=True`, B `truncated=False`, both `selected=False`, short content.
- Expect: A's char[1] is `~`; B's char[1] is a space; char[0] (selection) is a space for both.

**C14. Both markers co-occur.**
- Given: node `selected=True`, `truncated=True`.
- Expect: line begins with `*~` then `[<index>] <role> ...`.

**C15. `(file: <path>)` suffix iff `source_path` present.**
- Given: (a) `source_path="src/app/main.py"`; (b) no key.
- Expect: (a) line contains `  (file: src/app/main.py)`; (b) no `(file:` substring.

**C16. `w=<n>%` suffix iff `weight_pct` present.**
- Given: (a) `weight_pct=42`; (b) no key.
- Expect: (a) line contains `  w=42%`; (b) no weight suffix.

**C17. Both suffixes co-occur, file before weight.**
- Given: node with `source_path="docs/spec.md"` and `weight_pct=7`.
- Expect: line contains both `(file: docs/spec.md)` and `w=7%`, with the file suffix before the weight suffix.

### Content collapse & truncation

**C18. Content collapsed: every whitespace run becomes one space.**
- Given: content `"first line\n\tsecond   part"`.
- Expect: content portion is `first line second part` — no newline/tab/multi-space run survives; each run becomes exactly one space. *(adjudicated: "runs of whitespace → one space" = all whitespace, i.e. `str.split()` semantics.)*

**C19. Content ≤ 80 chars shown in full, no ellipsis.**
- Given: collapsed content exactly 80 chars (no internal whitespace to collapse).
- Expect: content portion equals that 80-char string verbatim; no `…` for this node; content portion length is 80.

**C20. Content > 80 chars truncated with trailing `…`, still within budget.**
- Given: collapsed content exactly 81 chars.
- Expect: content portion ends with a single-char `…`; the leading chars match the original prefix; the result still fits the 80-char budget (length, counting `…` as one char, is 80 — i.e. 79 prefix chars + `…`). *(adjudicated amb. 2/3: budget is Unicode-char `len`; `…` counts as one char; overflow cuts to 79 + `…` = length 80.)*

### Empty nodes, ordering, purity

**C21. Empty/absent nodes: header lines only, no per-node lines.**
- Given: (a) `nodes=[]`; (b) no `nodes` key.
- Expect: output is only the always-present header lines (first line + any meaningful optional lines + `nodes=0`); no per-node lines.

**C22. Purity — no input mutation.**
- Given: a fully-populated state (all keys, nodes with all optional fields, `selected_index`); deep-copied before the call.
- Expect: after `render(state)`, `state` equals the pre-call deep copy — no key added/removed/changed, nested structures unchanged.

**C23. Purity — determinism: same input → identical output.**
- Given: a valid state rendered twice, and a separately-constructed equal state rendered once.
- Expect: both calls on the same dict return byte-for-byte equal strings, and the equal-but-separate dict yields the same string.

**C24. Line ordering fixed and stable.**
- Given: a state exercising every line type (title, input, footer, detail, colors, nodes header, per-node lines).
- Expect: fixed relative order — first line first; optional lines before the nodes header; nodes header before all per-node lines; per-node lines follow input node order. Omitting a line never reorders the others.

### Command-menu segment (internal structure of the input line)

**C25. Menu selected entry is always surfaced when a menu is open.**
- Given: `command_menu` a dict whose `selected` is a recognizable command name (e.g. `"add-context"`), any/no `count`/`occluded`.
- Expect: the rendered block contains the literal value `add-context`.

**C26. Menu count is surfaced when it is a known integer.**
- Given: `command_menu` with `selected` set and `count` a known integer (e.g. `7`).
- Expect: the rendered block contains `7` within the command-menu segment.

**C27. Menu count is omitted when it is None (no number, no placeholder).**
- Given: `command_menu` with `selected="open-file"` and `count=None`.
- Expect: the segment still contains `open-file` but contains no count number and no count placeholder; the literal `None` does not appear in the segment.

**C28. OCCLUDED indicator present when occluded is true alongside a known count.**
- Given: `command_menu` with `selected` set, `count` a known integer (e.g. `5`), `occluded=True`.
- Expect: the rendered block carries an occluded indicator (case-insensitive `occluded`) in the command-menu segment, AND the known count (`5`) is still surfaced — the occluded indicator is appended to the count, it does not replace it.

**C29. OCCLUDED indicator absent when occluded is false.**
- Given: `command_menu` with `selected` set, `count` a known integer, `occluded=False`.
- Expect: no occluded indicator (no case-insensitive match for `occluded`).

**C47. OCCLUDED indicator requires a known count.** *(adjudicated amb. 3: the occluded
flag is "only meaningful alongside a known count"; with no count there is nothing to
qualify, so no indicator regardless of the flag.)*
- Given: `command_menu` with `selected` set, `count=None`, `occluded=True`.
- Expect: no occluded indicator appears (no case-insensitive match for `occluded`), and no count number/placeholder appears (consistent with C27).

### Detail line (internal structure)

**C30. Detail view identity is always surfaced when a detail view is active.**
- Given: `detail` non-empty with `view="diff"`, other fields valid.
- Expect: exactly one detail line, containing the literal value `diff`.

**C31. Detail node index surfaced when the inspector is bound to a node.**
- Given: `detail` active with `node_index=3`.
- Expect: the detail line contains `3`.

**C32. Detail node index uses a neutral placeholder when not bound.**
- Given: `detail` active with `node_index=None`.
- Expect: the detail line surfaces a neutral "no node" placeholder where the index would appear (non-blank), and the detail line does not contain the literal `None`.

**C33. Pane mode browse surfaces the highlighted split's value.**
- Given: `detail` active, `pane_mode="browse"`, `highlighted_split="left"`.
- Expect: the detail line contains `left`.

**C34. Pane mode browse with nothing highlighted surfaces a neutral placeholder.**
- Given: `detail` active, `pane_mode="browse"`, `highlighted_split` empty/absent (`None` or `""`).
- Expect: the detail line surfaces a neutral placeholder for the highlighted split (non-blank), and does not contain the literal `None`.

**C35. Highlighted split not surfaced outside browse mode.**
- Given: `detail` active, `pane_mode="maximized"` (or `"none"`), `highlighted_split="highlightonly-zzz"`.
- Expect: the rendered block does NOT contain `highlightonly-zzz`.

**C36. Pane mode maximized surfaces the maximized split's value.**
- Given: `detail` active, `pane_mode="maximized"`, `maximized_split="editor"`.
- Expect: the detail line contains `editor`.

**C37. Pane mode maximized with an empty value surfaces a neutral placeholder.**
- Given: `detail` active, `pane_mode="maximized"`, `maximized_split` empty (`""` or absent).
- Expect: the detail line surfaces a neutral placeholder for the maximized split (non-blank), and does not contain the literal `None`.

**C38. Maximized split not surfaced outside maximized mode.**
- Given: `detail` active, `pane_mode="browse"` (or `"none"`), `maximized_split="maxonly-zzz"`.
- Expect: the rendered block does NOT contain `maxonly-zzz`.

**C39. Pane mode none surfaces neither split field.**
- Given: `detail` active, `pane_mode="none"` (or key absent), `highlighted_split="hsplit-zzz"`, `maximized_split="msplit-zzz"`.
- Expect: the rendered block contains neither `hsplit-zzz` nor `msplit-zzz`; the detail line is still present (other fields surfaced).

**C40. Pane mode always surfaced, including the absent-key "none" case.**
- Given: (a) `pane_mode="browse"`; (b) `pane_mode` key absent; both with `detail` otherwise active.
- Expect: (a) the detail line contains `browse`; (b) the detail line surfaces a neutral "none" pane indicator (non-blank pane-mode position), and the detail line does not contain the literal `None`. *(adjudicated: absent `pane_mode` is treated as the neutral "none".)*

**C41. Locked surfaced as an affirmative indicator when locked is true.**
- Given: `detail` active, `locked=True`.
- Expect: the detail line surfaces a yes-style lock indicator (case-insensitive presence of a stable `lock` token); distinct from the false-case rendering (C42).

**C42. Locked surfaced as a negative indicator when locked is false.**
- Given: `detail` active, `locked=False`, otherwise identical to C41's state.
- Expect: the detail line surfaces a no-style lock indicator that is observably DIFFERENT from C41's rendering (the two renderings, differing only in `locked`, are not equal); the lock status is still surfaced, not absent.

**C43. Context view surfaces the visible splits' values.**
- Given: `detail` active, `view="context"`, `splits_visible=["tree","preview"]`.
- Expect: the detail line contains `tree` and `preview`.

**C44. Context view with no visible splits surfaces a neutral placeholder.**
- Given: `detail` active, `view="context"`, `splits_visible=[]`.
- Expect: the detail line surfaces a neutral placeholder for visible splits (non-blank), and does not contain the literal `None` or a bare `[]`.

**C45. splits_visible not surfaced for non-context views.**
- Given: `detail` active, `view="diff"`, `splits_visible=["splitvis-zzz"]`.
- Expect: the rendered block does NOT contain `splitvis-zzz`.

### Colors legend

**C46. Every role→color pairing is surfaced in the colors legend.**
- Given: `colors={"selected":"cyan","added":"green","removed":"red"}`.
- Expect: the rendered block contains every role (`selected`, `added`, `removed`) and every color (`cyan`, `green`, `red`); no pairing is dropped. (Tightens C8.)

### Robustness to sparse inputs (where render defends with a default)

These pin the cases render() deliberately guards (it reads these keys with a
default, unlike the required `mode`/`model` which it does not) — so a node/detail
missing an optional field is a case render() must tolerate, not crash on.

**C48. A node missing its `content` key renders as empty content, never crashes.**
- Given: a node dict with `index`/`role` but no `content` key.
- Expect: render does not raise; the node's line is produced with empty content (the
  same as an explicitly empty string), the per-node structure (markers, `[<index>]`,
  role) intact.

**C49. A context view missing its `splits_visible` key renders the neutral placeholder, never crashes.**
- Given: `detail` active with `view="context"` and no `splits_visible` key.
- Expect: render does not raise; the detail line surfaces the neutral "no visible
  splits" placeholder (same as an empty list, per C44).

### Falsy-but-valid values and unrecognized modes

These pin the boundary between "value absent" (segment omitted / neutral placeholder)
and "value present but falsy" (the real value `0`/`""` is surfaced). Intent: a numeric
zero is a *measured* value, not a synonym for "missing" — only an absent key is missing.

**C50. A weight of zero is a real weight and is surfaced.**
- Given: a node with `weight_pct=0` and no `source_path`.
- Expect: the node line contains the weight suffix `w=0%`. Zero is a meaningful measured
  weight; only an ABSENT `weight_pct` omits the suffix (per C16). (Distinguishes
  "value present" from "value truthy".)

**C51. A detail node index of zero is a bound node, not the unbound placeholder.**
- Given: `detail` active with `node_index=0`, otherwise valid.
- Expect: the detail line surfaces the bound index `0` (e.g. contains `[0]`) — NOT the
  neutral "no node" placeholder of C32. Index 0 is a valid binding; only `node_index=None`
  (C32) is unbound.

**C52. A selected index of zero is a real selection.**
- Given: `selected_index=0` with at least one node.
- Expect: the nodes-header line contains `selected=[0]`. Index 0 is a valid selection;
  only an absent/`None` `selected_index` (C10) omits the segment.

**C53. An unrecognized pane mode surfaces its own value and neither split field.**
- Given: `detail` active with `pane_mode` set to a value that is none of
  `browse`/`maximized`/`none` (e.g. `"split"`), with both `highlighted_split` and
  `maximized_split` set to recognizable values.
- Expect: the detail line surfaces the pane-mode value (`split`) and contains NEITHER the
  highlighted-split value (C33) NOR the maximized-split value (C36) — those qualifier
  fields are surfaced only in their own modes. (Generalizes C35/C38 to an unknown mode.)

## Adjudication notes

- **mode/model required — non-requirement.** A state missing `mode` or `model` is "never
  happens" per adjudication; `render` may raise `KeyError`. No contract item demands
  graceful handling and no test asserts behavior for that case.
- **"no literal `None`" assertions are scoped to the relevant line.** An absent top-level
  `focus` legitimately renders `focus=None` on the first line (C3), so detail-line items
  that forbid `None` (C32, C34, C37, C40, C44) assert against the **detail line**, not the
  whole block. Tests for those items set `mode`, `model`, and `focus` to real values so no
  incidental `None` appears.
- **Identifying "the detail line".** Tests locate it by a stable marker (the line carrying
  the `view` value), not by absolute line number — line position shifts as optional lines
  appear/disappear.
- **Composite-line wording is not asserted.** For the command-menu segment, detail line,
  and colors legend, only the meaningful VALUES and the omit/placeholder behavior are
  asserted — never exact labels (`command-menu→`, `view=`, `hi=`, `max=`, `splits=`,
  `locked=`, the `…` of `N items`) or punctuation. Those are diagnostic presentation
  wording; pinning them would couple tests to the implementation. Mutmut survivors that
  only alter such wording are equivalent w.r.t. this contract (see Mutation testing).
- **Neutral placeholder token.** Items asserting a "neutral placeholder" require only that
  the position is non-blank and is not the literal `None`/`[]` — the exact symbol is
  unfixed wording.
- **Open menu always has a selection.** Per intent, a menu is only open with a real
  `selected` entry; no contract item covers an open menu with no selection.

## Mutation testing (mutmut)
**212 mutants, 198 killed, 14 survivors — all documented-equivalent w.r.t. this contract.**

The 14 survivors are all single-token spelling changes inside the composite presentation
lines; every one leaves intact the *semantics* the contract asserts (presence of a value,
true≠false distinguishability, case-insensitive marker), so no test can — or should —
distinguish them. They fall into three families:

- **Neutral-placeholder token** (`-` → `XX-XX`): mutants 73 (node index), 104 (browse
  highlighted), 114 (maximized), 133 (context splits). The contract (C32/C34/C37/C40/C44)
  requires "a non-blank placeholder that is not the literal `None`/`[]`" — it deliberately
  does not pin the exact symbol, so any fixed token satisfies it.
- **Marker case / padding**: mutants 52, 53 (`OCCLUDED` casing/garble — C28 asserts a
  *case-insensitive* occluded marker), 81, 82 (`pane` default `none` casing — C40 asserts a
  case-insensitive `none` indicator), 84, 85, 89, 90 (`locked` `yes`/`no` casing — C41/C42
  assert a lock token is present and true≠false, not the exact words).
- **Join separator**: mutants 126 (`,` between visible splits — C43 asserts each split value
  appears) and 144 (` ` between colour pairs — C46 asserts each role/value appears). The
  separator is not part of the asserted semantics.

We deliberately do **not** assert these exact bytes: the contract was authored code-blind to
pin meaning, not spelling, and hard-coding the current spellings would (a) re-introduce the
implementation as the oracle and (b) break tests on any cosmetic restyle that changes nothing
an agent reading the snapshot would interpret differently. They are equivalent **with respect
to this contract**, not behaviourally identical. **Re-triage if any of these spellings becomes
contractual** — e.g. if a downstream consumer starts parsing the exact placeholder, the
`OCCLUDED` casing, or a separator — at which point the corresponding contract item should pin
the byte and the mutant becomes a genuine kill target.

Every other mutation — control-flow, conditionals, the fixed first-line/header/marker/suffix
formats, the 80/81 truncation boundary, default-value and missing-key handling (absent
`input`/`content`/`splits_visible`), and the occluded-vs-count and input-value-vs-menu
behaviours — is killed.
