import json
import sqlite3
from datetime import datetime, timezone

from ctx.models.nodes import Node
from ctx.core.log import logger
from ctx.core.workspace import get_db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    node_type TEXT NOT NULL DEFAULT 'message',
    meta TEXT NOT NULL DEFAULT '{}'
);
"""


def _connect() -> sqlite3.Connection:
    db = get_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = _connect()
    conn.executescript(_SCHEMA)
    conn.close()


def save_conversation(
    conversation_id: str,
    title: str,
    nodes: list[Node],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, conversation_id),
            )
        else:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, title, now, now),
            )

        conn.execute(
            "DELETE FROM nodes WHERE conversation_id = ?", (conversation_id,)
        )
        for node in nodes:
            # Skip system messages
            if not node.conversation_id:
                continue
            conn.execute(
                "INSERT INTO nodes (id, conversation_id, role, content, node_type, meta) VALUES (?, ?, ?, ?, ?, ?)",
                (node.id, node.conversation_id, node.role, node.content, node.node_type, json.dumps(node.meta)),
            )
        conn.commit()
    finally:
        conn.close()


def load_conversation(conversation_id: str) -> list[Node]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, conversation_id, role, content, node_type, meta FROM nodes WHERE conversation_id = ? ORDER BY rowid",
            (conversation_id,),
        ).fetchall()
    finally:
        conn.close()

    nodes = []
    for row in rows:
        node = Node(
            id=row[0],
            conversation_id=row[1],
            role=row[2],
            content=row[3],
            node_type=row[4],
            meta=json.loads(row[5]),
        )
        nodes.append(node)
    return nodes


def list_conversations() -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, title, updated_at FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()

    return [{"id": row[0], "title": row[1], "updated_at": row[2]} for row in rows]


def get_last_conversation_id() -> str | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id FROM conversations ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None