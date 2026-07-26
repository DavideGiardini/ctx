"""The window wall: a fetched page that would overrun the model's context window.

Contract: tests/specs/conversation-window-wall.md (items C1-C6).

Three tests, one per clause of the acceptance criterion: a refusal under a known small
window (C1-C4), the untouched page on the success path (C5), and the guard skipped when
litellm has no window metadata for the model (C6).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ctx.core import config as ctx_config
from ctx.core import tokens as ctx_tokens
from ctx.core.conversation import ConversationCore
from ctx.core.provider import ScriptedRound, ToolCall
from ctx.core.provider import TestProvider as ScriptedProvider
from ctx.core.search import TestSearch as CannedSearch
from ctx.models.nodes import Node

REFUSAL_PHRASE = "too large for the remaining context window"

BIG_PAGE_URL = "https://blog.rust-lang.org/2024/09/05/Rust-1.81.0.html"
SMALL_PAGE_URL = "https://docs.python.org/3/whatsnew/3.12.html"

ANSWER_TOKENS = [
    "I could not read that page, ",
    "so here is what I can say from the release notes I already have.",
]
ANSWER_TEXT = "".join(ANSWER_TOKENS)


@pytest.fixture
def config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Isolate config from the developer's ~/.config/ctx."""
    cfg_dir = tmp_path / "ctx-config"
    cfg_dir.mkdir()
    monkeypatch.setattr(ctx_config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(ctx_config, "CONFIG_PATH", cfg_dir / "config.json")
    return cfg_dir


@pytest.fixture
def search_available(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Config isolated *and* a backend key present, so the web tools are offered."""
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key-not-real")
    return config_dir


def pin_window(monkeypatch: pytest.MonkeyPatch, window: int | None) -> None:
    """Make the window lookup deterministic (`None` = litellm has no metadata)."""

    def _model_window(model: str) -> int | None:
        return window

    monkeypatch.setattr(ctx_tokens, "model_window", _model_window)


def oversized_page() -> str:
    """A page far bigger than a 4000-token window, with an identifiable tail."""
    body = (
        "Rust 1.81.0 stabilises the Error trait in core, ships a new sort "
        "implementation in the standard library, and lands the #[expect(lint)] "
        "attribute for expected lints. "
    ) * 8000
    return f"# Announcing Rust 1.81.0\n\n{body}\n<!-- end of release notes -->\n"


def modest_page() -> str:
    """A page that fits comfortably in any real window, tail marker included."""
    return (
        "# What's New In Python 3.12\n\n"
        "Python 3.12 improves f-string parsing (PEP 701), adds a type parameter "
        "syntax for generics (PEP 695), and gives per-interpreter GILs a public "
        "C API (PEP 684). The error messages for common mistakes, such as "
        "misspelling a module attribute, now suggest the intended name.\n\n"
        "## Deprecations\n\n"
        "distutils has been removed; use setuptools or packaging instead.\n"
        "<!-- end of what's new -->\n"
    )


def fetch_then_answer(url: str) -> ScriptedProvider:
    """Round 1 calls fetch(url); round 2 settles with the answer text."""
    return ScriptedProvider(
        rounds=[
            ScriptedRound(
                tokens=[],
                tool_calls=[
                    ToolCall(
                        id="call_fetch_release_notes",
                        name="fetch",
                        arguments=json.dumps({"url": url}),
                    )
                ],
            ),
            ScriptedRound(tokens=ANSWER_TOKENS),
        ]
    )


async def run_turn(core: ConversationCore, text: str) -> tuple[str, list[Node]]:
    """Drive one full turn; return the streamed text and the nodes handed to on_node."""
    handed_over: list[Node] = []

    async def on_node(node: Node) -> None:
        handed_over.append(node)

    _user_node, assistant_node = core.submit(text)
    chunks = [chunk async for chunk in core.stream(assistant_node, on_node)]
    return "".join(chunks), handed_over


def system_nodes(nodes: list[Node]) -> list[Node]:
    return [n for n in nodes if n.node_type == "system"]


def context_nodes(nodes: list[Node]) -> list[Node]:
    return [n for n in nodes if n.node_type == "context"]


async def test_oversized_fetch_is_refused_with_a_durable_breadcrumb(
    repo: Any,
    workspace: Any,
    test_provider: Any,
    search_available: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C1/C2/C3/C4: refusal instead of the page, durable breadcrumb, no page node,
    and the turn still reaches an answer."""
    pin_window(monkeypatch, 4000)
    page = oversized_page()
    provider = fetch_then_answer(BIG_PAGE_URL)
    core = ConversationCore(
        storage=repo,
        provider=provider,
        workspace=workspace,
        search=CannedSearch(page=page),
    )

    streamed, _handed_over = await run_turn(
        core, "Fetch the Rust 1.81 release notes and tell me what changed."
    )

    # C4: another round ran after the refusal and the turn settled on an answer.
    assert ANSWER_TEXT in streamed

    # C1: the round that followed answered the fetch call with the explanation, and
    # the page text reached no request at all.
    final_request = provider.messages_seen[-1]
    tool_messages = [m for m in final_request if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert REFUSAL_PHRASE in tool_messages[0]["content"]
    assert BIG_PAGE_URL in tool_messages[0]["content"]
    assert not any(page in str(m.get("content")) for m in final_request)

    # C2: exactly one breadcrumb (so the refused fetch was not retried), naming the URL.
    breadcrumbs = system_nodes(core.nodes)
    assert len(breadcrumbs) == 1
    assert breadcrumbs[0].role == "system"
    assert REFUSAL_PHRASE in breadcrumbs[0].content
    assert BIG_PAGE_URL in breadcrumbs[0].content

    # C3: the page itself became no node at all.
    assert context_nodes(core.nodes) == []
    assert not any(page in n.content for n in core.nodes)

    # C2: the breadcrumb survives quitting and resuming the conversation.
    reader = ConversationCore(
        storage=repo,
        provider=test_provider(["reloaded"]),
        workspace=workspace,
    )
    resumed = reader.resume_conversation(core.conversation_id)
    resumed_breadcrumbs = system_nodes(resumed)
    assert len(resumed_breadcrumbs) == 1
    assert REFUSAL_PHRASE in resumed_breadcrumbs[0].content
    assert BIG_PAGE_URL in resumed_breadcrumbs[0].content


async def test_fetched_page_that_fits_is_never_truncated(
    repo: Any,
    workspace: Any,
    search_available: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C5: with a known window the page fits under, it arrives whole and unwrapped."""
    pin_window(monkeypatch, 200_000)
    page = modest_page()
    core = ConversationCore(
        storage=repo,
        provider=fetch_then_answer(SMALL_PAGE_URL),
        workspace=workspace,
        search=CannedSearch(page=page),
    )

    streamed, _handed_over = await run_turn(
        core, "Read the Python 3.12 release notes and summarise the typing changes."
    )

    assert ANSWER_TEXT in streamed

    pages = context_nodes(core.nodes)
    assert len(pages) == 1
    fetched = pages[0]
    assert fetched.role == "context"
    assert fetched.meta["source_path"] == SMALL_PAGE_URL
    assert fetched.meta["origin"] == "model"
    # Byte-for-byte: no truncation, no ellipsis, no wrapper cap.
    assert fetched.content == page

    assert system_nodes(core.nodes) == []


async def test_unknown_window_skips_the_guard(
    repo: Any,
    workspace: Any,
    search_available: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C6: when litellm has no window metadata the guard stays out of the way — the
    oversized page reaches the model whole and no refusal is recorded."""
    pin_window(monkeypatch, None)
    page = oversized_page()
    core = ConversationCore(
        storage=repo,
        provider=fetch_then_answer(BIG_PAGE_URL),
        workspace=workspace,
        search=CannedSearch(page=page),
    )

    streamed, _handed_over = await run_turn(
        core, "Fetch the Rust 1.81 release notes and tell me what changed."
    )

    assert ANSWER_TEXT in streamed

    pages = context_nodes(core.nodes)
    assert len(pages) == 1
    assert pages[0].meta["source_path"] == BIG_PAGE_URL
    assert pages[0].content == page

    assert system_nodes(core.nodes) == []
    assert not any(REFUSAL_PHRASE in n.content for n in core.nodes)
