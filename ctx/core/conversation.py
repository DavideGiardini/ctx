import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from ctx.core.config import get_config
from ctx.core.context import build_context
from ctx.core.provider import Provider
from ctx.core.storage import StoragePort
from ctx.core.workspace import Workspace
from ctx.models.nodes import Node

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

    async def stream(self, assistant_node: Node) -> AsyncIterator[str]:
        """Yield tokens, updating assistant_node.content internally."""
        context_nodes = [n for n in self.nodes if n is not assistant_node]
        messages = build_context(context_nodes, self._workspace.read_file)
        try:
            async for token in self._provider.stream(messages, self.model):
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
