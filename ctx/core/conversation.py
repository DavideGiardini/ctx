import asyncio
from collections.abc import AsyncIterator, Callable
from uuid import uuid4

from ctx.core import tokens
from ctx.core.config import get_config
from ctx.core.context import build_context
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

# The default instruction handed to the model when drafting a compression and no
# per-range prompt is supplied (ADR-0016 A#1). In 3b this becomes a read of the
# ``compression.default_prompt`` config default (task 18).
DEFAULT_COMPRESSION_PROMPT = (
    "Preserve the facts, decisions, entities, and open threads needed for the "
    "conversation to continue coherently."
)


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
        # True only while a turn is actively streaming (see stream()); the
        # compression commands (H2) refuse to mutate the graph while it is set.
        self._streaming: bool = False

    @property
    def streaming(self) -> bool:
        """Whether a turn is currently streaming through ``stream()``.

        ``True`` from the moment the stream begins yielding until the stream
        completes, errors, or is cancelled (cleared in a ``finally``). The
        compression commands read it to enforce the H2 invariant: no
        commit/expand/draft may mutate the graph mid-turn.
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

    def current_view(self) -> list[Node]:
        """Project the active line as the linear ``list[Node]`` the UI consumes.

        Walks ``prev_id`` from the active tip back to the root and reverses, so
        the result is root-first. O(active-line length) and deterministic; the
        walk defensively stops on an id missing from the graph or already seen,
        so a malformed chain can never hang the UI. Empty conversation → ``[]``;
        after a ``rewind`` the view is correspondingly shorter (the dropped tail
        stays in ``_graph``).

        Compression folding (ADR-0016, Q1): after the walk, each **maximal
        contiguous run** of view nodes sharing the same non-``None``
        ``compressed_into = K`` is replaced *in place* by the compression node
        ``K`` from the graph. The folded children leave the view and ``K``
        appears despite its ``prev_id=None`` (it lives off the line). Two
        independent compressions yield two ``K`` nodes; a run whose
        ``compressed_into`` points at a node missing from the graph is treated as
        unfolded (defensive, like the walk). The tip may itself be folded — the
        view then ends with ``K`` — but ``_append_to_line`` still chains new
        nodes from the real ``_active_leaf_id``, so appending after a folded tip
        yields ``[…, K, new]``.
        """
        view: list[Node] = []
        seen: set[str] = set()
        cur = self._active_leaf_id
        while cur is not None and cur in self._graph and cur not in seen:
            seen.add(cur)
            node = self._graph[cur]
            view.append(node)
            cur = node.prev_id
        view.reverse()

        resolved: list[Node] = []
        i = 0
        while i < len(view):
            k_id = view[i].compressed_into
            if k_id is not None and k_id in self._graph:
                # Collapse the maximal contiguous run folded into the same K.
                resolved.append(self._graph[k_id])
                while i < len(view) and view[i].compressed_into == k_id:
                    i += 1
            else:
                resolved.append(view[i])
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

    def _append_to_line(self, node: Node) -> None:
        """Append a node onto the active line and advance the tip.

        Sets ``prev_id`` to the current tip and makes the node the new tip — the
        single graph-mutation primitive behind every command that used to do
        ``self.nodes.append(...)``.
        """
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
        """Handle a user message. Returns (user_node, assistant_node)."""
        self._ensure_conversation(text)
        user_node = Node.user(text, self.conversation_id)
        self._append_to_line(user_node)
        # AIDEV-NOTE: persist with the tip at the user node, before the assistant
        # node exists, so a crash mid-stream resumes cleanly on the user turn.
        self.persist()

        assistant_node = Node.assistant(self.conversation_id)
        self._append_to_line(assistant_node)
        return user_node, assistant_node

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
        self._active_leaf_id = self._storage.get_active_leaf(conv_id)
        if self._active_leaf_id is None or self._active_leaf_id not in self._graph:
            self._active_leaf_id = loaded[-1].id
        self.conversation_id = conv_id
        stored_model = self._storage.get_model(conv_id)
        if stored_model:
            # Empty/absent model (e.g. a pre-migration row) keeps the current default.
            self.model = stored_model
        self.conversation_title = next(
            (_derive_title(n.content) for n in self.nodes if n.role == "user"),
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
        Raises ``ValueError`` if ``target_id`` is not on the active line.
        """
        if not any(node.id == target_id for node in self.current_view()):
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
          guard — nested compression is out of scope);
        - **the slice's last node is the active leaf** (the 3a tip guard; a
          distinct, deletable check removed in task 22).

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
        # 3a tip guard (distinct + deletable — removed in task 22): the range must
        # end at the active leaf, so only a suffix ending at the tip is foldable.
        if slice_nodes[-1].id != self._active_leaf_id:
            raise ValueError("compression range must end at the active leaf (tip)")
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
        self._graph[k.id] = k
        for node in slice_nodes:
            node.compressed_into = k.id
        self.persist()
        return k

    def expand_compression(self, k_id: str) -> None:
        """Expand an active compression ``K`` back to its folded children.

        The non-destructive inverse of ``commit_compression``. Validates that
        ``k_id`` names a compression node that is currently **active** — some node
        still carries ``compressed_into == k_id`` — and that no turn is streaming
        (H2); raises ``ValueError`` otherwise.

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
        # Active iff some node still folds into it; an already-expanded K has no
        # child pointing at it (3a resolution is pointer-based).
        if not any(n.compressed_into == k_id for n in self._graph.values()):
            raise ValueError(f"compression is not active: {k_id}")
        e = Node.expand(k_id, self._active_leaf_id, self.conversation_id)
        self._graph[e.id] = e
        for child_id in k.meta["range"]:
            child = self._graph.get(child_id)
            if child is not None:
                child.compressed_into = None
        self.persist()

    async def draft_compression(
        self, start_id: str, end_id: str, prompt: str | None = None
    ) -> AsyncIterator[str]:
        """Stream an AI-drafted summary of a contiguous range (a meta-operation).

        Validates the range via ``_validate_compress_range`` (the same guards as
        ``commit_compression`` — streaming/H2, contiguous view slice, flat, 3a tip
        guard), raising ``ValueError`` on any failure **before any provider call**.

        Renders **only the range** through ``build_context`` with the core's own
        file loader, so each node contributes exactly its model-facing form (a raw
        import → the full file body; an already-summarized node → its summary; never
        the "Included:" label) — the Q10c invariant that the draft sees what the
        model sees. One final user message carrying the instruction (``prompt`` when
        given, else ``DEFAULT_COMPRESSION_PROMPT``) is appended, and the result is
        streamed via the provider on the active model.

        This is a meta-operation, never a gauge anchor (Q10b): it hands the provider
        a no-op ``on_usage``, so ``last_usage``/``calibration``/``usage_generation``
        are untouched no matter what the provider reports. It mutates no conversation
        state and commits nothing — a cancelled or failed draft leaves the graph
        exactly as it was (Q3); committing is the separate ``commit_compression``.
        """
        range_nodes = self._validate_compress_range(start_id, end_id)
        messages = build_context(range_nodes, self._workspace.read_file)
        instruction = prompt if prompt is not None else DEFAULT_COMPRESSION_PROMPT
        messages.append({"role": "user", "content": instruction})

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
        """
        context_nodes = [n for n in self.nodes if n is not assistant_node]
        messages = build_context(context_nodes, self._workspace.read_file)
        local_sum = tokens.count_messages(messages, self.model)

        def on_usage(usage: Usage) -> None:
            self._calibrate(local_sum, usage)

        self._streaming = True
        try:
            async for token in self._provider.stream(messages, self.model, on_usage):
                assistant_node.content += token
                yield token
        except asyncio.CancelledError:
            self.persist()
            raise
        except Exception:
            self.persist()
            raise
        else:
            self.persist()
        finally:
            self._streaming = False
