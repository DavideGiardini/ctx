# Snapshot render() — Sprint 3 extension contract (N1–N5)

Behavioral contract for the FIVE NEW fields added to `render(state) -> str`
(`tools.agent.snapshot`). This section is additive to `snapshot.md` (C1–C53);
it does NOT restate any C-item. House style: byte-exact where intent fixes an
exact format (glyphs, `range=[…]`), presence/substring of meaningful VALUES plus
the omit/placeholder rule where intent only says a line "surfaces"/"summarizes".
Lines are always located by a stable value/marker they carry, never by absolute
line number. All new top-level lines sit AFTER the fixed first line and BEFORE
the `nodes=` header; the drift glyph is on per-node lines (after the header).

---

## N1 — per-node `drift` glyph (byte-exact `Δ`, placement fixed = last)

**CS1. Truthy `drift` appends `Δ` as the last non-space content on the node line**
- Given: a state with one node carrying `drift: True`.
- Expect: that node's line, right-stripped, ENDS WITH the exact character `Δ`
  (U+0394); the leading markers and `[<index>] <role>` structure are unaffected.

**CS2. Falsy `drift` renders no glyph**
- Given: a state with one node carrying `drift: False`.
- Expect: no `Δ` appears anywhere in the output.

**CS3. Absent `drift` key renders no glyph**
- Given: a state with one node that has no `drift` key at all.
- Expect: no `Δ` appears anywhere in the output.

**CS4. With both a weight suffix and drift, `Δ` comes AFTER `w=…%`**
- Given: a node carrying a `weight_pct` (so a `w=<n>%` suffix is emitted) AND `drift: True`.
- Expect: on that node's line the `w=` substring occurs BEFORE the `Δ` character
  (`line.index("w=") < line.index("Δ")`), and the line ends with `Δ`.

---

## N2 — `context_gauge` line (values surfaced; wording NOT asserted)

**CS5. `context_gauge` present with numeric `pct` surfaces the number and a `%`**
- Given: top-level `context_gauge = {"pct": 42, "approximate": False}` (plus nodes).
- Expect: exactly ONE new top-level line appears (before the header); it surfaces
  the substring `42` and a `%`.

**CS6. `pct: 0` is a measured value and is surfaced as `0` with `%`**
- Given: `context_gauge = {"pct": 0, "approximate": False}`.
- Expect: the gauge line surfaces the substring `0` and a `%` (0 is not treated as
  missing).

**CS7. `pct: None` renders a neutral placeholder, still present**
- Given: `context_gauge = {"pct": None, "approximate": False}`.
- Expect: the gauge line is still present and non-blank; the position where the
  number would be is a placeholder — the line does NOT contain the literal `None`
  and does NOT contain a bare `[]`.

**CS8. `approximate: True` carries the `~` marker on the gauge line**
- Given: `context_gauge = {"pct": 42, "approximate": True}`.
- Expect: the gauge line contains the character `~`.

**CS9. `approximate: False` → no `~` on the gauge line**
- Given: `context_gauge = {"pct": 42, "approximate": False}`.
- Expect: the gauge line does NOT contain `~`.

**CS10. Absent `context_gauge` → no gauge line**
- Given: a state with no `context_gauge` key (plus nodes, no other optional lines).
- Expect: the only line before the `nodes=` header is the fixed first line
  (no gauge line is emitted).

**CS11. Gauge line appears before the `nodes=` header**
- Given: `context_gauge` present plus nodes.
- Expect: the gauge line's position precedes the `nodes=` header line.

---

## N3 — `range_selection` segment on the nodes header (byte-exact)

**CS12. Non-empty `range_selection` → `range=[i,j,k]` on the header, no spaces, in order**
- Given: `range_selection = [0, 1, 2]` with 3 nodes.
- Expect: the `nodes=` header line contains the exact substring `range=[0,1,2]`.

**CS13. Index `0` is a valid member and is included**
- Given: `range_selection = [0]` with 1 node.
- Expect: the header line contains the exact substring `range=[0]`.

**CS14. Empty `range_selection` → no `range=` segment**
- Given: `range_selection = []`.
- Expect: `range=` appears nowhere in the output.

**CS15. Absent `range_selection` → no `range=` segment**
- Given: a state with no `range_selection` key.
- Expect: `range=` appears nowhere in the output.

**CS16. `range=` and `selected=` can co-occur on the same header line**
- Given: `range_selection = [0]` and a top-level `selected_index = 0` (the header
  `selected=` segment is driven by `selected_index`, per C10/C52, not a per-node flag).
- Expect: the single `nodes=` header line contains BOTH `range=[0]` and a
  `selected=` segment.

---

## N4 / N5 — removed (ctx0 subtraction, ADR-0017)

The `deep_dive.breadcrumb` line (CS17–CS20) and the `diff_view` line (CS21–CS25)
rendered the full-screen drill surfaces that ctx0 deletes. Those surfaces — and
the `render()` code, `describe_state()` keys, and tests that drove them — were
removed in the subtraction pass. Nothing renders them anymore.

---

## Purity / tolerance

**CS26. render tolerates every new key being absent (no crash)**
- Given: a valid state with nodes and NONE of `drift`, `context_gauge`,
  `range_selection` present.
- Expect: `render` returns a `str` without raising; no `Δ` and no `range=` appear.
