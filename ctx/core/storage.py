import json
import sqlite3
from datetime import UTC, datetime
from typing import Protocol

from ctx.models.nodes import Node


class StoragePort(Protocol):
    """Seam for conversation persistence."""

    def init(self) -> None: ...
    def save(
        self,
        conversation_id: str,
        title: str,
        nodes: list[Node],
        *,
        model: str = "",
        active_leaf_id: str | None = None,
    ) -> None: ...
    def load(self, conversation_id: str) -> list[Node]: ...
    def get_title(self, conversation_id: str) -> str | None: ...
    def get_model(self, conversation_id: str) -> str | None: ...
    def get_active_leaf(self, conversation_id: str) -> str | None: ...
    def list(self) -> list[dict]: ...
    def get_last(self) -> str | None: ...

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    active_leaf_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    node_type TEXT NOT NULL DEFAULT 'message',
    meta TEXT NOT NULL DEFAULT '{}',
    prev_id TEXT,
    compressed_into TEXT,
    created_seq INTEGER NOT NULL DEFAULT 0
);
"""


class ConversationRepository:
    """Deep module: owns SQLite persistence, schema, and JSON serialization.

    The interface is small (save, load, list, init, get_last) while the
    implementation hides all SQL mechanics and connection lifecycle.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
            self._migrate(conn)
            conn.commit()
        finally:
            conn.close()

    def _migrate(self, conn: sqlite3.Connection) -> None:
        # SQLite has no ADD COLUMN IF NOT EXISTS; add columns that DBs predating a
        # given feature lack. New DBs already have them from _SCHEMA. Runs inside
        # init()'s single transaction, so schema change + data backfill commit
        # atomically.
        conv_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(conversations)")
        }
        if "model" not in conv_columns:
            conn.execute(
                "ALTER TABLE conversations ADD COLUMN model TEXT NOT NULL DEFAULT ''"
            )

        # Append-only node graph edge columns (ADR-0016).
        node_columns = {row[1] for row in conn.execute("PRAGMA table_info(nodes)")}
        if "prev_id" not in node_columns:
            conn.execute("ALTER TABLE nodes ADD COLUMN prev_id TEXT")
        if "compressed_into" not in node_columns:
            conn.execute("ALTER TABLE nodes ADD COLUMN compressed_into TEXT")
        # AIDEV-NOTE: gate the one-time backfill on the COLUMN being absent (the
        # marker of a pre-graph DB), NOT on a per-conversation NULL leaf — a
        # conversation legitimately saved with active_leaf_id=None must not have
        # its prev_id chain rewritten on later inits. ALTER + backfill share
        # init()'s transaction, so a crash rolls back both (no idempotency guard).
        if "active_leaf_id" not in conv_columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN active_leaf_id TEXT")
            self._backfill_graph(conn)

        # Monotonic creation order (ADR-0016 A#2). Gate the one-time backfill on the
        # COLUMN being absent (the pre-3b marker), like the graph backfill above.
        if "created_seq" not in node_columns:
            conn.execute(
                "ALTER TABLE nodes ADD COLUMN created_seq INTEGER NOT NULL DEFAULT 0"
            )
            self._backfill_created_seq(conn)

    def _backfill_graph(self, conn: sqlite3.Connection) -> None:
        # Chain each pre-graph conversation's nodes into a prev_id line by rowid
        # and point active_leaf_id at the last node — the degenerate single-path
        # case of the graph (ADR-0016).
        conv_ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM conversations WHERE active_leaf_id IS NULL"
            )
        ]
        for conv_id in conv_ids:
            node_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM nodes WHERE conversation_id = ? ORDER BY rowid",
                    (conv_id,),
                )
            ]
            prev: str | None = None
            for node_id in node_ids:
                conn.execute(
                    "UPDATE nodes SET prev_id = ? WHERE id = ?", (prev, node_id)
                )
                prev = node_id
            if node_ids:
                conn.execute(
                    "UPDATE conversations SET active_leaf_id = ? WHERE id = ?",
                    (node_ids[-1], conv_id),
                )

    def _backfill_created_seq(self, conn: sqlite3.Connection) -> None:
        # Assign per-conversation 1-based seqs in rowid (insertion) order — valid
        # because in-memory insertion order round-trips through the full-replace
        # save() (insertion order → rowid → load order), so rowid order == creation
        # order (ADR-0016 A#3 §1). Matches a fresh conversation's counter (starts 1).
        conv_ids = [row[0] for row in conn.execute("SELECT id FROM conversations")]
        for conv_id in conv_ids:
            node_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM nodes WHERE conversation_id = ? ORDER BY rowid",
                    (conv_id,),
                )
            ]
            for seq, node_id in enumerate(node_ids, start=1):
                conn.execute(
                    "UPDATE nodes SET created_seq = ? WHERE id = ?", (seq, node_id)
                )

    def save(
        self,
        conversation_id: str,
        title: str,
        nodes: list[Node],
        *,
        model: str = "",
        active_leaf_id: str | None = None,
    ) -> None:
        # AIDEV-NOTE: persist the FULL node set (every line + folded children),
        # not just the active view — else abandoned tails don't survive and rewind
        # turns destructive (ADR-0016). active_leaf_id is the tip, which after a
        # rewind is not the last-created node. Id-less breadcrumbs are skipped.
        now = datetime.now(UTC).isoformat()
        persistable = [node for node in nodes if node.conversation_id]
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE conversations SET title = ?, model = ?, "
                    "active_leaf_id = ?, updated_at = ? WHERE id = ?",
                    (title, model, active_leaf_id, now, conversation_id),
                )
            elif persistable:
                conn.execute(
                    "INSERT INTO conversations "
                    "(id, title, model, active_leaf_id, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (conversation_id, title, model, active_leaf_id, now, now),
                )
            else:
                # A brand-new conversation with nothing to persist must not create a
                # row, so it can't leak into list()/get_last() (contract C18).
                return

            conn.execute(
                "DELETE FROM nodes WHERE conversation_id = ?", (conversation_id,)
            )
            for node in persistable:
                conn.execute(
                    "INSERT INTO nodes "
                    "(id, conversation_id, role, content, node_type, meta, "
                    "prev_id, compressed_into, created_seq) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        node.id,
                        node.conversation_id,
                        node.role,
                        node.content,
                        node.node_type,
                        json.dumps(node.meta),
                        node.prev_id,
                        node.compressed_into,
                        node.created_seq,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def load(self, conversation_id: str) -> list[Node]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, conversation_id, role, content, node_type, meta, "
                "prev_id, compressed_into, created_seq "
                "FROM nodes WHERE conversation_id = ? ORDER BY rowid",
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
                prev_id=row[6],
                compressed_into=row[7],
                created_seq=row[8],
            )
            nodes.append(node)
        return nodes

    def get_title(self, conversation_id: str) -> str | None:
        """The stored title for a conversation, or ``None`` if it was never saved.

        Symmetric with ``get_model``: an existing row with an empty title returns
        ``""`` (a real, authoritative value the caller keeps as-is), a row that
        was never created returns ``None`` (nothing stored, derive instead).
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def get_model(self, conversation_id: str) -> str | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT model FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def get_active_leaf(self, conversation_id: str) -> str | None:
        """The stored active tip for a conversation (its ``active_leaf_id``).

        ``None`` for an unknown conversation or one whose tip was never recorded
        (a pre-migration edge the backfill left NULL, e.g. a node-less row); the
        caller (``ConversationCore.resume_conversation``) falls back to the last
        node by load order in that case. Symmetric with ``get_model``.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT active_leaf_id FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def list(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, title, updated_at FROM conversations "
                "ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
        finally:
            conn.close()

        return [{"id": row[0], "title": row[1], "updated_at": row[2]} for row in rows]

    def get_last(self) -> str | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id FROM conversations ORDER BY updated_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None
