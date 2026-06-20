import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from ctx.core.context import build_context
from ctx.core.log import logger
from ctx.core.provider import Provider
from ctx.core.storage import StoragePort
from ctx.core.workspace import Workspace
from ctx.models.nodes import Node

DEFAULT_MODEL = "openrouter/google/gemma-4-26b-a4b-it"
MAX_TITLE_LENGTH = 50


@dataclass
class TokenUsage:
    """Token consumption for the current conversation.

    ``fraction`` is the raw ``total / limit`` ratio (it may exceed 1.0); the
    view layer is responsible for clamping it for display.
    """

    per_node: dict[str, int]
    total: int
    limit: int
    fraction: float


class ConversationCore:
    """Deep module: owns conversation state, commands, and streaming lifecycle."""

    def __init__(
        self,
        storage: StoragePort,
        provider: Provider,
        workspace: Workspace,
    ) -> None:
        self._storage = storage
        self._provider = provider
        self._workspace = workspace
        self.nodes: list[Node] = []
        self.conversation_id: str = ""
        self.conversation_title: str = ""
        self.model: str = DEFAULT_MODEL

    def setup(self) -> None:
        self._workspace.ensure()
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

    def set_model(self, model: str) -> Node:
        self.model = model
        node = Node(role="application", content=f"Model set to: {model}", node_type="system")
        self.nodes.append(node)
        self.persist()
        return node

    async def check_connectivity(self, model: str) -> Node:
        ok, msg = await self._provider.check_connectivity(model)
        if ok:
            node = Node(role="application", content=f"✔ Connected to {model}", node_type="system")
        else:
            node = Node(
                role="application",
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
        # "Big S" — the root LLM System Prompt node
        root_system = Node(
            role="system",
            content="You are a helpful assistant.",
            node_type="system",
        )
        self.nodes.append(root_system)
        app_node = Node(
            role="application",
            content="Started a new conversation.",
            node_type="system",
        )
        self.nodes.append(app_node)
        return app_node

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
            try:
                raw = self._workspace.read_file(path)
            except (OSError, ValueError) as exc:
                logger.warning("include_files failed to read | path=%s | error=%s", path, exc)
                raw = ""
            node = Node(
                role="context",
                content=f"Included: {path}",
                node_type="context",
                conversation_id=self.conversation_id,
                meta={
                    "source_path": path,
                    "prompt": "",
                    "raw_content": raw,
                    "output": raw,
                },
            )
            self.nodes.append(node)
            nodes.append(node)
        self.persist()
        return nodes

    def add_system_message(self, content: str) -> Node:
        node = Node(role="application", content=content, node_type="system")
        self.nodes.append(node)
        return node

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token count estimate for non-assistant nodes.

        Uses a simple heuristic (≈ 4 chars per token) so we can display a
        context-window percentage without pulling in a heavy tokenizer.
        """
        return max(1, len(text) // 4)

    def _node_tokens(self, node: Node) -> int:
        """Token count for a single node: the real count when known, else an estimate."""
        if node.token_count is not None:
            return node.token_count
        return self.estimate_tokens(node.content)

    def token_usage(self) -> TokenUsage:
        """Compute current token consumption against the model's context window."""
        per_node = {node.id: self._node_tokens(node) for node in self.nodes}
        total = sum(per_node.values())
        limit = self._provider.context_window_limit(self.model)
        fraction = (total / limit) if limit > 0 else 0.0
        return TokenUsage(per_node=per_node, total=total, limit=limit, fraction=fraction)

    async def stream(self, assistant_node: Node) -> AsyncIterator[str]:
        """Yield tokens, updating assistant_node.content internally.

        When the LLM stream finishes we capture the final ``usage`` dict and
        store the completion token count on the node so the UI can render the
        context bar in a single, cheap update.
        """
        messages = build_context(self.nodes[:-1], self._workspace.read_file)
        try:
            async for chunk in self._provider.stream(messages, self.model):
                assistant_node.content += chunk.token
                if chunk.usage is not None:
                    completion_tokens = chunk.usage.get("completion_tokens")
                    if completion_tokens is not None:
                        assistant_node.token_count = int(completion_tokens)
                        logger.info(
                            "stream usage | completion_tokens=%s", completion_tokens
                        )
                yield chunk.token
        except asyncio.CancelledError:
            self.persist()
            raise
        except Exception:
            self.persist()
            raise
        else:
            self.persist()
