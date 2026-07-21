from collections.abc import AsyncIterator, Callable
from uuid import uuid4

from ctx.core import tokens
from ctx.core.config import DEFAULT_COMPRESSION_PROMPT, get_config
from ctx.core.context import (
    CLOSE_COMPRESS_MARKER,
    OPEN_COMPRESS_MARKER,
    build_compression_transcript,
    build_context,
    hash_context,
)
from ctx.core.provider import Provider, Usage
from ctx.core.storage import StoragePort
from ctx.core.workspace import Workspace
from ctx.models.nodes import Node

# A provider's reported prompt-token count is accepted as a calibration anchor
# only when it lands within this factor of the local estimate (either
# direction). A count wildly off the local sum signals a mismatched tokenizer or
# a buggy provider report and is rejected rather than poisoning the gauge.
CALIBRATION_TOLERANCE = 10.0

MAX_TITLE_LENGTH = 50

# ``DEFAULT_COMPRESSION_PROMPT`` — the preserve-info fallback for the one-keystroke
# compression path (ADR-0016 A#1) — now lives in ctx.core.config as the single
# source of the ``compression.default_prompt`` default (task 18); re-exported here
# so existing importers of ``ConversationCore``'s module keep working.
__all__ = ["ConversationCore", "DEFAULT_COMPRESSION_PROMPT"]


def _derive_title(content: str) -> str:
    """Derive a conversation title from a message's content.

    Single source of truth for the title shape: the first ``MAX_TITLE_LENGTH``
    characters with newlines flattened to spaces, so ``_ensure_conversation`` and
    ``resume_conversation`` cannot drift (ADR 0006 #5).
    """
    return content[:MAX_TITLE_LENGTH].replace("\n", " ")


class ConversationCore:
    """Deep module: owns conversation state, commands, and streaming lifecycle.

    Persistence policy (uniform across commands): every command method that
    mutates conversation state — ``submit``, ``set_model``, ``check_connectivity``,
    ``add_system_message``, ``include_files`` — calls ``persist()`` after creating
    its node(s), and constructs those nodes with the active ``conversation_id`` so
    the storage layer actually writes them. A command run before any conversation
    exists (``conversation_id == ""``) produces a transient node and ``persist()``
    no-ops, so nothing is written until there is a conversation to own it. The
    consequence is that model-change and connectivity breadcrumbs survive resume.
    """

    def __init__(
        self,
        storage: StoragePort,
        provider: Provider,
        workspace: Workspace,
    ) -> None:
        self._storage = storage
        self._provider = provider
        self._workspace = workspace
        # Default model is read once from config at construction (no per-call
        # file I/O); used for the initial model and on /new reset (ADR 0006 #3).
        self._default_model: str = get_config()["model"]
        # Append-only conversation graph (ADR-0016): _graph holds ALL nodes keyed
        # by id (active line + abandoned tails + S3 compression children),
        # _active_leaf_id is the current tip. See current_view().
        self._graph: dict[str, Node] = {}
        self._active_leaf_id: str | None = None
        self.conversation_id: str = ""
        self.conversation_title: str = ""
        self.model: str = self._default_model
        # Provider-anchored token accounting for the header gauge (ADR 0015 #2);
        # see the last_usage/calibration/usage_generation properties.
        self._last_usage: Usage | None = None
        self._calibration: float | None = None
        self._usage_generation: int = 0
        # True while a turn is in flight — from submit() (which stamps the
        # assistant seq) through stream() completing. The compression commands
        # (H2) refuse to mutate the graph while it is set (ADR-0016 A#3 §2).
        self._streaming: bool = False

    @property
    def streaming(self) -> bool:
        """Whether a turn is currently in flight.

        ``True`` from ``submit()`` (which stamps the assistant node's
        ``created_seq`` but does not yet build its context) until the turn's
        ending is recorded by ``end_turn`` — or the conversation is abandoned
        by new/resume. The compression commands read it to enforce the H2
        invariant: no commit/expand/draft may mutate the graph mid-turn, so no
        event can land in the ``submit()``→first-tick window and fold into what
        the model actually saw after its ``ctx_hash`` was stamped (A#3 §2).
        """
        return self._streaming

    @property
    def last_usage(self) -> Usage | None:
        """The provider's exact ``Usage`` for the most recent streamed turn.

        ``None`` until a turn completes whose provider-reported usage passes the
        sanity check (see ``calibration``); thereafter it is that turn's
        ``Usage``. A turn whose provider reports no usage, or reports usage that
        fails the sanity check, leaves the previous value unchanged.
        """
        return self._last_usage

    @property
    def calibration(self) -> float | None:
        """Provider prompt-token count ÷ local estimate for the latest turn.

        The factor the header gauge uses to scale its provider-agnostic local
        estimate onto the provider's own tokenizer. It is
        ``prompt_tokens / local_sum`` for the most recent turn whose usage passed
        the sanity check — ``prompt_tokens > 0``, a positive local sum, and the
        two within ``CALIBRATION_TOLERANCE``× of each other. ``None`` until such a
        turn occurs; a turn with no usage, or with usage that fails the sanity
        check, leaves the previous value unchanged.
        """
        return self._calibration

    @property
    def usage_generation(self) -> int:
        """Counter incremented each time a streamed turn adopts provider usage.

        Starts at ``0`` and bumps by one every time ``_calibrate`` accepts a
        sane ``Usage`` (and so updates ``last_usage``/``calibration``); a turn
        that reports no usage or a usage that fails the sanity check leaves it
        unchanged. The UI samples it before and after a turn to tell whether
        *this* turn produced a fresh exact anchor — robust regardless of whether
        the provider reuses one ``Usage`` object across turns (ADR 0015 #2).
        """
        return self._usage_generation

    @property
    def read_file(self) -> Callable[[str], str]:
        """The file loader used to resolve ``context`` nodes.

        Exactly the loader handed to ``build_context`` at stream time, exposed so
        the UI's token-accounting can render nodes the same way the model sees
        them without reaching past the core into the workspace.
        """
        return self._workspace.read_file

    def _active_line(self) -> list[Node]:
        """The raw active line: nodes reached by walking ``prev_id`` from the tip.

        Root-first and **unfolded** — the same walk ``current_view()`` performs
        before it applies compression folding, so it still contains the folded
        children (their ``prev_id`` chain is intact) and never the off-line
        ``K``/``E`` nodes (``prev_id=None``, they live off the line). The walk
        defensively stops on an id missing from the graph or already seen, so a
        malformed chain can never hang. Single source of truth for "which nodes
        are on the line": ``current_view`` folds it, resume derives the title
        from it, and ``rewind`` guards membership against it.
        """
        line: list[Node] = []
        seen: set[str] = set()
        cur = self._active_leaf_id
        while cur is not None and cur in self._graph and cur not in seen:
            seen.add(cur)
            node = self._graph[cur]
            line.append(node)
            cur = node.prev_id
        line.reverse()
        return line

    def _expanded_k_ids(self) -> set[str]:
        """Ids of compressions deactivated by an expand event ``E`` (A#2 now-rule).

        A compression ``K`` is inactive as soon as any ``E`` node targets it
        (``E.meta["target"] == K.id``); ``expand_compression`` appends that ``E``.
        The single event read behind both the now-view fold and the ``expand``
        liveness guard — ``compressed_into`` is never consulted (ADR-0016 A#3 §3).
        """
        return {
            target
            for n in self._graph.values()
            if n.node_type == "expand"
            and (target := n.meta.get("target")) is not None
        }

    def _active_folds(self, line_ids: set[str]) -> dict[str, Node]:
        """Map each folded child id on the current line to its active ``K``.

        Event-enumeration resolution (ADR-0016 A#2/H3 now-rule): a compression
        ``K`` applies iff **no ``E`` targets it** and its whole stored range
        (``K.meta["range"]``) lies on the line (``⊆ line_ids``). Discovery scans
        the ``K``/``E`` event nodes in the graph; child ``compressed_into``
        pointers are never read, so a stale pointer with no matching applying
        ``K`` folds nothing. Active compressions never overlap (A#3), so each
        folded child maps to exactly one ``K``.
        """
        expanded = self._expanded_k_ids()
        folds: dict[str, Node] = {}
        for k in self._graph.values():
            if k.node_type != "compression" or k.id in expanded:
                continue
            range_ids = k.meta.get("range", [])
            if range_ids and all(child_id in line_ids for child_id in range_ids):
                for child_id in range_ids:
                    folds[child_id] = k
        return folds

    def current_view(self) -> list[Node]:
        """Project the active line as the linear ``list[Node]`` the UI consumes.

        Walks ``prev_id`` from the active tip back to the root and reverses, so
        the result is root-first. Deterministic; the walk defensively stops on an
        id missing from the graph or already seen, so a malformed chain can never
        hang the UI. Empty conversation → ``[]``; after a ``rewind`` the view is
        correspondingly shorter (the dropped tail stays in ``_graph``).

        Compression folding (ADR-0016 A#2/H3 now-rule): after the walk, each
        **maximal contiguous run** of the applying compressions' children is
        replaced *in place* by the compression node ``K``. Which ``K`` applies is
        resolved by **event enumeration** (``_active_folds``) — a ``K`` folds iff
        no ``E`` targets it and its stored range lies on the line — **never** by
        following child ``compressed_into`` pointers (ADR-0016 A#3 §3). The folded
        children leave the view and ``K`` appears despite its ``prev_id=None`` (it
        lives off the line). Two independent compressions yield two ``K`` nodes;
        after an ``expand`` the ``E`` deactivates ``K`` so its children reappear.
        The tip may itself be folded — the view then ends with ``K`` — but
        ``_append_to_line`` still chains new nodes from the real
        ``_active_leaf_id``, so appending after a folded tip yields ``[…, K, new]``.
        """
        view = self._active_line()
        folds = self._active_folds({n.id for n in view})

        resolved: list[Node] = []
        i = 0
        while i < len(view):
            k = folds.get(view[i].id)
            if k is None:
                resolved.append(view[i])
                i += 1
            else:
                # Collapse the maximal contiguous run folded into the same K.
                resolved.append(k)
                while i < len(view) and folds.get(view[i].id) is k:
                    i += 1
        return resolved

    @property
    def nodes(self) -> list[Node]:
        """The active conversation line (today's flat node list).

        A read-only projection over the graph (``current_view()``), recomputed on
        each access, so every existing reader — the UI, token accounting,
        ``describe_state`` — sees exactly today's shape with no changes. Mutations
        go through the command methods (which route to ``_append_to_line``), never
        by assigning or appending to this list.
        """
        return self.current_view()

    def _all_nodes(self) -> list[Node]:
        """Every node in the graph, in insertion (≈ creation/rowid) order.

        Handed to ``storage.save`` so the full non-destructive graph round-trips —
        persisting only ``current_view()`` would delete abandoned tails and make
        rewind destructive.
        """
        return list(self._graph.values())

    def all_nodes(self) -> list[Node]:
        """Read-only view of the whole graph (line + abandoned tails + K/E events).

        The whole-graph accessor: it includes off-line ``K``/``E`` events and
        abandoned rewind tails that the active line ``nodes`` projects away
        (ADR-0016 A#2/A#3, H6).
        """
        return self._all_nodes()

    def _next_seq(self) -> int:
        """The next ``created_seq``: one past the max over the WHOLE graph.

        Computed over every node in ``_graph`` (active line + abandoned tails +
        off-line ``K``/``E`` events, H6) — never the view — so a rewind's
        abandoned tail is still counted and seqs never collide or get reused.
        Empty graph → ``1``; monotonic and, because it is only ever *assigned* to a
        fresh node (never reassigned), stable across persistence and resume
        (``resume_conversation`` rebuilds ``_graph`` from the loaded seqs, so this
        continues from the loaded max, ADR-0016 A#2).
        """
        return max((n.created_seq for n in self._graph.values()), default=0) + 1

    def _add_to_graph(self, node: Node) -> None:
        """Stamp ``created_seq`` and place an off-line node straight into the graph.

        The single insertion primitive for the off-line event nodes (``K``, ``E``);
        line nodes go through ``_append_to_line``. Both stamp the seq before insert.
        """
        node.created_seq = self._next_seq()
        self._graph[node.id] = node

    def _append_to_line(self, node: Node) -> None:
        """Append a node onto the active line and advance the tip.

        Sets ``prev_id`` to the current tip and makes the node the new tip — the
        single graph-mutation primitive behind every command that used to do
        ``self.nodes.append(...)``. Stamps a monotonic ``created_seq`` (A#2).
        """
        node.created_seq = self._next_seq()
        node.prev_id = self._active_leaf_id
        self._graph[node.id] = node
        self._active_leaf_id = node.id

    def setup(self) -> None:
        self._workspace.ensure()
        self._storage.init()

    def _ensure_conversation(self, first_message: str) -> None:
        if not self.conversation_id:
            self.conversation_id = uuid4().hex
        if not self.conversation_title:
            self.conversation_title = _derive_title(first_message)

    def persist(self) -> None:
        if not self.conversation_id:
            return
        # AIDEV-NOTE: persist the FULL graph (_all_nodes), not the active view —
        # else a rewind's abandoned tail is deleted and rewind turns destructive.
        self._storage.save(
            self.conversation_id,
            self.conversation_title,
            self._all_nodes(),
            model=self.model,
            active_leaf_id=self._active_leaf_id,
        )

    def submit(self, text: str) -> tuple[Node, Node]:
        """Handle a user message. Returns (user_node, assistant_node).

        Raises ``ValueError`` while a turn is already in flight: a second
        submit is refused, never queued. This is the authoritative backstop —
        the UI's own streaming check is a courtesy hint, not the guard.
        """
        if self._streaming:
            raise ValueError("cannot submit while a turn is streaming")
        self._ensure_conversation(text)
        user_node = Node.user(text, self.conversation_id)
        self._append_to_line(user_node)
        # AIDEV-NOTE: persist with the tip at the user node, before the assistant
        # node exists, so a crash mid-stream resumes cleanly on the user turn.
        self.persist()

        assistant_node = Node.assistant(self.conversation_id)
        self._append_to_line(assistant_node)
        # AIDEV-NOTE: the turn is in flight from here — its created_seq is stamped
        # but its context/ctx_hash isn't built until stream()'s first tick. Flag it
        # now so no compression event can land in that window (else it folds into
        # what was actually sent after its ctx_hash was stamped —
        # ADR-0016 A#3 §2, task 28). end_turn() lowers it; new/resume reset it
        # for the tests-only "submit never followed by stream()" path.
        self._streaming = True
        return user_node, assistant_node

    def end_turn(
        self, node: Node, *, cancelled: bool = False, error: str | None = None
    ) -> None:
        """Record the ending of the turn anchored on ``node`` — the single door
        every ending passes through (clean finish, cancel, or error).

        Always lowers the in-flight ``streaming`` flag. Then, provided ``node``
        is still part of the current conversation graph (i.e. the conversation
        was not switched away mid-turn by new/resume), records what the turn
        became and persists — in that order, so the durable mark can never be
        lost to an earlier save:

        - clean finish (no keyword): nothing stamped; the final content and
          the whole graph are persisted;
        - ``cancelled=True``: stamps ``node.meta["interrupted"] = True``;
        - ``error=<message>``: stamps ``node.meta["error"] = <message>``.

        ``cancelled`` and ``error`` are mutually exclusive; passing both raises
        ``ValueError``. A turn whose conversation was abandoned (``node`` no
        longer in the graph) lowers the flag and otherwise no-ops: nothing may
        be stamped into — or persisted over — the newly loaded conversation.
        """
        if cancelled and error is not None:
            raise ValueError("a turn ends cancelled or errored, never both")
        self._streaming = False
        # AIDEV-NOTE: identity check, not id membership — a resume of the SAME
        # conversation rebuilds the graph with fresh Node objects, and stamping
        # the stale object would silently miss the live copy.
        if self._graph.get(node.id) is not node:
            return
        if cancelled:
            node.meta["interrupted"] = True
        elif error is not None:
            node.meta["error"] = error
        self.persist()

    def set_model(self, model: str) -> Node:
        self.model = model
        node = Node.system(f"Model set to: {model}", self.conversation_id)
        self._append_to_line(node)
        self.persist()
        return node

    async def check_connectivity(self, model: str) -> Node:
        ok, msg = await self._provider.check_connectivity(model)
        if ok:
            node = Node.system(f"✔ Connected to {model}", self.conversation_id)
        else:
            node = Node.system(
                f"⚠ Could not verify connectivity to {model} — "
                f"the model may still work. Error: {msg}",
                self.conversation_id,
            )
        self._append_to_line(node)
        self.persist()
        return node

    def new_conversation(self) -> Node:
        self.persist()
        self._graph = {}
        self._active_leaf_id = None
        self.conversation_id = ""
        self.conversation_title = ""
        self.model = self._default_model
        self._streaming = False  # a fresh conversation abandons any in-flight turn
        return Node.system("Started a new conversation.")

    def resume_conversation(self, conv_id: str) -> list[Node]:
        loaded = self._storage.load(conv_id)
        if not loaded:
            # Unknown id: leave the in-progress conversation intact.
            return []
        # Rebuild the whole graph from the stored edges; tip = stored active_leaf,
        # falling back to the last node by load order if it's absent/dangling
        # (a pre-migration row the backfill left NULL).
        self._graph = {node.id: node for node in loaded}
        self._streaming = False  # a resumed conversation has no turn in flight
        self._active_leaf_id = self._storage.get_active_leaf(conv_id)
        if self._active_leaf_id is None or self._active_leaf_id not in self._graph:
            self._active_leaf_id = loaded[-1].id
        self.conversation_id = conv_id
        stored_model = self._storage.get_model(conv_id)
        if stored_model:
            # Empty/absent model (e.g. a pre-migration row) keeps the current default.
            self.model = stored_model
        # Prefer the stored title (authoritative); derive only when it is empty.
        # Derivation walks the raw active line, never the folded view — a first
        # user turn folded into a K must still title the conversation, and every
        # user turn being folded must not silently blank the title (which the
        # next persist() would then overwrite permanently).
        stored_title = self._storage.get_title(conv_id)
        if stored_title:
            self.conversation_title = stored_title
        else:
            self.conversation_title = next(
                (
                    _derive_title(n.content)
                    for n in self._active_line()
                    if n.role == "user"
                ),
                "",
            )
        return self.nodes

    def include_files(self, paths: list[str]) -> list[Node]:
        self._ensure_conversation("")
        nodes: list[Node] = []
        for path in paths:
            node = Node.context(path, self.conversation_id)
            self._append_to_line(node)
            nodes.append(node)
        self.persist()
        return nodes

    def add_system_message(self, content: str) -> Node:
        node = Node.system(content, self.conversation_id)
        self._append_to_line(node)
        self.persist()
        return node

    def rewind(self, target_id: str) -> list[Node]:
        """Move the active tip back to an earlier node on the current line.

        ``target_id`` must be a node on the current active line (reachable by
        walking ``prev_id`` from the tip); it becomes the new tip *inclusive*, so
        ``current_view()`` then ends at it. The nodes after it are **not** deleted
        — they stay in the graph and the DB as an abandoned tail (append-only),
        recoverable by rewinding forward or, later, surfaced as a branch (S4).
        Raises ``ValueError`` if ``target_id`` is not on the active line. The
        line is the raw ``_active_line()``, **not** ``current_view()``: the view
        contains off-line ``K``/``E`` nodes, and rewinding to a ``K`` (``prev_id
        =None``) would collapse the view to ``[K]`` and land it on the line on the
        next ``submit`` (Q1). Folded children are on the raw line but rejected too
        for now (S4 revisits branching onto a folded turn) — a child is "folded"
        iff event enumeration (``_active_folds``) currently folds it, not by any
        ``compressed_into`` pointer (ADR-0016 A#3 §3).
        """
        line = self._active_line()
        folds = self._active_folds({n.id for n in line})
        if not any(
            node.id == target_id and node.id not in folds for node in line
        ):
            raise ValueError(f"rewind target not on active line: {target_id}")
        self._active_leaf_id = target_id
        self.persist()
        return self.nodes

    def _validate_compress_range(self, start_id: str, end_id: str) -> list[Node]:
        """Validate a compression range and return the slice it delimits.

        ``start_id`` and ``end_id`` must delimit a contiguous slice of
        ``current_view()`` (``start_id`` at or before ``end_id``, both present).
        The shared precondition check for ``commit_compression`` and (task 5)
        ``draft_compression``. Raises ``ValueError`` unless all hold:

        - not ``self.streaming`` (H2 — no compression mid-turn);
        - both ids are in ``current_view()`` and ``start_id`` is at or before
          ``end_id`` (a real, forward, contiguous slice);
        - **no node in the slice is ``node_type == "compression"``** (Q7 flat
          guard — nested compression is out of scope).

        The old 3a tip guard (slice must end at the active leaf) was deleted in
        task 22: a middle range is now foldable, and the per-turn ``ctx_hash``
        stamp records what each turn actually saw (ADR-0016 Q5 — 3b *replaces*
        the guard with the recorded stamp, not merely drops it).

        Returns the slice as a ``list[Node]`` in view (root-first) order.
        """
        if self.streaming:
            raise ValueError("cannot compress while a turn is streaming")
        view = self.current_view()
        ids = [n.id for n in view]
        try:
            start = ids.index(start_id)
            end = ids.index(end_id)
        except ValueError as exc:
            raise ValueError(
                f"compression range endpoints not in view: {start_id}, {end_id}"
            ) from exc
        if start > end:
            raise ValueError(
                f"compression range start is after end: {start_id}, {end_id}"
            )
        slice_nodes = view[start : end + 1]
        if any(n.node_type == "compression" for n in slice_nodes):
            raise ValueError("cannot compress a range containing a compression node")
        return slice_nodes

    def commit_compression(
        self, start_id: str, end_id: str, summary: str, prompt: str = ""
    ) -> Node:
        """Fold a contiguous range into a compression node ``K`` (pure, no AI).

        Validates the range via ``_validate_compress_range`` (raising
        ``ValueError`` on any failure), then non-destructively records the
        compression: a ``Node.compression`` ``K`` (``meta["range"]`` = the slice
        ids in order, ``meta["prompt"] = prompt``) is added straight to the
        graph, each slice node gets ``compressed_into = K.id``, and the state is
        persisted. The children are preserved (never deleted); ``current_view()``
        then shows ``K`` in their place. Returns the new ``K``.
        """
        slice_nodes = self._validate_compress_range(start_id, end_id)
        k = Node.compression(
            summary,
            self.conversation_id,
            [n.id for n in slice_nodes],
            prompt=prompt,
        )
        self._add_to_graph(k)
        for node in slice_nodes:
            node.compressed_into = k.id
        self.persist()
        return k

    def expand_compression(self, k_id: str) -> None:
        """Expand an active compression ``K`` back to its folded children.

        The non-destructive inverse of ``commit_compression``. Validates that
        ``k_id`` names a compression node that is currently **active** — no
        ``E`` event already targets it (A#2 now-rule, not a ``compressed_into``
        read) — and that no turn is streaming (H2); raises ``ValueError``
        otherwise.

        The mutation records the 3b-shaped event even though 3a's own resolution
        stays pointer-based (ADR-0016 A#3 §1): an ``E`` expand event node
        (``Node.expand`` with ``meta["target"] = k_id`` and ``meta["anchor"]`` =
        the current active leaf) is added straight to the graph, and every folded
        child (read from ``K.meta["range"]``) has its ``compressed_into`` cleared,
        so ``current_view()`` restores the children in ``K``'s place. ``K`` itself
        is **kept** in the graph as an off-line orphan (never row-deleted), then
        the state is persisted.
        """
        if self.streaming:
            raise ValueError("cannot expand while a turn is streaming")
        k = self._graph.get(k_id)
        if k is None or k.node_type != "compression":
            raise ValueError(f"not a compression node: {k_id}")
        # Active iff no E already targets it (event enumeration, A#3 §3) — an
        # already-expanded K has an E and re-expanding it is rejected.
        if k_id in self._expanded_k_ids():
            raise ValueError(f"compression is not active: {k_id}")
        e = Node.expand(k_id, self._active_leaf_id, self.conversation_id)
        self._add_to_graph(e)
        for child_id in k.meta["range"]:
            child = self._graph.get(child_id)
            if child is not None:
                child.compressed_into = None
        self.persist()

    def folded_children(self, k_id: str) -> list[Node]:
        """Return the nodes folded into compression ``K``, in recorded order.

        Reads ``K.meta["range"]`` — the ordered child ids captured at commit —
        and resolves each from the graph, preserving that order; a range id
        missing from the graph is skipped (defensive). Returns ``[]`` when
        ``k_id`` is unknown or does not name a compression node. The folded
        children are **not** in ``current_view()`` (they left the view when
        folded, Q8), so this is how the UI reaches them for the committed-``K``
        inspector.
        """
        k = self._graph.get(k_id)
        if k is None or k.node_type != "compression":
            return []
        children: list[Node] = []
        for child_id in k.meta["range"]:
            child = self._graph.get(child_id)
            if child is not None:
                children.append(child)
        return children

    async def draft_compression(
        self, start_id: str, end_id: str, prompt: str | None = None
    ) -> AsyncIterator[str]:
        """Stream an AI-drafted summary of a contiguous range (a meta-operation).

        Validates the range via ``_validate_compress_range`` (the same guards as
        ``commit_compression`` — streaming/H2, contiguous view slice, flat; the
        3a tip guard was deleted in task 22 so a middle range drafts too), raising
        ``ValueError`` on any failure **before any provider call**.

        The provider call is framed per ADR-0016 Amendment #6 (superseding Q10c):

        - the **system** message is the editable instruction — ``prompt`` when it is
          non-blank, else ``DEFAULT_COMPRESSION_PROMPT``; a ``None`` or
          whitespace-only prompt is not a real instruction (13i) and falls back to
          the default. The scaffold that tells the model to summarize only the
          marked span lives inside that prompt;
        - the **user** message is the *whole active line* rendered by
          ``build_compression_transcript(self.current_view(), <range ids>,
          self.read_file)`` — every node in its model-facing form (imports as file
          bodies, committed ``K``s as their summaries) with the selected range
          wrapped in ``<compress_this>``/``</compress_this>`` markers, so the model
          sees the before/after context and never leads with a bare assistant turn.

        Exactly two messages are sent: ``[system, user]``. If the marked span
        renders empty (e.g. the range is a single interrupted zero-token turn),
        ``ValueError`` is raised **before any provider call** — there is nothing to
        compress.

        This is a meta-operation, never a gauge anchor (Q10b): it hands the provider
        a no-op ``on_usage``, so ``last_usage``/``calibration``/``usage_generation``
        are untouched no matter what the provider reports. It mutates no conversation
        state and commits nothing — a cancelled or failed draft leaves the graph
        exactly as it was (Q3); committing is the separate ``commit_compression``.
        """
        range_nodes = self._validate_compress_range(start_id, end_id)
        range_ids = [n.id for n in range_nodes]
        transcript = build_compression_transcript(
            self.current_view(), range_ids, self.read_file
        )
        # A#6 §3: refuse an empty marked span before any provider call — the range
        # rendered no model-facing content (an interrupted zero-token turn), so the
        # <compress_this> pair is adjacent and empty and there is nothing to compress.
        _, _, after_open = transcript.partition(OPEN_COMPRESS_MARKER)
        marked, _, _ = after_open.partition(CLOSE_COMPRESS_MARKER)
        if not marked.strip():
            raise ValueError("nothing to compress: the selected range is empty")

        # A blank/whitespace-only prompt is not a real instruction (several APIs
        # reject an empty system message); fall back to the default (13i).
        if prompt is not None and prompt.strip() != "":
            system_prompt = prompt
        else:
            system_prompt = DEFAULT_COMPRESSION_PROMPT
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcript},
        ]

        # No gauge anchor (Q10b): a no-op on_usage keeps last_usage/calibration/
        # usage_generation untouched no matter what the provider reports.
        def _ignore_usage(_usage: Usage) -> None:
            return None

        async for token in self._provider.stream(messages, self.model, _ignore_usage):
            yield token

    def _calibrate(self, local_sum: int, usage: Usage) -> None:
        """Adopt a provider ``Usage`` as the gauge calibration anchor, if sane.

        Trusts the report only when ``prompt_tokens`` is positive, the local
        estimate is positive, and the two agree within ``CALIBRATION_TOLERANCE``×
        either way. A sane report sets ``last_usage`` and
        ``calibration = prompt_tokens / local_sum``; a bogus one (zero or wildly
        off the local sum) is ignored so a previously trusted anchor survives.
        """
        if usage.prompt_tokens <= 0 or local_sum <= 0:
            return
        ratio = usage.prompt_tokens / local_sum
        if not (1 / CALIBRATION_TOLERANCE <= ratio <= CALIBRATION_TOLERANCE):
            return
        self._last_usage = usage
        self._calibration = ratio
        self._usage_generation += 1

    async def stream(self, assistant_node: Node) -> AsyncIterator[str]:
        """Yield tokens, updating assistant_node.content internally.

        Also anchors the header gauge: the local token estimate of the context
        just built (``tokens.count_messages`` of the exact ``messages`` sent) is
        measured, and an ``on_usage`` callback is handed to the provider. When the
        provider reports a sane ``Usage`` (see ``_calibrate``) it updates
        ``last_usage`` and ``calibration`` for this turn; otherwise both are left
        unchanged. The yielded values stay plain ``str``.

        This generator never touches the ``streaming`` flag and never persists:
        every ending — clean finish, cancel, error (including a pre-stream
        context-build failure, e.g. an unreadable ``/include``d file) — is
        recorded by the caller through ``end_turn``, the single owner of how a
        turn ends. A generator ``finally`` cannot own the flag: a worker
        cancelled before its first tick never runs it, which is exactly the
        stuck-flag bug ``end_turn`` retires.
        """
        context_nodes = [n for n in self.nodes if n is not assistant_node]
        messages = build_context(context_nodes, self._workspace.read_file)
        # AIDEV-NOTE: stamp the per-turn ctx_hash once, at the real generation
        # moment — immutable after (ADR-0016 A#3 §4 tripwire). Write-only under
        # ctx0 (ADR-0017): the reading surfaces that compared it were subtracted.
        assistant_node.meta["ctx_hash"] = hash_context(messages)
        local_sum = tokens.count_messages(messages, self.model)

        def on_usage(usage: Usage) -> None:
            self._calibrate(local_sum, usage)

        async for token in self._provider.stream(messages, self.model, on_usage):
            assistant_node.content += token
            yield token
