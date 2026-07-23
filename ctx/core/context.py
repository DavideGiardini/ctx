import hashlib
import json
from collections.abc import Callable
from typing import Any

from ctx.core.log import logger
from ctx.models.nodes import Node

OPEN_COMPRESS_MARKER = "<compress_this>"
CLOSE_COMPRESS_MARKER = "</compress_this>"


def hash_context(messages: list[dict[str, Any]]) -> str:
    """Canonical, stable digest of a rendered ``build_context`` message list.

    Returns the hex sha256 of ``json.dumps(messages, sort_keys=True,
    ensure_ascii=False)``. The digest depends only on the *content* of the
    messages, not on dict key insertion order (``sort_keys=True``), and is a
    pure function — identical input always yields the identical string, and any
    change to message roles, content, ordering, or count changes it.

    This is the per-turn verification anchor (ADR-0016 A#3 §4): at generation
    time the exact rendered messages are hashed and stored immutably on the
    assistant node's ``meta["ctx_hash"]``. Under ctx0 (ADR-0017) the stamp is
    *write-only* — the reading surfaces that re-derived and compared it were
    subtracted — but it is still recorded on every turn so a future reader can
    verify a reconstruction against it.
    """
    canonical = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def model_facing_form(
    node: Node, load_file: Callable[[str], str]
) -> tuple[str, str] | None:
    """The single rule for a node's ``(role, body)`` as the model sees it.

    Returns ``None`` when the node contributes nothing to the request. This is
    the one definition of "what does this node look like to the model" — both
    ``build_context`` (which then wraps the body in ``<context_import>`` /
    ``<conversation_summary>`` XML) and the compression transcript
    (``_transcript_block``, which labels it ``Role:``) consume it, so the rule
    is not hand-synced in two places (Code Quality Review, "Model-facing-form
    extraction").

      - ``user`` / ``assistant`` turns contribute their ``content`` under their
        own role; empty content contributes nothing.
      - a ``context`` node contributes its content-on-node body under the
        ``user`` role (its snapshot/extract — see ``_context_body``); an empty
        body contributes nothing.
      - a committed compression ``K`` contributes its summary (``content``)
        under the ``user`` role.
      - any node that does not reach the model (``goes_to_model()`` false —
        a ``system`` breadcrumb, an ``expand`` event) contributes nothing.
    """
    if not node.goes_to_model():
        return None
    if node.node_type == "context":
        body = _context_body(node, load_file)
        return ("user", body) if body else None
    if node.node_type == "compression":
        return ("user", node.content) if node.content else None
    return (node.role, node.content) if node.content else None


def _context_body(node: Node, load_file: Callable[[str], str]) -> str | None:
    """A context node's model-facing body: its content-on-node snapshot/extract.

    Content-on-node (ctx0 ``import``, supersedes ADR-0009): a context node stores
    the exact text the model should see — the verbatim file snapshot, or the
    edited extract — on ``node.content``. ``build_context`` no longer reads the
    file live.

    AIDEV-NOTE: legacy back-compat shim. Pre-``import`` ``/include`` nodes stored
    only ``meta["source_path"]`` (no ``"prompt"`` key) with an ``"Included: …"``
    label as content, and were read live every turn. A content-on-node node
    always carries a ``"prompt"`` key (set by ``Node.context``), so its absence
    marks a legacy node — fall back to a live read so old conversations still
    resolve; a failed read yields a visible ``[could not read …]`` sentinel
    rather than silently vanishing. Drop this branch once such nodes have aged
    out of stored conversations.
    """
    if "prompt" in node.meta:
        return node.content or None
    source_path = node.meta.get("source_path", "")
    if not source_path:
        return None
    try:
        return load_file(source_path)
    except (OSError, ValueError) as exc:
        logger.warning(
            "failed to read legacy context file | path=%s | error=%s", source_path, exc
        )
        return f"[could not read {source_path}: {exc}]"


def build_context(
    nodes: list[Node], load_file: Callable[[str], str]
) -> list[dict]:
    """Convert a list of Nodes into LLM message dicts.

    Each node's model-facing ``(role, body)`` comes from ``model_facing_form``.
    A ``context`` node's body (its content-on-node snapshot/extract) is wrapped
    in ``<context_import source="…">`` XML; a ``compression`` node's summary is
    wrapped in ``<conversation_summary>`` XML; both count as user-role content so
    a summary or import coalesces with adjacent user material (ADR-0016 A#1, H6).
    Adjacent user-role content is coalesced into one user message; assistant
    nodes are appended as their own; nodes that reach nothing are skipped.

    ROLE-ALTERNATION INVARIANT: the returned list never contains two adjacent
    dicts of the same role. Strict role-alternation providers (Anthropic-family
    via litellm) reject consecutive same-role turns, so whenever user-role
    material would follow an already-emitted user message it is *merged* into
    that message with an explicit ``\\n\\n`` separator — never emitted as a
    second user dict and never glued on with no separator. A dropped node (a
    system breadcrumb) emits nothing and does **not** break the merge: two user
    runs separated only by dropped nodes still collapse to one user message.
    Only an assistant message breaks the run, so material after it starts a
    fresh user dict (task 34).

    ``load_file`` is injected (for the legacy context read shim, see
    ``_context_body``) so this stays pure and testable without I/O.
    """
    messages: list[dict] = []

    for node in nodes:
        form = model_facing_form(node, load_file)
        if form is None:
            continue
        role, body = form

        if node.node_type == "context":
            source_path = node.meta.get("source_path", "")
            body = f'<context_import source="{source_path}">\n{body}\n</context_import>'
        elif node.node_type == "compression":
            body = f"<conversation_summary>\n{body}\n</conversation_summary>"

        if role == "user":
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] += "\n\n" + body
            else:
                messages.append({"role": "user", "content": body})
        elif role == "assistant":
            messages.append({"role": "assistant", "content": body})

    return messages


def build_compression_transcript(
    nodes: list[Node],
    range_ids: list[str],
    load_file: Callable[[str], str],
) -> str:
    """Render ``nodes`` as one plain-text transcript, marking a contiguous range.

    Used by the compression *draft* call (ADR-0016 Amendment #6): the model is
    handed the **whole active line** as a single user message so it sees the
    before/after context, with the range being compressed wrapped in
    ``<compress_this>`` / ``</compress_this>`` marker lines. This function is the
    pure renderer of that string; wiring it into ``draft_compression`` is task 47.

    Each node that reaches the model (``Node.goes_to_model()``) becomes one
    labeled block ``"{Role}:\\n{body}"`` in node order. The body is the node's
    *model-facing form*, reusing ``build_context``'s per-role/-type rules but as
    plain text (no ``<context_import>`` / ``<conversation_summary>`` XML wrapper):

      - a ``user`` / ``assistant`` turn contributes its ``content``, labeled
        ``User:`` / ``Assistant:`` by role;
      - a ``context`` node contributes its content-on-node body (the verbatim
        snapshot or the edited extract — the same body ``build_context`` sends,
        minus the XML wrapper), labeled ``User:`` (its model-facing role);
      - a committed compression ``K`` contributes its summary (``content``),
        labeled ``User:`` (its model-facing role).

    A node that does **not** reach the model (a ``system`` breadcrumb, an
    ``expand`` event) emits nothing, and a block whose body is empty is dropped —
    exactly the nodes ``build_context`` skips.

    The emitted blocks whose id is in ``range_ids`` are bracketed: a
    ``<compress_this>`` line immediately before the first such block and a
    ``</compress_this>`` line immediately after the last. Because the range is
    contiguous, these blocks are consecutive; blocks before the range appear
    above the opening marker and blocks after it below the closing marker. Blocks
    are separated by a blank line. If no in-range node produces a block (an empty
    marked span — e.g. the range is a single interrupted zero-token turn), the two
    marker lines are still emitted as an adjacent empty pair, so a caller (task 47)
    can detect the empty span.

    ``load_file`` is injected so this stays pure and testable without I/O.
    """
    marked = set(range_ids)
    before: list[str] = []
    within: list[str] = []
    after: list[str] = []
    seen_marked = False

    for node in nodes:
        block = _transcript_block(node, load_file)
        if block is None:
            continue
        if node.id in marked:
            within.append(block)
            seen_marked = True
        elif seen_marked:
            after.append(block)
        else:
            before.append(block)

    segments: list[str] = []
    if before:
        segments.append("\n\n".join(before))
    segments.append(
        f"{OPEN_COMPRESS_MARKER}\n"
        + "\n\n".join(within)
        + f"\n{CLOSE_COMPRESS_MARKER}"
    )
    if after:
        segments.append("\n\n".join(after))
    return "\n\n".join(segments)


def _transcript_block(node: Node, load_file: Callable[[str], str]) -> str | None:
    """Render one node as a ``"{Role}:\\n{body}"`` block, or None if it emits nothing.

    Consumes the shared ``model_facing_form`` rule (the plain body, no XML
    wrapper) and labels it — see ``build_compression_transcript``.
    """
    form = model_facing_form(node, load_file)
    if form is None:
        return None
    role, body = form
    return f"{role.title()}:\n{body}"
