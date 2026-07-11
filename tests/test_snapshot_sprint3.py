"""Tests for the FIVE NEW render() fields (Sprint 3): N1–N5.

Contract: tests/specs/snapshot-sprint3.md (CS1–CS26). Existing C1–C53 behavior
lives in tests/test_snapshot.py and is NOT re-tested here.

Lines are located by stable value tokens they carry, never by absolute index.
All states are built from plain dict literals via the local helpers below.
"""

from tools.agent.snapshot import render

BASE_STATE = {"mode": "chat", "model": "gpt-4o", "focus": "input"}
BASE_NODE = {
    "index": 0,
    "role": "user",
    "content": "hello world",
    "selected": False,
    "truncated": False,
}


def state(**over):
    s = dict(BASE_STATE)
    s["streaming"] = False
    s.update(over)
    return s


def node(**over):
    n = dict(BASE_NODE)
    n.update(over)
    return n


def lines(out):
    return out.split("\n")


def header_line(out):
    for ln in lines(out):
        if ln.startswith("nodes="):
            return ln
    return None


def top_lines(out):
    """Lines before the `nodes=` header (the fixed first line + new top lines)."""
    res = []
    for ln in lines(out):
        if ln.startswith("nodes="):
            break
        res.append(ln)
    return res


def node_line(out, idx):
    marker = f"[{idx}]"
    for ln in lines(out):
        if marker in ln:
            return ln
    return None


# ---------------------------------------------------------------------------
# N1 — per-node drift glyph
# ---------------------------------------------------------------------------

# CS1
def test_drift_truthy_appends_delta_last():
    out = render(state(nodes=[node(drift=True)]))
    ln = node_line(out, 0)
    assert ln is not None
    assert ln.rstrip().endswith("Δ")  # Δ is the last non-space content


# CS2
def test_drift_false_no_glyph():
    out = render(state(nodes=[node(drift=False)]))
    assert "Δ" not in out


# CS3
def test_drift_absent_no_glyph():
    out = render(state(nodes=[node()]))  # no drift key at all
    assert "Δ" not in out


# CS4
def test_drift_after_weight_suffix():
    # Weight produces the `w=<n>%` suffix; drift's Δ must come after it.
    out = render(state(nodes=[node(weight_pct=50, drift=True)]))
    ln = node_line(out, 0)
    assert ln is not None
    assert "w=" in ln, "expected a weight suffix on the node line"
    assert ln.index("w=") < ln.index("Δ")
    assert ln.rstrip().endswith("Δ")


# ---------------------------------------------------------------------------
# N2 — context_gauge line
# ---------------------------------------------------------------------------

# CS5
def test_gauge_numeric_pct_surfaced():
    out = render(state(context_gauge={"pct": 42, "approximate": False}, nodes=[node()]))
    top = top_lines(out)
    assert len(top) == 2  # fixed first line + exactly one gauge line
    gauge = top[1]
    assert "42" in gauge
    assert "%" in gauge


# CS6
def test_gauge_pct_zero_surfaced():
    out = render(state(context_gauge={"pct": 0, "approximate": False}, nodes=[node()]))
    gauge = top_lines(out)[1]
    assert "0" in gauge
    assert "%" in gauge


# CS7
def test_gauge_pct_none_placeholder():
    out = render(state(context_gauge={"pct": None, "approximate": False}, nodes=[node()]))
    top = top_lines(out)
    assert len(top) == 2
    gauge = top[1]
    assert gauge.strip() != ""          # still present, non-blank
    assert "None" not in gauge          # not the literal None
    assert "[]" not in gauge            # not a bare []


# CS8 + CS9
def test_gauge_approximate_marker_toggles():
    approx = render(state(context_gauge={"pct": 42, "approximate": True}, nodes=[node()]))
    exact = render(state(context_gauge={"pct": 42, "approximate": False}, nodes=[node()]))
    assert "~" in top_lines(approx)[1]
    assert "~" not in top_lines(exact)[1]


# CS10
def test_gauge_absent_no_line():
    out = render(state(nodes=[node()]))
    assert len(top_lines(out)) == 1  # only the fixed first line before the header


# CS11
def test_gauge_before_header():
    out = render(state(context_gauge={"pct": 42, "approximate": False}, nodes=[node()]))
    ls = lines(out)
    gauge_idx = next(i for i, ln in enumerate(ls) if "42" in ln and "%" in ln)
    header_idx = next(i for i, ln in enumerate(ls) if ln.startswith("nodes="))
    assert gauge_idx < header_idx


# ---------------------------------------------------------------------------
# N3 — range_selection segment on the nodes header
# ---------------------------------------------------------------------------

# CS12
def test_range_segment_exact():
    out = render(state(range_selection=[0, 1, 2],
                       nodes=[node(), node(index=1), node(index=2)]))
    assert "range=[0,1,2]" in header_line(out)


# CS13
def test_range_includes_zero():
    out = render(state(range_selection=[0], nodes=[node()]))
    assert "range=[0]" in header_line(out)


# CS14
def test_range_empty_no_segment():
    out = render(state(range_selection=[], nodes=[node()]))
    assert "range=" not in out


# CS15
def test_range_absent_no_segment():
    out = render(state(nodes=[node()]))
    assert "range=" not in out


# CS16
def test_range_and_selected_coexist():
    out = render(state(range_selection=[0], selected_index=0, nodes=[node(selected=True)]))
    hdr = header_line(out)
    assert "range=[0]" in hdr
    assert "selected=" in hdr


# ---------------------------------------------------------------------------
# N4 — deep_dive.breadcrumb line
# ---------------------------------------------------------------------------

# CS17
def test_breadcrumb_surfaces_labels_in_order():
    crumb = ["Chat", "K a1b2", "Diff a1b2"]
    out = render(state(deep_dive={"breadcrumb": crumb}, nodes=[node()]))
    top = top_lines(out)
    assert len(top) == 2  # fixed first line + exactly one breadcrumb line
    line = top[1]
    for label in crumb:
        assert label in line
    assert line.index("Chat") < line.index("K a1b2") < line.index("Diff a1b2")


# CS18 + CS19 + CS20
def test_breadcrumb_noise_cases_no_line():
    for over in (
        {"deep_dive": {"breadcrumb": ["Chat"]}},   # lone root
        {"deep_dive": {"breadcrumb": []}},          # empty
        {"deep_dive": {}},                          # breadcrumb absent
        {},                                          # deep_dive absent
    ):
        out = render(state(nodes=[node()], **over))
        assert len(top_lines(out)) == 1, over


# ---------------------------------------------------------------------------
# N5 — diff_view line
# ---------------------------------------------------------------------------

def _diff_line(out):
    top = top_lines(out)
    assert len(top) == 2, f"expected exactly one diff line, got {top}"
    return top[1]


# CS21
def test_diff_open_surfaces_region_count():
    regions = [{"left": [1, 2], "right": [3, 4]}, {"left": [5], "right": [6]}]
    out = render(state(
        diff_view={"open": True, "regions": regions, "warning": False, "drill": None},
        nodes=[node()],
    ))
    assert "2" in _diff_line(out)


# CS22
def test_diff_empty_regions_count_zero():
    out = render(state(
        diff_view={"open": True, "regions": [], "warning": False, "drill": None},
        nodes=[node()],
    ))
    assert "0" in _diff_line(out)


# CS23
def test_diff_closed_and_absent_no_line():
    closed = render(state(
        diff_view={"open": False, "regions": [], "warning": False, "drill": None},
        nodes=[node()],
    ))
    absent = render(state(nodes=[node()]))
    assert len(top_lines(closed)) == 1
    assert len(top_lines(absent)) == 1


# CS24
def test_diff_warning_indicator_toggles():
    regions = [{"left": [1], "right": [2]}]
    warn_on = render(state(
        diff_view={"open": True, "regions": regions, "warning": True, "drill": None},
        nodes=[node()],
    ))
    warn_off = render(state(
        diff_view={"open": True, "regions": regions, "warning": False, "drill": None},
        nodes=[node()],
    ))
    assert "warn" in _diff_line(warn_on).lower()
    assert "warn" not in _diff_line(warn_off).lower()


# CS25
def test_diff_drill_indicator_toggles():
    regions = [{"left": [1], "right": [2]}]
    drill_on = render(state(
        diff_view={"open": True, "regions": regions, "warning": False,
                   "drill": {"region": 0}},
        nodes=[node()],
    ))
    drill_off = render(state(
        diff_view={"open": True, "regions": regions, "warning": False, "drill": None},
        nodes=[node()],
    ))
    assert "drill" in _diff_line(drill_on).lower()
    assert "drill" not in _diff_line(drill_off).lower()


# ---------------------------------------------------------------------------
# Purity / tolerance
# ---------------------------------------------------------------------------

# CS26
def test_render_tolerates_all_new_keys_absent():
    out = render(state(nodes=[node()]))  # none of the five new keys present
    assert isinstance(out, str)
    assert "Δ" not in out
    assert "range=" not in out
