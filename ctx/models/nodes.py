from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


def _render_search_results(results: list[dict]) -> str:
    """Render a ranked hit list as the results block the model reads.

    One block per hit — ``rank. title`` / source line / snippet — in the order
    given, blocks separated by a blank line. The source line carries the date
    only when the backend reported one (they differ on whether they do), so a
    date-less hit never renders a placeholder. No hits renders to ``""``, which
    is what makes an empty search contribute nothing to the model.
    """
    blocks = []
    for rank, hit in enumerate(results, start=1):
        date = hit.get("date")
        url = hit.get("url", "")
        source = f"{url} ({date})" if date else url
        blocks.append(
            f"{rank}. {hit.get('title', '')}\n{source}\n{hit.get('snippet', '')}"
        )
    return "\n\n".join(blocks)


@dataclass
class Node:
    id: str = field(default_factory=lambda: uuid4().hex)
    conversation_id: str = ""
    role: str = ""
    content: str = ""
    node_type: str = "message"
    meta: dict = field(default_factory=dict)
    # Append-only graph edges (ADR-0016): prev_id = predecessor (None = root;
    # shared prev_id = branch siblings). compressed_into wired up in S3.
    prev_id: str | None = None
    compressed_into: str | None = None
    # Monotonic creation order (ADR-0016 A#2), assigned by ConversationCore when a
    # node enters the graph and never reassigned; the 3b event-enumeration oracle.
    created_seq: int = 0

    @classmethod
    def user(cls, content: str, conversation_id: str) -> Node:
        """Build a user chat turn."""
        return cls(role="user", content=content, conversation_id=conversation_id)

    @classmethod
    def assistant(cls, conversation_id: str, content: str = "") -> Node:
        """Build an assistant chat turn (content is filled in as it streams).

        ``meta`` keys stamped later by ``ConversationCore`` (the canonical
        vocabulary for assistant turns — do not improvise new keys):
          - ``meta["ctx_hash"]`` — digest of the exact context sent to the
            model, stamped at the turn's first tick (ADR-0016 A#3 §4);
          - ``meta["interrupted"]`` — ``True`` when the turn was cancelled
            mid-stream (stamped durably by ``end_turn``);
          - ``meta["error"]`` — the provider/build error message when the turn
            failed (stamped durably by ``end_turn``).
        """
        return cls(role="assistant", content=content, conversation_id=conversation_id)

    @classmethod
    def system(cls, content: str, conversation_id: str = "") -> Node:
        """Build a system breadcrumb (e.g. "Model set to: …").

        The optional ``conversation_id`` decides durability: passed inside an
        active conversation the breadcrumb persists (model-change/connectivity
        notices reappear on resume); left empty it stays session-local, because
        storage skips id-less nodes (ADR 0006 #6).
        """
        return cls(
            role="system",
            content=content,
            node_type="system",
            conversation_id=conversation_id,
        )

    @classmethod
    def search(
        cls,
        query: str,
        results: list[dict],
        conversation_id: str,
    ) -> Node:
        """Build a ``search`` node: one web search the model ran, plus its hits.

        A search is its own node kind rather than a context import, because a
        query with a ranked hit list is a genuinely different shape from a file
        snapshot and the high-ground view must tell them apart at a glance
        (ADR-0018 §4). ``role`` and ``node_type`` are both ``"search"``.

        ``results`` is the ranked hit list, best hit first, as plain JSON-able
        dicts with the keys ``title``, ``url``, ``snippet`` and ``date`` (the
        date is optional — backends differ on whether they report one).

        ``content`` is the **rendered results block the model receives** — this
        factory renders it, so no call site invents its own layout. Every hit
        contributes its rank, title, url and snippet, in ranked order, with the
        date shown when the hit has one; ``build_context`` later wraps the whole
        block in ``<search_results query="…">``. An empty ``results`` list
        renders to empty content, and an empty search node contributes nothing
        to the model (the same rule as an empty context import).

        ``meta`` keys (the canonical vocabulary):
          - ``meta["query"]`` — the query string exactly as the model asked it
            (names the ``<search_results query="…">`` wrapper and the
            inspector's Prompt split);
          - ``meta["hits"]`` — the structured hit list, so the rendered block
            never has to be re-parsed to recover the individual results.
        """
        return cls(
            role="search",
            content=_render_search_results(results),
            node_type="search",
            conversation_id=conversation_id,
            meta={"query": query, "hits": list(results)},
        )

    def goes_to_model(self) -> bool:
        """Whether this node's content is sent to the LLM when building context.

        The single source of truth for "which nodes reach the model" —
        ``build_context`` routes its inclusion decision through this predicate
        rather than re-deriving role rules (ADR 0014 #1). User/assistant turns,
        context imports, compression nodes and search nodes reach the model; a
        compression node stands in for the folded originals it summarizes
        (ADR-0016 H6), and a search node replays its results as text so it stays
        as foldable as an import (ADR-0018 §3).
        """
        return self.role in {"user", "assistant"} or self.node_type in {
            "context",
            "compression",
            "search",
        }

    @classmethod
    def compression(
        cls,
        summary: str,
        conversation_id: str,
        range_ids: list[str],
        prompt: str = "",
    ) -> Node:
        """Build a compression node ``K`` that folds a contiguous range of nodes.

        A compression node stands in for the folded originals when context is
        built: the model sees ``summary`` (later wrapped in
        ``<conversation_summary>``) instead of the folded children
        (ADR-0016 A#1/A#2, H6).

        ``role`` and ``node_type`` are both ``"compression"``; ``content`` is the
        ``summary`` text. ``meta`` carries the canonical keys (H1/H5):
          - ``meta["prompt"]`` — the compression instruction that produced the
            summary (``""`` for a hand-written/manual summary).
          - ``meta["range"]`` — the ordered ids of the folded child nodes.

        The node sits **off** the ``prev_id`` line (``prev_id=None``); the core
        adds it straight to the graph, never via the line-append path.
        """
        return cls(
            role="compression",
            content=summary,
            node_type="compression",
            conversation_id=conversation_id,
            meta={"prompt": prompt, "range": list(range_ids)},
        )

    @classmethod
    def expand(
        cls,
        target_id: str,
        anchor_id: str | None,
        conversation_id: str,
    ) -> Node:
        """Build an expand event node ``E`` that deactivates a compression ``K``.

        ``E`` records the *event* of expanding ``K`` back to its folded children
        rather than any conversation content: ``role`` and ``node_type`` are both
        ``"expand"``, ``content`` is empty, and it never reaches the model
        (``goes_to_model()`` stays ``False``). Like a compression node it sits
        **off** the ``prev_id`` line (``prev_id=None``); the core adds it straight
        to the graph, never via the line-append path.

        ``meta`` carries the canonical keys (H5):
          - ``meta["target"]`` — the id of the compression ``K`` this expand
            deactivates.
          - ``meta["anchor"]`` — the active leaf id at expand time (S4
            forward-compat for branch-local expand; 3a resolution ignores it).
        """
        return cls(
            role="expand",
            node_type="expand",
            conversation_id=conversation_id,
            meta={"target": target_id, "anchor": anchor_id},
        )

    @classmethod
    def context(
        cls,
        content: str,
        source_path: str,
        conversation_id: str,
        prompt: str = "",
        source_content: str = "",
        origin: str = "user",
    ) -> Node:
        """Build a context-import node holding its content **on the node**.

        The single factory for both import front doors (ctx0 §3, supersedes
        ADR-0009's live-read imports). ``content`` is the node's *model-facing
        form* — the exact text ``build_context`` sends, wrapped in
        ``<context_import source="…">`` — so it is the snapshot/extract, never a
        "Included: …" reference label:

          - **verbatim** (``/include``): ``content`` is the raw file snapshot,
            ``prompt`` is ``""`` and ``source_content`` is ``""`` (the source is
            the content itself);
          - **prompt** (``/import``): ``content`` is the edited AI extract,
            ``prompt`` is the drafting instruction, and ``source_content`` is the
            raw file the extract was drawn from (kept for the inspector's Source
            pane; never sent to the model).

        ``meta`` keys (the canonical vocabulary):
          - ``meta["source_path"]`` — the imported file's path (names the
            ``<context_import source="…">`` wrapper and the inspector);
          - ``meta["prompt"]`` — the drafting instruction (``""`` for verbatim);
            its *presence* also marks a content-on-node node for the legacy read
            shim (see ``context._context_body``);
          - ``meta["source_content"]`` — the raw source for prompt-mode; omitted
            for verbatim (source == content).
          - ``meta["origin"]`` — stamped **only** when ``origin="model"``, marking
            a page the model fetched itself (a fetched page is an import whose
            source is a URL, ADR-0018 §4). The default ``"user"`` origin — a
            hand-driven ``/include`` or ``/import`` — stamps nothing, so the key's
            mere presence answers "did the model pull this in?".
        """
        meta = {"source_path": source_path, "prompt": prompt}
        if source_content:
            meta["source_content"] = source_content
        if origin == "model":
            meta["origin"] = origin
        return cls(
            role="context",
            content=content,
            node_type="context",
            conversation_id=conversation_id,
            meta=meta,
        )
