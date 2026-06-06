from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class Node:
    id: str = field(default_factory=lambda: uuid4().hex)
    role: str = ""
    content: str = ""
    node_type: str = "message"
    meta: dict = field(default_factory=dict)