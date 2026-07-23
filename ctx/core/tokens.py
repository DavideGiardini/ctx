"""Framework-free token accounting for the context-budget UI.

Two denominators, by design (the per-node column and the header gauge answer
different questions):

* **Per-node weight** is a *local, provider-agnostic ratio* — each node's local
  token estimate over a denominator (the conversation total, or the model
  window). Because every node is measured with the *same* local tokenizer, the
  tokenizer's scale factor cancels in the ratio, so the percentage is robust even
  when the local estimate is only approximate for the active provider's model.
* **The header gauge** is an *absolute* figure: tokens used over the model's input
  window. It is sharpened by a provider's exact ``usage`` when one is available
  (passed in as ``calibration``) and otherwise reported from the local estimate
  alone, flagged ``approximate``.

This module is pure: it performs no I/O of its own and holds no state. File
contents reach it through the injected ``read_file`` loader that ``build_context``
already uses, and all token counting funnels through litellm's ``token_counter``
(the single home of the tiktoken fallback) and ``get_model_info``.
"""

from collections.abc import Callable
from typing import Literal

import litellm

from ctx.core.context import build_context
from ctx.models.nodes import Node

Basis = Literal["context", "window"]


def count_messages(messages: list[dict], model: str) -> int:
    """Local token count of rendered LLM ``messages`` for ``model``.

    Wraps litellm's ``token_counter`` — the ONE place the tiktoken fallback
    lives. ``messages`` is the shape ``build_context`` produces (role/content
    dicts). An empty list counts as ``0``. Provider-agnostic: for models litellm
    bundles a native tokenizer for the count is exact, otherwise it is an
    approximation via tiktoken; callers must not assume exactness.
    """
    if not messages:
        return 0
    return litellm.token_counter(model=model, messages=messages)


def per_node_tokens(
    nodes: list[Node], model: str, read_file: Callable[[str], str]
) -> list[int]:
    """Per-node local token estimate, message-framed, one int per input node.

    Each node is rendered *in isolation* via ``build_context([node], read_file)``
    and counted with ``count_messages`` — so a node's own message framing is
    included and a context node is counted by its *content-on-node* model-facing
    body (the import snapshot/extract). The result list is parallel to ``nodes``.

    A node that does not reach the model (``not node.goes_to_model()`` — notably a
    ``system`` breadcrumb) contributes ``0``, as does a model-bound node that
    renders to nothing (e.g. empty content). Every non-empty ``goes_to_model()``
    node contributes a positive count.
    """
    return [
        count_messages(build_context([node], read_file), model) for node in nodes
    ]


def weight_pct(
    nodes: list[Node],
    model: str,
    read_file: Callable[[str], str],
    basis: Basis,
    max_input_tokens: int | None,
) -> list[int | None]:
    """Per-node weight percentages, one entry per input node (``None`` = no weight).

    Built from ``per_node_tokens``. A node whose local estimate is ``0`` (it does
    not reach the model, or renders empty) has no weight to show and maps to
    ``None``; every other node maps to a rounded integer percentage.

    The denominator depends on ``basis``:

    * ``"context"`` — denominator is the sum of all nodes' local estimates, so the
      non-``None`` percentages answer "what share of *this conversation* is this
      node" and sum to ~100 (modulo integer rounding). If that sum is ``0`` every
      entry is ``None``.
    * ``"window"`` — denominator is ``max_input_tokens``, so each percentage
      answers "what share of the *model's whole input window* is this node". The
      per-node values do not sum to 100 (the conversation rarely fills the
      window). If ``max_input_tokens`` is ``None`` (or ``0``) every entry is
      ``None``.

    The percentage is provider-agnostic and never carries a calibration factor:
    the local tokenizer's scale cancels in the ratio, so the column is stable
    regardless of any provider ``usage`` anchor.
    """
    per_node = per_node_tokens(nodes, model, read_file)

    if basis == "context":
        denominator: int | None = sum(per_node)
    else:
        denominator = max_input_tokens

    if not denominator:  # None or 0 → no usable denominator
        return [None] * len(per_node)

    return [round(100 * tok / denominator) if tok else None for tok in per_node]


def gauge(
    local_total: int,
    max_input_tokens: int | None,
    calibration: float | None,
) -> tuple[int | None, bool]:
    """Header context-window gauge: ``(pct_used, approximate)``.

    ``local_total`` is the local token estimate of the whole context just built.
    When ``calibration`` is provided (a ``provider_usage / local_estimate`` ratio
    measured from a real turn) the absolute total is scaled by it to track the
    provider's own tokenizer; when it is ``None`` the raw local estimate is used.

    ``pct_used`` is the (rounded) percentage of ``max_input_tokens`` consumed; it
    is **not** clamped, so a context larger than the window reports above 100. When
    ``max_input_tokens`` is ``None`` (or ``0``) the window is unknown and
    ``pct_used`` is ``None`` (the UI degrades to ``--%``).

    ``approximate`` is ``True`` whenever ``calibration`` is ``None`` — i.e. there
    is no provider anchor yet, so the absolute figure is only the local estimate
    and the UI should mark it ``~``. It is ``False`` only once a calibration ratio
    is supplied.
    """
    approximate = calibration is None
    if not max_input_tokens:  # None or 0 → window unknown
        return None, approximate
    effective = local_total * calibration if calibration is not None else local_total
    return round(100 * effective / max_input_tokens), approximate


def model_window(model: str) -> int | None:
    """The model's input-token window, or ``None`` if unknown — never raises.

    Wraps litellm's ``get_model_info(model)["max_input_tokens"]``. litellm raises
    for a model it does not recognise and may report the field absent or ``None``;
    every such case degrades to ``None`` so callers can treat an unknown model as
    simply "no window" rather than guarding against exceptions.
    """
    try:
        info = litellm.get_model_info(model)
    except Exception:
        return None
    window = info.get("max_input_tokens") if isinstance(info, dict) else None
    return window if isinstance(window, int) and window > 0 else None
