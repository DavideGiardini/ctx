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
        self.nodes: list[Node] = []
        self.conversation_id: str = ""
        self.conversation_title: str = ""
        self.model: str = self._default_model
        # Provider-anchored token accounting for the header gauge. Both stay
        # None until a streamed turn reports usage that passes the sanity check.
        self._last_usage: Usage | None = None
        self._calibration: float | None = None
        # Monotonically bumped each time _calibrate adopts a usage. Lets the UI
        # detect "a fresh anchor landed this turn" without depending on the
        # provider minting a new Usage object per turn (ADR 0015 #2).
        self._usage_generation: int = 0

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
        self._storage.save(
            self.conversation_id,
            self.conversation_title,
            self.nodes,
            model=self.model,
        )

    def submit(self, text: str) -> tuple[Node, Node]:
        """Handle a user message. Returns (user_node, assistant_node)."""
        self._ensure_conversation(text)
        user_node = Node.user(text, self.conversation_id)
        self.nodes.append(user_node)
        self.persist()

        assistant_node = Node.assistant(self.conversation_id)
        self.nodes.append(assistant_node)
        return user_node, assistant_node

    def set_model(self, model: str) -> Node:
        self.model = model
        node = Node.system(f"Model set to: {model}", self.conversation_id)
        self.nodes.append(node)
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
        self.nodes.append(node)
        self.persist()
        return node

    def new_conversation(self) -> Node:
        self.persist()
        self.nodes = []
        self.conversation_id = ""
        self.conversation_title = ""
        self.model = self._default_model
        return Node.system("Started a new conversation.")

    def resume_conversation(self, conv_id: str) -> list[Node]:
        loaded = self._storage.load(conv_id)
        if not loaded:
            # Unknown id: leave the in-progress conversation intact.
            return []
        self.nodes = loaded
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
            self.nodes.append(node)
            nodes.append(node)
        self.persist()
        return nodes

    def add_system_message(self, content: str) -> Node:
        node = Node.system(content, self.conversation_id)
        self.nodes.append(node)
        self.persist()
        return node

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
