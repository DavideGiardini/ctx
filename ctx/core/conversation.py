from collections.abc import AsyncIterator
from typing import Protocol
from uuid import uuid4

from ctx.core.context import build_context
from ctx.core.provider import Provider, check_connectivity
from ctx.core.workspace import ensure_workspace
from ctx.models.nodes import Node

DEFAULT_MODEL = "openrouter/google/gemma-4-26b-a4b-it"
MAX_TITLE_LENGTH = 50


class StoragePort(Protocol):
    """Seam for conversation persistence."""

    def init(self) -> None: ...
    def save(self, conversation_id: str, title: str, nodes: list[Node]) -> None: ...
    def load(self, conversation_id: str) -> list[Node]: ...


class ConversationCore:
    """Deep module: owns conversation state, commands, and streaming lifecycle."""

    def __init__(self, storage: StoragePort, provider: Provider) -> None:
        self._storage = storage
        self._provider = provider
        self.nodes: list[Node] = []
        self.conversation_id: str = ""
        self.conversation_title: str = ""
        self.model: str = DEFAULT_MODEL

    def setup(self) -> None:
        ensure_workspace()
        self._storage.init()

    def _ensure_conversation(self, first_message: str) -> None:
        if not self.conversation_id:
            self.conversation_id = uuid4().hex
        if not self.conversation_title:
            self.conversation_title = first_message[:MAX_TITLE_LENGTH].replace("\n", " ")

    def persist(self) -> None:
        if not self.conversation_id:
            return
        self._storage.save(self.conversation_id, self.conversation_title, self.nodes)

    def submit(self, text: str) -> tuple[Node, Node]:
        """Handle a user message. Returns (user_node, assistant_node)."""
        self._ensure_conversation(text)
        user_node = Node(role="user", content=text, conversation_id=self.conversation_id)
        self.nodes.append(user_node)
        self.persist()

        assistant_node = Node(role="assistant", content="", conversation_id=self.conversation_id)
        self.nodes.append(assistant_node)
        return user_node, assistant_node

    def query_model(self) -> Node:
        node = Node(role="system", content=f"Current model: {self.model}", node_type="system")
        self.nodes.append(node)
        return node

    def set_model(self, model: str) -> Node:
        self.model = model
        node = Node(role="system", content=f"Model set to: {model}", node_type="system")
        self.nodes.append(node)
        self.persist()
        return node

    async def check_connectivity(self, model: str) -> Node:
        ok, msg = await check_connectivity(model)
        if ok:
            node = Node(role="system", content=f"✔ Connected to {model}", node_type="system")
        else:
            node = Node(
                role="system",
                content=(
                    f"⚠ Could not verify connectivity to {model} — "
                    f"the model may still work. Error: {msg}"
                ),
                node_type="system",
            )
        self.nodes.append(node)
        return node

    def new_conversation(self) -> Node:
        self.persist()
        self.nodes = []
        self.conversation_id = ""
        self.conversation_title = ""
        self.model = DEFAULT_MODEL
        return Node(role="system", content="Started a new conversation.", node_type="system")

    def resume_conversation(self, conv_id: str) -> list[Node]:
        self.nodes = self._storage.load(conv_id)
        if not self.nodes:
            return []
        self.conversation_id = conv_id
        self.conversation_title = next(
            (
                n.content[:MAX_TITLE_LENGTH].replace("\n", " ")
                for n in self.nodes
                if n.role == "user"
            ),
            "",
        )
        return self.nodes

    def include_files(self, paths: list[str]) -> list[Node]:
        self._ensure_conversation("")
        nodes: list[Node] = []
        for path in paths:
            node = Node(
                role="context",
                content=f"Included: {path}",
                node_type="context",
                conversation_id=self.conversation_id,
                meta={"source_path": path},
            )
            self.nodes.append(node)
            nodes.append(node)
        self.persist()
        return nodes

    def add_system_message(self, content: str) -> Node:
        node = Node(role="system", content=content, node_type="system")
        self.nodes.append(node)
        return node

    async def stream(self, assistant_node: Node) -> AsyncIterator[str]:
        """Yield tokens, updating assistant_node.content internally."""
        messages = build_context(self.nodes[:-1])
        try:
            async for token in self._provider.stream(messages, self.model):
                assistant_node.content += token
                yield token
        except Exception:
            self.persist()
            raise
        else:
            self.persist()
