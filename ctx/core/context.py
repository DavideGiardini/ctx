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


def build_context(
    nodes: list[Node], load_file: Callable[[str], str]
) -> list[dict]:
    """Convert a list of Nodes into LLM message dicts.

    Context nodes (node_type == "context") load their file, wrap it in
    <context_import> XML, and count as user-role content. Compression nodes
    (node_type == "compression") wrap their summary content in
    <conversation_summary> XML and likewise count as user-role content, so a
    summary coalesces with adjacent user material exactly like an import
    (ADR-0016 A#1, H6). Adjacent user-role content is coalesced into one user
    message; assistant nodes are appended as their own; other roles (e.g.
    system) are skipped.

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

    Failures are made *visible* rather than silent: when a context node's file
    fails to load (``load_file`` raises ``OSError``/``ValueError``), a marked
    ``<context_import source="…" error="…">`` block is emitted as user material
    so the model — and, through it, the user — sees that the import failed,
    instead of the file silently disappearing. A context node with no usable
    ``source_path`` has nothing to import and is dropped.

    Empty ``user``/``assistant`` nodes (``content == ""``) are skipped so no
    empty-content message reaches the provider (several APIs reject those).

    ``load_file`` is injected so this stays pure and testable without I/O.
    """
    messages: list[dict] = []

    for node in nodes:
        if not node.goes_to_model():
            continue

        node_content, node_role = node.content, node.role

        if node.node_type == "context":
            source_path = node.meta.get("source_path")
            if not source_path:
                logger.warning("context node missing source_path | node_id=%s", node.id)
                continue
            try:
                content = load_file(source_path)
            except (OSError, ValueError) as exc:
                logger.warning(
                    "failed to read context file | path=%s | error=%s", source_path, exc
                )
                node_content = (
                    f'<context_import source="{source_path}" error="{exc}">'
                    "</context_import>"
                )
            else:
                node_content = (
                    f'<context_import source="{source_path}">\n{content}\n</context_import>'
                )
            node_role = "user"

        elif node.node_type == "compression":
            node_content = (
                f"<conversation_summary>\n{node_content}\n</conversation_summary>"
            )
            node_role = "user"

        if node_role == "user":
            if not node_content:
                continue
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] += "\n\n" + node_content
            else:
                messages.append({"role": "user", "content": node_content})
        elif node_role == "assistant":
            if not node_content:
                continue
            messages.append({"role": "assistant", "content": node_content})

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
      - a ``context`` node contributes the loaded file body (``load_file`` on its
        ``meta["source_path"]``), **not** the "Included: …" label, labeled
        ``User:`` (its model-facing role) — a context node with no usable
        ``source_path`` contributes nothing;
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

    Mirrors ``build_context``'s per-role/-type inclusion and model-facing forms,
    but as plain labeled text (no XML wrapper) — see ``build_compression_transcript``.
    """
    if not node.goes_to_model():
        return None

    if node.node_type == "context":
        source_path = node.meta.get("source_path")
        if not source_path:
            return None
        try:
            body = load_file(source_path)
        except (OSError, ValueError) as exc:
            body = f"[could not read {source_path}: {exc}]"
        role = "user"
    elif node.node_type == "compression":
        body = node.content
        role = "user"
    else:
        body = node.content
        role = node.role

    if not body:
        return None
    return f"{role.title()}:\n{body}"
