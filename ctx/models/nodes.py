from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class Node:
    id: str = field(default_factory=lambda: uuid4().hex)
    conversation_id: str = ""
    role: str = ""
    content: str = ""
    node_type: str = "message"
    meta: dict = field(default_factory=dict)

    # ── Context 3-split helpers ──
    # These are stored in meta so they are JSON-serialised for SQLite.  The
    # properties below give the UI a clean API so it doesn't hardcode dict keys.

    @property
    def prompt(self) -> str:
        """The prompt used for the import / compression (Top split)."""
        return str(self.meta.get("prompt", ""))

    @property
    def raw_content(self) -> str:
        """The raw text of the imported document (Center split)."""
        return str(self.meta.get("raw_content", ""))

    @property
    def output(self) -> str:
        """The extracted / summarised text passed to the LLM (Bottom split)."""
        return str(self.meta.get("output", ""))

    @property
    def token_count(self) -> int | None:
        """Token count as reported by the provider (or None if unknown)."""
        val = self.meta.get("token_count")
        if val is None:
            return None
        return int(val)

    @token_count.setter
    def token_count(self, value: int | None) -> None:
        self.meta["token_count"] = value
