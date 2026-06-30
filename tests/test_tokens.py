"""Behavioral tests for ctx.core.tokens.

Authored code-blind from the contract in tests/specs/tokens.md. Each test cites the
contract item (C#) it exercises. Assertions trace to contract Expects: relationships,
signs, parallelism, ratios, and tolerances — never pinned tokenizer magic numbers.
"""

import inspect

from ctx.core import tokens

KNOWN_MODEL = "gpt-4"
UNKNOWN_MODEL = "totally/nonexistent-model-xyz"


# --- count_messages -------------------------------------------------------------


def test_count_messages_empty_is_zero():
    # C1: an empty conversation counts as 0.
    assert tokens.count_messages([], KNOWN_MODEL) == 0


def test_count_messages_nonempty_is_positive():
    # C2: real content yields a positive int.
    messages = [{"role": "user", "content": "Summarize the quarterly revenue report."}]
    result = tokens.count_messages(messages, KNOWN_MODEL)
    assert isinstance(result, int)
    assert result > 0


def test_count_messages_monotonic_in_content_length():
    # C3: more content counts strictly more than less; both >= the empty count (0).
    short = [{"role": "user", "content": "Hi there."}]
    long = [
        {
            "role": "user",
            "content": (
                "Please walk me through the entire architecture of the context "
                "budgeting subsystem, including the two denominators, the calibration "
                "anchor, and how the header gauge differs from the per-node weights."
            ),
        }
    ]
    short_count = tokens.count_messages(short, KNOWN_MODEL)
    long_count = tokens.count_messages(long, KNOWN_MODEL)
    assert long_count > short_count
    assert short_count >= 0


# --- per_node_tokens ------------------------------------------------------------


def test_per_node_tokens_parallel_to_input(make_node, stub_loader):
    # C4: one int per input node, same order/length.
    nodes = [
        make_node(role="user", content="What is the budget for Q3?"),
        make_node(role="assistant", content="The Q3 budget is finalized."),
        make_node(role="user", content="Thanks, send the breakdown."),
    ]
    result = tokens.per_node_tokens(nodes, KNOWN_MODEL, stub_loader({}))
    assert len(result) == len(nodes)
    assert all(isinstance(x, int) for x in result)


def test_per_node_tokens_nonempty_model_bound_is_positive(make_node, stub_loader):
    # C5: a non-empty goes_to_model node contributes > 0.
    nodes = [make_node(role="user", content="Generate a migration plan for the DB.")]
    result = tokens.per_node_tokens(nodes, KNOWN_MODEL, stub_loader({}))
    assert result[0] > 0


def test_per_node_tokens_system_breadcrumb_is_zero(make_node, stub_loader):
    # C6: a system breadcrumb (not goes_to_model) contributes 0.
    nodes = [make_node(role="system", node_type="system", content="run started")]
    result = tokens.per_node_tokens(nodes, KNOWN_MODEL, stub_loader({}))
    assert result[0] == 0


def test_per_node_tokens_empty_model_bound_is_zero(make_node, stub_loader):
    # C7: a model-bound node that renders to nothing contributes 0.
    nodes = [make_node(role="user", content="")]
    result = tokens.per_node_tokens(nodes, KNOWN_MODEL, stub_loader({}))
    assert result[0] == 0


def test_per_node_tokens_context_node_counts_resolved_body(make_node, stub_loader):
    # C8: a context node is counted by its loaded file body; a large body dominates a
    # tiny user message.
    big_body = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 200
    loader = stub_loader({"report.txt": big_body})
    tiny_user = make_node(role="user", content="ok")
    context_node = make_node(
        role="context", node_type="context", meta={"source_path": "report.txt"}
    )
    nodes = [tiny_user, context_node]
    result = tokens.per_node_tokens(nodes, KNOWN_MODEL, loader)
    tiny_count, context_count = result
    assert context_count > 0
    assert context_count > tiny_count


# --- weight_pct -----------------------------------------------------------------


def test_weight_pct_parallel_to_input(make_node, stub_loader):
    # C9: one entry (int | None) per input node, in order.
    nodes = [
        make_node(role="user", content="Outline the deployment steps."),
        make_node(role="assistant", content="Here are the deployment steps in order."),
    ]
    result = tokens.weight_pct(
        nodes, KNOWN_MODEL, stub_loader({}), "context", None
    )
    assert len(result) == len(nodes)
    assert all(x is None or isinstance(x, int) for x in result)


def test_weight_pct_zero_token_node_is_none_both_bases(make_node, stub_loader):
    # C10: a zero-token node (system breadcrumb) maps to None under both bases; the
    # model-bound nodes stay non-None.
    window = tokens.model_window(KNOWN_MODEL)
    nodes = [
        make_node(role="system", node_type="system", content="boot"),
        make_node(role="user", content="Explain the calibration anchor in detail."),
        make_node(role="assistant", content="The calibration anchor is a ratio."),
    ]
    loader = stub_loader({})

    ctx_weights = tokens.weight_pct(nodes, KNOWN_MODEL, loader, "context", None)
    win_weights = tokens.weight_pct(nodes, KNOWN_MODEL, loader, "window", window)

    # breadcrumb is first
    assert ctx_weights[0] is None
    assert win_weights[0] is None
    # model-bound nodes are non-None ints under both bases
    assert all(isinstance(x, int) for x in ctx_weights[1:])
    assert all(isinstance(x, int) for x in win_weights[1:])


def test_weight_pct_context_basis_sums_to_about_100(make_node, stub_loader):
    # C11: context-basis non-None entries sum to ~100 (tolerance 95..105 for a 3-node
    # conversation of independently-rounded ints).
    nodes = [
        make_node(role="user", content="Draft a release announcement for v2."),
        make_node(
            role="assistant",
            content="Here is a draft release announcement covering the new features.",
        ),
        make_node(role="user", content="Make it shorter and add a call to action."),
    ]
    weights = tokens.weight_pct(nodes, KNOWN_MODEL, stub_loader({}), "context", None)
    total = sum(w for w in weights if w is not None)
    assert 95 <= total <= 105


def test_weight_pct_context_basis_all_zero_is_all_none(make_node, stub_loader):
    # C12: when the total local estimate is 0 (only a breadcrumb), every entry is None
    # and no ZeroDivisionError is raised.
    nodes = [
        make_node(role="system", node_type="system", content="session header"),
    ]
    weights = tokens.weight_pct(nodes, KNOWN_MODEL, stub_loader({}), "context", None)
    assert weights == [None]


def test_weight_pct_window_basis_each_under_100(make_node, stub_loader):
    # C13: window-basis entries for a small conversation are each < 100.
    window = tokens.model_window(KNOWN_MODEL)
    nodes = [
        make_node(role="user", content="What is the status of the rollout?"),
        make_node(role="assistant", content="The rollout is at 80 percent."),
    ]
    weights = tokens.weight_pct(nodes, KNOWN_MODEL, stub_loader({}), "window", window)
    for w in weights:
        if w is not None:
            assert w < 100


def test_weight_pct_window_sum_under_context_sum(make_node, stub_loader):
    # C14: window-basis non-None values do not sum to 100; they sum well under it and
    # strictly under the context-basis sum for the same conversation.
    window = tokens.model_window(KNOWN_MODEL)
    nodes = [
        make_node(role="user", content="Compare the two pricing tiers for me."),
        make_node(
            role="assistant",
            content="Tier one is cheaper but limited; tier two is full-featured.",
        ),
    ]
    loader = stub_loader({})
    win_weights = tokens.weight_pct(nodes, KNOWN_MODEL, loader, "window", window)
    ctx_weights = tokens.weight_pct(nodes, KNOWN_MODEL, loader, "context", None)

    win_sum = sum(w for w in win_weights if w is not None)
    ctx_sum = sum(w for w in ctx_weights if w is not None)
    assert win_sum < 100
    assert win_sum < ctx_sum


def test_weight_pct_window_none_denominator_all_none(make_node, stub_loader):
    # C15: window-basis with max_input_tokens None → every entry None, no raise.
    nodes = [
        make_node(role="user", content="Anything works here for the denominator test."),
        make_node(role="assistant", content="Acknowledged."),
    ]
    weights = tokens.weight_pct(nodes, KNOWN_MODEL, stub_loader({}), "window", None)
    assert weights == [None, None]


def test_weight_pct_window_zero_denominator_all_none(make_node, stub_loader):
    # C16: window-basis with max_input_tokens 0 → every entry None, no ZeroDivision.
    nodes = [
        make_node(role="user", content="Zero window denominator test message."),
        make_node(role="assistant", content="Acknowledged."),
    ]
    weights = tokens.weight_pct(nodes, KNOWN_MODEL, stub_loader({}), "window", 0)
    assert weights == [None, None]


def test_weight_pct_takes_no_calibration_and_is_deterministic(make_node, stub_loader):
    # C17: the per-node column is purely local — the signature has no calibration
    # parameter, and identical inputs always produce identical output.
    sig = inspect.signature(tokens.weight_pct)
    assert "calibration" not in sig.parameters

    nodes = [
        make_node(role="user", content="Determinism check message one."),
        make_node(role="assistant", content="Determinism check reply two."),
    ]
    loader = stub_loader({})
    first = tokens.weight_pct(nodes, KNOWN_MODEL, loader, "context", None)
    second = tokens.weight_pct(nodes, KNOWN_MODEL, loader, "context", None)
    assert first == second


# --- gauge ----------------------------------------------------------------------


def test_gauge_approximate_true_when_no_calibration():
    # C18: approximate is True when calibration is None.
    _pct, approximate = tokens.gauge(500, 8000, None)
    assert approximate is True


def test_gauge_approximate_false_when_calibration_supplied():
    # C19: approximate is False once a calibration float is supplied.
    _pct, approximate = tokens.gauge(500, 8000, 1.3)
    assert approximate is False


def test_gauge_calibration_scales_pct_used():
    # C20: calibration 2.0 roughly doubles pct_used vs None (strictly greater, and
    # within ±2 points of 2x).
    local_total = 1000
    window = 8000
    raw_pct, _ = tokens.gauge(local_total, window, None)
    cal_pct, _ = tokens.gauge(local_total, window, 2.0)
    assert cal_pct > raw_pct
    assert abs(cal_pct - 2 * raw_pct) <= 2


def test_gauge_unknown_window_is_none_no_raise():
    # C21: max_input_tokens None → pct_used None, no exception; approximate follows C18.
    pct, approximate = tokens.gauge(1234, None, None)
    assert pct is None
    assert approximate is True


def test_gauge_pct_used_not_clamped_above_100():
    # C22: local_total exceeding the window reports above 100 (not clamped).
    pct, _ = tokens.gauge(16000, 8000, None)
    assert pct is not None
    assert pct > 100


def test_gauge_pct_used_monotonic_in_local_total():
    # C23: bigger local_total → bigger pct_used for a fixed window+calibration.
    window = 8000
    small_pct, _ = tokens.gauge(1000, window, None)
    large_pct, _ = tokens.gauge(4000, window, None)
    assert large_pct > small_pct


# --- model_window ---------------------------------------------------------------


def test_model_window_known_model_positive_int():
    # C24: a known model returns a positive int (exact value not pinned).
    result = tokens.model_window(KNOWN_MODEL)
    assert isinstance(result, int)
    assert result > 0


def test_model_window_unknown_model_none_no_raise():
    # C25: an unknown model degrades to None and never raises.
    assert tokens.model_window(UNKNOWN_MODEL) is None
