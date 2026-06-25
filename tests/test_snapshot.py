"""Tests for tools.agent.snapshot.render.

The oracle for every assertion in this file traces to tests/specs/snapshot.md
(the adjudicated behavioral contract), never to the implementation. These tests
were authored code-blind: assertions reflect what render() SHOULD do, not what
any particular implementation happens to do.

render(state: dict) -> str is pure and returns a newline-joined multi-line
string. It consumes plain dicts, so we build dict literals directly rather than
using conftest fixtures.
"""

import copy

from tools.agent.snapshot import render

# --- local helpers (no conftest fixtures: render consumes plain dicts) ---


def state(**over):
    base = {"mode": "chat", "model": "gpt-4o", "focus": "input"}
    base.update(over)
    return base


def node(**over):
    base = {
        "index": 0,
        "role": "user",
        "content": "hello world",
        "selected": False,
        "truncated": False,
    }
    base.update(over)
    return base


def lines(out):
    return out.split("\n")


def first_line(out):
    return lines(out)[0]


def detail_line(out, view_token):
    """Locate the detail line as the line carrying the `view` value.

    Never located by absolute index. `view_token` is the view string set in the
    test state (e.g. "diff", "context"); the detail line is the unique line that
    contains it.
    """
    matches = [ln for ln in lines(out) if view_token in ln]
    assert len(matches) >= 1, f"no detail line containing {view_token!r} in:\n{out}"
    return matches[0]


def node_line(out, index):
    """Locate a per-node line by the `[<index>]` token it carries."""
    token = f"[{index}]"
    matches = [ln for ln in lines(out) if ln[2:].startswith(token)]
    assert len(matches) == 1, f"expected one node line with {token!r} in:\n{out}"
    return matches[0]


# --- C1: first line exact, always emitted ---


def test_first_line_exact_format():
    # C1
    out = render(state(streaming=False))
    assert first_line(out) == "mode=chat focus=input streaming=no model=gpt-4o"


# --- C2: streaming yes/no, never True/False ---


def test_streaming_true_renders_yes():
    # C2
    out = render(state(streaming=True))
    assert "streaming=yes" in first_line(out)
    assert "streaming=True" not in first_line(out)


def test_streaming_false_renders_no():
    # C2
    out = render(state(streaming=False))
    assert "streaming=no" in first_line(out)
    assert "streaming=False" not in first_line(out)


# --- C3: focus segment ---


def test_focus_nodes_in_first_line():
    # C3a
    out = render(state(focus="nodes", streaming=False))
    assert "focus=nodes" in first_line(out)


def test_focus_absent_still_has_focus_segment():
    # C3b — build WITHOUT focus key, do not use helper default
    out = render({"mode": "chat", "model": "gpt-4o", "streaming": False})
    fl = first_line(out)
    assert "focus=" in fl
    assert "focus=None" in fl
    # four key=value segments
    segments = [seg for seg in fl.split() if "=" in seg]
    assert len(segments) == 4


# --- C4: title line iff truthy ---


def test_title_truthy_present():
    # C4a
    out = render(state(streaming=False, title="Refactoring plan"))
    assert "Refactoring plan" in out


def test_c4_empty_title_no_line():
    # C4(b) — empty title produces no title line
    out = render(state(title=""))
    assert 'title="' not in out


def test_title_absent_no_line():
    # C4c
    out = render(state(streaming=False))
    assert "title=" not in out


# --- C5: input line iff input non-empty OR menu open ---


def test_input_nonempty_no_menu_present():
    # C5a
    out = render(state(streaming=False, input="explain this"))
    assert "explain this" in out


def test_input_empty_no_menu_absent():
    # C5b
    out = render(state(streaming=False, input=""))
    assert "input=" not in out


def test_input_empty_with_menu_present():
    # C5c
    out = render(
        state(
            streaming=False,
            input="",
            command_menu={"selected": "add-context", "count": 2, "occluded": False},
        )
    )
    # menu open forces the input line; menu selection is surfaced
    assert "add-context" in out


def test_input_absent_with_menu_present():
    # C5d
    s = {
        "mode": "chat",
        "model": "gpt-4o",
        "focus": "input",
        "streaming": False,
        "command_menu": {"selected": "open-file", "count": 1, "occluded": False},
    }
    out = render(s)
    assert "open-file" in out


# --- C6: footer line iff truthy ---


def test_footer_truthy_present():
    # C6a
    out = render(state(streaming=False, footer="3 changes pending"))
    assert "3 changes pending" in out


def test_footer_empty_absent():
    # C6b
    out = render(state(streaming=False, footer=""))
    assert "footer=" not in out


def test_footer_absent_absent():
    # C6c
    out = render(state(streaming=False))
    assert "footer=" not in out


# --- C7: detail line iff non-empty dict ---


def test_detail_nonempty_one_line():
    # C7a
    out = render(
        state(
            streaming=False,
            detail={"view": "diff", "node_index": 2, "pane_mode": "none", "locked": True},
        )
    )
    dl = detail_line(out, "diff")
    assert "diff" in dl and "2" in dl
    assert len([ln for ln in lines(out) if "diff" in ln]) == 1


def test_detail_empty_dict_no_line():
    # C7b
    out = render(state(streaming=False, detail={}))
    assert "diff" not in out


def test_detail_absent_no_line():
    # C7c
    out = render(state(streaming=False))
    # no view tokens present
    assert "diff" not in out and "context" not in out


# --- C8: colors line iff non-empty dict ---


def test_colors_nonempty_present():
    # C8a
    out = render(state(streaming=False, colors={"user": "cyan", "assistant": "green"}))
    assert "user" in out and "cyan" in out
    assert "assistant" in out and "green" in out


def test_colors_empty_absent():
    # C8b
    out = render(state(streaming=False, colors={}))
    assert "cyan" not in out and "green" not in out


def test_colors_absent_absent():
    # C8c
    out = render(state(streaming=False))
    assert "colors" not in out.lower()


# --- C9: nodes header always present ---


def test_nodes_header_count_three():
    # C9a
    nodes = [
        node(index=0, role="user", content="alpha"),
        node(index=1, role="assistant", content="beta"),
        node(index=2, role="user", content="gamma"),
    ]
    out = render(state(streaming=False, nodes=nodes))
    assert "nodes=3" in out


def test_nodes_header_count_zero_empty():
    # C9b
    out = render(state(streaming=False, nodes=[]))
    assert "nodes=0" in out


def test_nodes_header_count_zero_absent():
    # C9c
    out = render(state(streaming=False))
    assert "nodes=0" in out


# --- C10: header selected=[<i>] iff selected_index set ---


def test_selected_index_set_in_header():
    # C10a
    nodes = [node(index=0, content="a"), node(index=1, content="b")]
    out = render(state(streaming=False, nodes=nodes, selected_index=1))
    assert "selected=[1]" in out


def test_selected_index_none_no_segment():
    # C10b
    out = render(state(streaming=False, nodes=[], selected_index=None))
    assert "selected=" not in out


def test_selected_index_absent_no_segment():
    # C10c
    out = render(state(streaming=False, nodes=[]))
    assert "selected=" not in out


# --- C11: node leading markers two fixed chars ---


def test_node_leading_markers_default():
    # C11
    out = render(
        state(
            streaming=False,
            nodes=[
                node(index=0, role="user", content="hello world", selected=False, truncated=False)
            ],
        )
    )
    ln = node_line(out, 0)
    # two spaces (no selection, no truncation) then [0] user then hello world
    assert ln.startswith("  [0] user")
    assert "hello world" in ln


# --- C12: selection marker char[0] ---


def test_selection_marker_char0():
    # C12
    nodes = [
        node(index=0, role="user", content="selected one", selected=True, truncated=False),
        node(index=1, role="assistant", content="not selected", selected=False, truncated=False),
    ]
    out = render(state(streaming=False, nodes=nodes))
    a = node_line(out, 0)
    b = node_line(out, 1)
    assert a[0] == "*"
    assert b[0] == " "
    assert a[1] == " "
    assert b[1] == " "


# --- C13: truncation marker char[1] ---


def test_truncation_marker_char1():
    # C13
    nodes = [
        node(index=0, role="user", content="truncated one", selected=False, truncated=True),
        node(index=1, role="assistant", content="whole one", selected=False, truncated=False),
    ]
    out = render(state(streaming=False, nodes=nodes))
    a = node_line(out, 0)
    b = node_line(out, 1)
    assert a[1] == "~"
    assert b[1] == " "
    assert a[0] == " "
    assert b[0] == " "


# --- C14: both markers ---


def test_both_markers():
    # C14
    out = render(
        state(
            streaming=False,
            nodes=[node(index=5, role="user", content="both", selected=True, truncated=True)],
        )
    )
    ln = node_line(out, 5)
    assert ln.startswith("*~[5] user")


# --- C15: file suffix iff source_path ---


def test_file_suffix_present():
    # C15a
    out = render(
        state(
            streaming=False,
            nodes=[node(index=0, content="some content", source_path="src/app/main.py")],
        )
    )
    ln = node_line(out, 0)
    assert "  (file: src/app/main.py)" in ln


def test_file_suffix_absent():
    # C15b
    out = render(state(streaming=False, nodes=[node(index=0, content="some content")]))
    assert "(file:" not in out


# --- C16: weight suffix iff weight_pct ---


def test_weight_suffix_present():
    # C16a
    out = render(state(streaming=False, nodes=[node(index=0, content="weighted", weight_pct=42)]))
    ln = node_line(out, 0)
    assert "  w=42%" in ln


def test_weight_suffix_absent():
    # C16b
    out = render(state(streaming=False, nodes=[node(index=0, content="unweighted")]))
    assert "w=" not in out


# --- C17: both suffixes, file before weight ---


def test_both_suffixes_file_before_weight():
    # C17
    out = render(
        state(
            streaming=False,
            nodes=[node(index=0, content="speccy", source_path="docs/spec.md", weight_pct=7)],
        )
    )
    ln = node_line(out, 0)
    assert "(file: docs/spec.md)" in ln
    assert "w=7%" in ln
    assert ln.index("(file: docs/spec.md)") < ln.index("w=7%")


# --- C18: whitespace collapse ---


def test_whitespace_collapse():
    # C18
    out = render(
        state(streaming=False, nodes=[node(index=0, content="first line\n\tsecond   part")])
    )
    ln = node_line(out, 0)
    assert "first line second part" in ln


# --- C19: content 80 chars full ---


def test_content_80_chars_full():
    # C19
    content = "a" * 80
    out = render(state(streaming=False, nodes=[node(index=0, content=content)]))
    ln = node_line(out, 0)
    assert content in ln
    assert "…" not in ln  # no ellipsis
    # rendered content portion is the verbatim 80-char run
    assert ("a" * 80) in ln


# --- C20: content 81 chars truncated ---


def test_content_81_chars_truncated():
    # C20
    content = "a" * 81
    out = render(state(streaming=False, nodes=[node(index=0, content=content)]))
    ln = node_line(out, 0)
    # rendered content ends with a single ellipsis, prefix preserved
    rendered = ("a" * 79) + "…"
    assert rendered in ln
    # the full 81-char run must not appear unchanged
    assert ("a" * 81) not in ln
    # exactly one ellipsis char
    assert ln.count("…") == 1


# --- C21: empty/absent nodes → header lines only ---


def test_empty_nodes_no_per_node_lines():
    # C21a
    out = render(state(streaming=False, nodes=[]))
    assert "nodes=0" in out
    assert "[0]" not in out


def test_absent_nodes_no_per_node_lines():
    # C21b
    out = render(state(streaming=False))
    assert "nodes=0" in out
    assert "[0]" not in out


# --- C22: purity, no mutation ---


def test_purity_no_mutation():
    # C22
    s = state(
        streaming=True,
        title="Refactoring plan",
        input="explain this",
        footer="3 changes pending",
        command_menu={"selected": "add-context", "count": 3, "occluded": True},
        detail={
            "view": "context",
            "node_index": 2,
            "pane_mode": "browse",
            "highlighted_split": "left",
            "maximized_split": "editor",
            "locked": True,
            "splits_visible": ["tree", "preview"],
        },
        colors={"user": "cyan", "assistant": "green"},
        nodes=[
            node(
                index=0,
                role="user",
                content="hello world",
                selected=True,
                truncated=True,
                source_path="docs/spec.md",
                weight_pct=7,
            )
        ],
        selected_index=0,
    )
    before = copy.deepcopy(s)
    render(s)
    assert s == before


# --- C23: determinism ---


def test_determinism_byte_equal():
    # C23
    s1 = state(
        streaming=False,
        title="Refactoring plan",
        nodes=[node(index=0, role="user", content="hello world")],
        selected_index=0,
    )
    out_a = render(s1)
    out_b = render(s1)
    s2 = state(
        streaming=False,
        title="Refactoring plan",
        nodes=[node(index=0, role="user", content="hello world")],
        selected_index=0,
    )
    out_c = render(s2)
    assert out_a == out_b == out_c


# --- C24: line ordering ---


def test_line_ordering():
    # C24
    nodes = [
        node(index=0, role="user", content="alpha"),
        node(index=1, role="assistant", content="beta"),
        node(index=2, role="user", content="gamma"),
    ]
    out = render(
        state(
            streaming=False,
            title="Refactoring plan",
            input="explain this",
            footer="3 changes pending",
            detail={"view": "diff", "node_index": 2, "pane_mode": "none", "locked": False},
            colors={"user": "cyan"},
            nodes=nodes,
            selected_index=1,
        )
    )
    all_lines = lines(out)
    # first line is first
    assert all_lines[0] == "mode=chat focus=input streaming=no model=gpt-4o"
    # nodes header line index
    header_idx = next(i for i, ln in enumerate(all_lines) if "nodes=3" in ln)
    # optional lines appear before nodes header
    assert all_lines.index(next(ln for ln in all_lines if "Refactoring plan" in ln)) < header_idx
    assert all_lines.index(next(ln for ln in all_lines if "explain this" in ln)) < header_idx
    assert all_lines.index(next(ln for ln in all_lines if "3 changes pending" in ln)) < header_idx
    assert all_lines.index(next(ln for ln in all_lines if "diff" in ln)) < header_idx
    assert all_lines.index(next(ln for ln in all_lines if "cyan" in ln)) < header_idx
    # nodes header before per-node lines
    i0 = all_lines.index(node_line(out, 0))
    i1 = all_lines.index(node_line(out, 1))
    i2 = all_lines.index(node_line(out, 2))
    assert header_idx < i0
    # per-node lines in node order
    assert i0 < i1 < i2


# --- C25: menu selected surfaced ---


def test_menu_selected_surfaced():
    # C25
    out = render(
        state(
            streaming=False,
            input="some text",
            command_menu={"selected": "add-context", "count": 3, "occluded": False},
        )
    )
    assert "add-context" in out


# --- C26: menu count when int ---


def test_menu_count_int_surfaced():
    # C26
    out = render(
        state(
            streaming=False,
            input="filter",
            command_menu={"selected": "add-context", "count": 7, "occluded": False},
        )
    )
    # locate the menu segment line (the one carrying the selected command)
    menu_ln = next(ln for ln in lines(out) if "add-context" in ln)
    assert "7" in menu_ln


# --- C27: menu count omitted when None ---


def test_menu_count_none_omitted():
    # C27
    out = render(
        state(
            streaming=False,
            input="filter",
            command_menu={"selected": "open-file", "count": None, "occluded": False},
        )
    )
    menu_ln = next(ln for ln in lines(out) if "open-file" in ln)
    assert "open-file" in menu_ln
    assert "None" not in menu_ln


# --- C28: OCCLUDED present when occluded True + count int ---


def test_occluded_present_when_true_and_count():
    # C28
    out = render(
        state(
            streaming=False,
            input="filter",
            command_menu={"selected": "add-context", "count": 5, "occluded": True},
        )
    )
    menu_ln = next(ln for ln in lines(out) if "add-context" in ln)
    assert "occluded" in menu_ln.lower()


# --- C29: OCCLUDED absent when False ---


def test_occluded_absent_when_false():
    # C29
    out = render(
        state(
            streaming=False,
            input="filter",
            command_menu={"selected": "add-context", "count": 5, "occluded": False},
        )
    )
    menu_ln = next(ln for ln in lines(out) if "add-context" in ln)
    assert "occluded" not in menu_ln.lower()


# --- C47: OCCLUDED requires known count ---


def test_c47_occluded_requires_count():
    # C47/C28 — occluded indicator requires a count; with count=None nothing shows
    out = render(
        state(
            input="filter",
            command_menu={"selected": "open-file", "count": None, "occluded": True},
        )
    )
    assert "open-file" in out
    assert "occluded" not in out.lower()
    assert "None" not in out


# --- C30: detail view surfaced ---


def test_detail_view_surfaced():
    # C30
    out = render(
        state(
            streaming=False,
            detail={"view": "diff", "node_index": 0, "pane_mode": "none", "locked": False},
        )
    )
    assert len([ln for ln in lines(out) if "diff" in ln]) == 1


# --- C31: node index surfaced ---


def test_detail_node_index_surfaced():
    # C31
    out = render(
        state(
            streaming=False,
            detail={"view": "diff", "node_index": 3, "pane_mode": "none", "locked": False},
        )
    )
    dl = detail_line(out, "diff")
    assert "3" in dl


# --- C32: node index placeholder when None ---


def test_detail_node_index_none_placeholder():
    # C32
    out = render(
        state(
            streaming=False,
            detail={"view": "diff", "node_index": None, "pane_mode": "none", "locked": False},
        )
    )
    dl = detail_line(out, "diff")
    assert dl.strip() != ""
    assert "None" not in dl


# --- C33: browse surfaces highlighted ---


def test_browse_surfaces_highlighted():
    # C33
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "pane_mode": "browse",
                "highlighted_split": "left",
                "locked": False,
            },
        )
    )
    dl = detail_line(out, "browse")
    assert "left" in dl


# --- C34: browse no highlight placeholder ---


def test_browse_no_highlight_none_placeholder():
    # C34
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "pane_mode": "browse",
                "highlighted_split": None,
                "locked": False,
            },
        )
    )
    dl = detail_line(out, "browse")
    assert dl.strip() != ""
    assert "None" not in dl


def test_browse_no_highlight_empty_placeholder():
    # C34 (empty-string sub-case)
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "pane_mode": "browse",
                "highlighted_split": "",
                "locked": False,
            },
        )
    )
    dl = detail_line(out, "browse")
    assert dl.strip() != ""
    assert "None" not in dl


# --- C35: highlighted not surfaced outside browse ---


def test_highlighted_not_surfaced_maximized():
    # C35
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "pane_mode": "maximized",
                "highlighted_split": "highlightonly-zzz",
                "maximized_split": "editor",
                "locked": False,
            },
        )
    )
    assert "highlightonly-zzz" not in out


def test_highlighted_not_surfaced_none():
    # C35 (none sub-case)
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "pane_mode": "none",
                "highlighted_split": "highlightonly-zzz",
                "locked": False,
            },
        )
    )
    assert "highlightonly-zzz" not in out


# --- C36: maximized surfaces maximized split ---


def test_maximized_surfaces_split():
    # C36
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "pane_mode": "maximized",
                "maximized_split": "editor",
                "locked": False,
            },
        )
    )
    dl = detail_line(out, "maximized")
    assert "editor" in dl


# --- C37: maximized empty placeholder ---


def test_maximized_empty_placeholder():
    # C37
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "pane_mode": "maximized",
                "maximized_split": "",
                "locked": False,
            },
        )
    )
    dl = detail_line(out, "maximized")
    assert dl.strip() != ""
    assert "None" not in dl


def test_maximized_absent_split_placeholder():
    # C37 (absent sub-case)
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "pane_mode": "maximized",
                "locked": False,
            },
        )
    )
    dl = detail_line(out, "maximized")
    assert dl.strip() != ""
    assert "None" not in dl


# --- C38: maximized not surfaced outside maximized ---


def test_maximized_not_surfaced_browse():
    # C38
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "pane_mode": "browse",
                "highlighted_split": "left",
                "maximized_split": "maxonly-zzz",
                "locked": False,
            },
        )
    )
    assert "maxonly-zzz" not in out


def test_maximized_not_surfaced_none():
    # C38 (none sub-case)
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "pane_mode": "none",
                "maximized_split": "maxonly-zzz",
                "locked": False,
            },
        )
    )
    assert "maxonly-zzz" not in out


# --- C39: pane none surfaces neither ---


def test_pane_none_surfaces_neither():
    # C39
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "pane_mode": "none",
                "highlighted_split": "hsplit-zzz",
                "maximized_split": "msplit-zzz",
                "locked": False,
            },
        )
    )
    assert "hsplit-zzz" not in out
    assert "msplit-zzz" not in out
    # detail line still present
    assert detail_line(out, "diff")


def test_pane_absent_surfaces_neither():
    # C39 (absent sub-case)
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "highlighted_split": "hsplit-zzz",
                "maximized_split": "msplit-zzz",
                "locked": False,
            },
        )
    )
    assert "hsplit-zzz" not in out
    assert "msplit-zzz" not in out
    assert detail_line(out, "diff")


# --- C40: pane always surfaced ---


def test_pane_browse_surfaced():
    # C40a
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "pane_mode": "browse",
                "highlighted_split": "left",
                "locked": False,
            },
        )
    )
    dl = detail_line(out, "diff")
    assert "browse" in dl


def test_pane_absent_none_indicator():
    # C40b
    out = render(
        state(
            streaming=False,
            detail={"view": "diff", "node_index": 0, "locked": False},
        )
    )
    dl = detail_line(out, "diff")
    assert dl.strip() != ""
    assert "None" not in dl
    # neutral "none" indicator present
    assert "none" in dl.lower()


# --- C41: locked true ---


def test_locked_true_token():
    # C41
    out = render(
        state(
            streaming=False,
            detail={"view": "diff", "node_index": 0, "pane_mode": "none", "locked": True},
        )
    )
    dl = detail_line(out, "diff")
    assert "lock" in dl.lower()


# --- C42: locked false differs ---


def test_locked_false_differs_from_true():
    # C42
    base = {"view": "diff", "node_index": 0, "pane_mode": "none"}
    out_locked = render(state(streaming=False, detail={**base, "locked": True}))
    out_unlocked = render(state(streaming=False, detail={**base, "locked": False}))
    assert out_locked != out_unlocked
    # both surface a detail/status line carrying the view
    assert detail_line(out_locked, "diff")
    assert detail_line(out_unlocked, "diff")


# --- C43: context splits surfaced ---


def test_context_splits_surfaced():
    # C43
    out = render(
        state(
            streaming=False,
            detail={
                "view": "context",
                "node_index": 0,
                "pane_mode": "none",
                "splits_visible": ["tree", "preview"],
                "locked": False,
            },
        )
    )
    dl = detail_line(out, "context")
    assert "tree" in dl
    assert "preview" in dl


# --- C44: context no splits placeholder ---


def test_context_no_splits_placeholder():
    # C44
    out = render(
        state(
            streaming=False,
            detail={
                "view": "context",
                "node_index": 0,
                "pane_mode": "none",
                "splits_visible": [],
                "locked": False,
            },
        )
    )
    dl = detail_line(out, "context")
    assert dl.strip() != ""
    assert "None" not in dl
    assert "[]" not in dl


# --- C45: splits not surfaced for non-context ---


def test_splits_not_surfaced_non_context():
    # C45
    out = render(
        state(
            streaming=False,
            detail={
                "view": "diff",
                "node_index": 0,
                "pane_mode": "none",
                "splits_visible": ["splitvis-zzz"],
                "locked": False,
            },
        )
    )
    assert "splitvis-zzz" not in out


# --- C46: all color pairs ---


def test_all_color_pairs_surfaced():
    # C46
    colors = {"selected": "cyan", "added": "green", "removed": "red"}
    out = render(state(streaming=False, colors=colors))
    for role, color in colors.items():
        assert role in out
        assert color in out


# C5e
def test_input_value_kept_with_menu():
    out = render(
        state(
            input="filter text",
            command_menu={"selected": "add-context", "count": 3, "occluded": False},
        )
    )
    input_line = next(ln for ln in lines(out) if "add-context" in ln)
    assert "filter text" in input_line
    assert "add-context" in input_line


# C5f
def test_no_input_line_when_absent_no_menu():
    out = render(state())
    assert "input=" not in out


# C5g
def test_absent_input_not_none_with_menu():
    out = render(
        state(
            command_menu={"selected": "open-file", "count": 1, "occluded": False},
        )
    )
    input_line = next(ln for ln in lines(out) if "open-file" in ln)
    assert "None" not in input_line


# C28
def test_occluded_keeps_count():
    out = render(
        state(
            input="filter text",
            command_menu={"selected": "add-context", "count": 5, "occluded": True},
        )
    )
    menu_line = next(ln for ln in lines(out) if "add-context" in ln)
    assert "5" in menu_line
    assert "occluded" in menu_line.lower()


# C11b
def test_bare_node_no_trailing_suffix():
    out = render(state(nodes=[node(index=0, role="user", content="hello world")]))
    assert node_line(out, 0).endswith("hello world")


def test_node_missing_content_equals_empty():
    # C48: absent `content` key renders EXACTLY THE SAME as content == "",
    # never crashes, never invents placeholder text.
    absent = state(nodes=[{"index": 0, "role": "user"}])
    empty = state(nodes=[node(index=0, role="user", content="")])

    out_absent = render(absent)
    out_empty = render(empty)

    assert out_absent == out_empty


# C49
def test_context_missing_splits_placeholder():
    out = render(
        state(
            detail={"view": "context", "node_index": 0, "pane_mode": "none", "locked": False},
        )
    )
    detail_line = next(ln for ln in lines(out) if "context" in ln)
    assert detail_line.strip() != ""
    assert "None" not in detail_line


# C50 — a weight of zero is a real weight and is surfaced
def test_c50_zero_weight_is_surfaced():
    out = render(state(nodes=[node(index=0, weight_pct=0)], selected_index=0))
    line = node_line(out, 0)
    assert "w=0%" in line


# C51 — a detail node index of zero is a bound node, not the unbound placeholder
def test_c51_detail_node_index_zero_is_bound():
    out = render(
        state(detail={"view": "diff", "node_index": 0, "pane_mode": "none", "locked": False})
    )
    line = detail_line(out, "diff")
    assert "[0]" in line


# C52 — a selected index of zero is a real selection
def test_c52_selected_index_zero_is_real_selection():
    out = render(state(nodes=[node(index=0)], selected_index=0))
    header = next(line for line in lines(out) if line.startswith("nodes="))
    assert "selected=[0]" in header


# C53 — an unrecognized pane mode surfaces its own value and neither split field
def test_c53_unknown_pane_mode_surfaces_value_no_split_fields():
    out = render(
        state(
            detail={
                "view": "diff",
                "node_index": 1,
                "pane_mode": "split",
                "highlighted_split": "HSPLIT-zzz",
                "maximized_split": "MSPLIT-zzz",
                "locked": False,
            }
        )
    )
    line = detail_line(out, "diff")
    assert "split" in line
    assert "HSPLIT-zzz" not in out
    assert "MSPLIT-zzz" not in out
