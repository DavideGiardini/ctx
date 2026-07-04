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

## N4 — `deep_dive.breadcrumb` line (values surfaced; separator NOT asserted)

**CS17. Breadcrumb with >1 element surfaces every label in order, before the header**
- Given: `deep_dive = {"breadcrumb": ["Chat", "K a1b2", "Diff a1b2"]}` plus nodes.
- Expect: exactly ONE new top-level line (before the header) contains each label
  string, and their relative order is preserved
  (`line.index("Chat") < line.index("K a1b2") < line.index("Diff a1b2")`).

**CS18. A lone root breadcrumb (`["Chat"]`) is noise → no line**
- Given: `deep_dive = {"breadcrumb": ["Chat"]}` plus nodes.
- Expect: no breadcrumb line is emitted (only the fixed first line precedes the header).

**CS19. Empty breadcrumb → no line**
- Given: `deep_dive = {"breadcrumb": []}`.
- Expect: no breadcrumb line is emitted.

**CS20. Absent `breadcrumb` / absent `deep_dive` → no line**
- Given: `deep_dive = {}` and, separately, a state with no `deep_dive` key.
- Expect: no breadcrumb line is emitted in either case.

---

## N5 — `diff_view` line (values surfaced; wording NOT asserted)

Tests build states WITHOUT a `detail` dict so no unrelated line carries "diff";
the diff line is located by the region-count / `warn` / `drill` values it carries.

**CS21. `open: True` → exactly one diff line (before header) surfacing the region COUNT**
- Given: `diff_view = {"open": True, "regions": [r1, r2], "warning": False, "drill": None}`
  (2 regions) plus nodes, no `detail`.
- Expect: exactly one new top-level line (before the header) surfaces the integer
  `2` (len of regions).

**CS22. Empty regions → count `0` surfaced**
- Given: `diff_view = {"open": True, "regions": [], "warning": False, "drill": None}`.
- Expect: the diff line surfaces the integer `0`.

**CS23. `open: False` or absent `diff_view` → no diff line**
- Given: `diff_view = {"open": False, ...}` and, separately, no `diff_view` key.
- Expect: no diff line is emitted in either case (only the fixed first line precedes
  the header).

**CS24. `warning` indicator toggles with the flag**
- Given: `diff_view` open with `warning: True` vs `warning: False` (drill None).
- Expect: when `warning: True` the diff line contains a case-insensitive `warn`
  token; when `warning: False` it does NOT.

**CS25. `drill` indicator toggles with a non-None drill dict**
- Given: `diff_view` open with `drill: {…}` (non-None) vs `drill: None`.
- Expect: when `drill` is a non-None dict the diff line contains a case-insensitive
  `drill` token; when `drill` is `None` it does NOT.

---

## Purity / tolerance

**CS26. render tolerates every new key being absent (no crash)**
- Given: a valid state with nodes and NONE of `drift`, `context_gauge`,
  `range_selection`, `deep_dive`, `diff_view` present.
- Expect: `render` returns a `str` without raising; no `Δ` and no `range=` appear.
