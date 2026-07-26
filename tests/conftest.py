"""Shared pytest fixtures for the ctx test suite.

These are the canonical building blocks every module's tests reuse, so each
test session wires its dependencies the same way rather than reinventing them.
All fixtures lean on the architecture's existing seams (TestProvider, the
temp-dir Workspace, the injectable storage path, the pure build_context loader).
"""

import asyncio
from collections.abc import Callable
from itertools import count
from pathlib import Path

import pytest

from ctx.core.provider import Provider, TestProvider, Usage
from ctx.core.storage import ConversationRepository
from ctx.core.workspace import Workspace
from ctx.models.nodes import Node
from ctx.ui.app import ChatApp


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
def repo_factory(tmp_path: Path) -> Callable[[], ConversationRepository]:
    """Factory making independent, initialized ConversationRepositories.

    Each call returns a repository on its own temp-file DB, so a single test can
    build two unrelated conversation stores (e.g. comparing two independently
    constructed cores). The singleton ``repo`` fixture shares one DB and cannot.
    """
    seq = count()

    def _build() -> ConversationRepository:
        repository = ConversationRepository(
            str(tmp_path / f"conversations-{next(seq)}.db")
        )
        repository.init()
        return repository

    return _build


@pytest.fixture
def workspace_factory(tmp_path: Path) -> Callable[[], Workspace]:
    """Factory making independent Workspaces, each rooted in its own temp dir."""
    seq = count()

    def _build() -> Workspace:
        root = tmp_path / f"ws-{next(seq)}"
        root.mkdir()
        ws = Workspace(root)
        ws.ensure()
        return ws

    return _build


class _VaryingProvider:
    """A provider whose streamed tokens and reported usage vary per ``stream`` call.

    Constructed with a list of ``(tokens, usage)`` pairs — one per expected turn.
    The Nth ``stream`` call yields the Nth pair's tokens and, when that pair's
    usage is not ``None`` and a callback was supplied, fires ``on_usage`` once with
    it. Models a real provider whose per-turn usage differs across turns on the
    same core (e.g. a sane turn followed by a no-usage or bogus turn).
    """

    def __init__(self, turns: list[tuple[list[str], Usage | None]]) -> None:
        self._turns = turns
        self._call = 0

    async def stream(self, messages, model, on_usage=None, tools=None, on_tool_calls=None):  # type: ignore[no-untyped-def]
        tokens, usage = self._turns[self._call]
        self._call += 1
        for token in tokens:
            yield token
        if usage is not None and on_usage is not None:
            on_usage(usage)

    async def check_connectivity(self, model):  # type: ignore[no-untyped-def]
        return (True, "ok")


@pytest.fixture
def varying_provider() -> Callable[[list[tuple[list[str], Usage | None]]], _VaryingProvider]:
    """Factory for a provider whose usage varies per turn (see ``_VaryingProvider``)."""

    def _build(turns: list[tuple[list[str], Usage | None]]) -> _VaryingProvider:
        return _VaryingProvider(list(turns))

    return _build


@pytest.fixture
def test_provider() -> Callable[..., TestProvider]:
    """Factory for a TestProvider that streams the given tokens.

    Pass an optional ``usage`` to have the provider report exact token counts
    via the ``on_usage`` callback after streaming (used by calibration tests);
    omit it (the default) for a provider that reports no usage.
    """

    def _build(tokens: list[str], usage: Usage | None = None) -> TestProvider:
        return TestProvider(tokens, usage)

    return _build


# ---------------------------------------------------------------------------
# Shared provider doubles.
#
# These are the canonical hand-rolled providers the suite reuses instead of each
# module re-declaring its own copy. They are a *shared surface*: import them by
# name (``from conftest import BlockingProvider``) and give them real docstrings.
# Both core tests (construct, then pass to ``ConversationCore(...)``) and Pilot
# tests (hot-swap onto a running app via ``app.core._provider``) use one class
# with one signature.
# ---------------------------------------------------------------------------


class BlockingProvider:
    """Yields its ``before`` tokens, then blocks on ``gate`` before a final ``AFTER``.

    Models an LLM suspended mid-stream, so the task consuming the stream (a turn
    worker or a draft worker) stays live (RUNNING) while a test drives the UI or
    probes ``core.streaming``. Construct with the tokens to emit before blocking
    and an ``asyncio.Event`` gate; release the stream by setting the gate
    (``gate.set()``). The trailing ``AFTER`` is normally never reached — tests
    close/cancel the stream while it is blocked.

    DEADLOCK WARNING: never use this provider for a *setup* turn that is awaited
    to completion. A turn drained to its end against a gate that is never set
    suspends forever and deadlocks the entire pytest run. Prime the line with the
    default scripted provider (``TestProvider``) and swap the blocking one in only
    for the single turn under test.
    """

    def __init__(self, before: list[str], gate: asyncio.Event) -> None:
        self._before = before
        self._gate = gate

    async def stream(self, messages, model=None, on_usage=None, tools=None, on_tool_calls=None):  # type: ignore[no-untyped-def]
        for token in self._before:
            yield token
        await self._gate.wait()
        yield "AFTER"

    async def check_connectivity(self, model=None):  # type: ignore[no-untyped-def]
        return (True, "ok")


@pytest.fixture
def app_factory(
    repo: ConversationRepository, workspace: Workspace
) -> Callable[..., ChatApp]:
    """Factory constructing a ChatApp wired to the shared ``repo``/``workspace``.

    The single home for the Pilot tests' app construction — formerly an ``_app``
    factory copy in every ``test_app_*.py`` file. Call it with no arguments for the
    common case: a ``TestProvider(["ok"])`` streaming one canned token. Override
    either the whole provider or just the default provider's script:

    * ``app_factory(provider=some_provider)`` — inject a specific provider double
      (e.g. a ``BlockingProvider`` or a compression-payload ``RecordingProvider``).
    * ``app_factory(tokens=[...], usage=Usage(...))`` — build the default
      ``TestProvider`` with a custom token script and/or reported usage (the
      gauge / weights / draft-compression variants).

    ``provider`` takes precedence over ``tokens``/``usage`` when both are given.
    Each call returns a fresh ChatApp over the *same* shared repo/workspace, so a
    single test can build two apps against one store (e.g. expand-survives-restart).
    """

    def _build(
        provider: Provider | None = None,
        *,
        tokens: list[str] | None = None,
        usage: Usage | None = None,
    ) -> ChatApp:
        if provider is None:
            provider = TestProvider(list(tokens) if tokens is not None else ["ok"], usage)
        return ChatApp(provider=provider, workspace=workspace, storage=repo)

    return _build


class RecordingProvider:
    """Canned provider that records the messages of its most recent ``stream`` call.

    After a turn, ``captured`` holds the exact messages list handed to the last
    ``stream`` call (``None`` if never invoked) and ``called`` flags whether it ran
    at all — so a test can assert precisely what a turn sends the model (e.g. that a
    committed summary, not its folded children, reaches the provider). Streams the
    given tokens verbatim.
    """

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = list(tokens)
        self.called = False
        self.captured: list[dict] | None = None

    async def stream(self, messages, model=None, on_usage=None, tools=None, on_tool_calls=None):  # type: ignore[no-untyped-def]
        self.called = True
        self.captured = messages
        for token in self._tokens:
            yield token

    async def check_connectivity(self, model=None):  # type: ignore[no-untyped-def]
        return (True, "ok")


class ErroringProvider:
    """Provider that raises mid-stream, so a consuming worker takes its failure path.

    The unreachable ``yield`` after the ``raise`` is what makes ``stream`` an async
    generator; the ``RuntimeError`` surfaces on the first iteration.
    """

    async def stream(self, messages, model=None, on_usage=None, tools=None, on_tool_calls=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")
        yield ""  # pragma: no cover — makes this an async generator

    async def check_connectivity(self, model=None):  # type: ignore[no-untyped-def]
        return (True, "ok")
