"""Shared pytest fixtures for the ctx test suite.

These are the canonical building blocks every module's tests reuse, so each
test session wires its dependencies the same way rather than reinventing them.
All fixtures lean on the architecture's existing seams (TestProvider, the
temp-dir Workspace, the injectable storage path, the pure build_context loader).
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from ctx.core.provider import TestProvider
from ctx.core.storage import ConversationRepository
from ctx.core.workspace import Workspace
from ctx.models.nodes import Node


@pytest.fixture
def make_node() -> Callable[..., Node]:
    """Build a Node with sensible defaults; override any field per call.

    Defaults to a persistable user message (conversation_id set), since the
    storage layer skips nodes without a conversation_id.
    """

    def _make(
        role: str = "user",
        content: str = "hello",
        *,
        node_type: str = "message",
        conversation_id: str = "conv-1",
        meta: dict | None = None,
    ) -> Node:
        return Node(
            role=role,
            content=content,
            node_type=node_type,
            conversation_id=conversation_id,
            meta=meta if meta is not None else {},
        )

    return _make


@pytest.fixture
def stub_loader() -> Callable[[dict[str, str]], Callable[[str], str]]:
    """Factory for an in-memory file loader to inject into build_context.

    Returns a builder: pass a {path: content} mapping and get back a
    ``load_file(path) -> str`` callable. Unknown paths raise FileNotFoundError
    (a subclass of OSError), matching what a real filesystem loader raises so
    the error-handling path is exercisable.
    """

    def _build(files: dict[str, str]) -> Callable[[str], str]:
        def _load(path: str) -> str:
            if path not in files:
                raise FileNotFoundError(path)
            return files[path]

        return _load

    return _build


@pytest.fixture
def repo(tmp_path: Path) -> ConversationRepository:
    """A ConversationRepository backed by a temp-file SQLite DB, initialized.

    NOTE: we deliberately do *not* use ":memory:" here. ConversationRepository
    opens a fresh connection per method (storage.py), and an in-memory SQLite
    database is private to its connection — so ":memory:" would give init(),
    save(), and load() three separate empty databases. A temp-file path shares
    state across calls. (Flagged for the storage-module test session.)
    """
    repository = ConversationRepository(str(tmp_path / "conversations.db"))
    repository.init()
    return repository


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """A Workspace rooted in a temp dir, with .ctx/ and .ctx/context/ created."""
    ws = Workspace(tmp_path)
    ws.ensure()
    return ws


@pytest.fixture
def test_provider() -> Callable[[list[str]], TestProvider]:
    """Factory for a TestProvider that streams the given tokens."""

    def _build(tokens: list[str]) -> TestProvider:
        return TestProvider(tokens)

    return _build
