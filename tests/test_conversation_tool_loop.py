"""The tool-calling round loop in ``ConversationCore.stream()``.

Contract: ``tests/specs/conversation-tool-loop.md``. Each test names the item(s)
it covers in its docstring.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from ctx.core import config as ctx_config
from ctx.core.conversation import ConversationCore
from ctx.core.provider import ScriptedRound, ToolCall
from ctx.core.provider import TestProvider as ScriptedProvider
from ctx.core.search import TOOL_SCHEMAS, SearchError, SearchHit
from ctx.core.search import TestSearch as CannedSearch
from ctx.models.nodes import Node

# --- fixtures ---------------------------------------------------------------


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


@pytest.fixture
def search_unavailable(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Config isolated and no backend key anywhere in the environment."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    return config_dir


def write_search_config(config_dir: Path, *, max_tool_calls: int) -> None:
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "search": {
                    "provider": "tavily",
                    "max_results": 5,
                    "max_tool_calls": max_tool_calls,
                }
            }
        ),
        encoding="utf-8",
    )


def turn_line(core: ConversationCore, user_node: Node) -> list[Node]:
    """The conversation line from the user node onward — the nodes this turn owns.

    Ignores whatever precedes it (system prompt, included context), which this
    change does not touch.
    """
    ids = [node.id for node in core.nodes]
    return core.nodes[ids.index(user_node.id) :]


def kinds(nodes: list[Node]) -> list[str]:
    return [node.node_type for node in nodes]


def assistants(nodes: list[Node]) -> list[Node]:
    return [n for n in nodes if n.node_type == "message" and n.role == "assistant"]


def node_recorder() -> tuple[list[Node], Callable[[Node], Awaitable[None]]]:
    seen: list[Node] = []

    async def on_node(node: Node) -> None:
        seen.append(node)

    return seen, on_node


HITS = [
    SearchHit(
        title="ECB holds rates steady in October",
        url="https://www.ecb.europa.eu/press/pr/date/2026/html/decision.en.html",
        snippet="The Governing Council decided to keep the three key interest rates unchanged.",
        date="2026-10-29",
    ),
    SearchHit(
        title="Euro area annual inflation at 2.1%",
        url="https://ec.europa.eu/eurostat/news/euro-indicators/inflation-october-2026",
        snippet="Euro area annual inflation was 2.1% in October 2026, down from 2.3%.",
    ),
]


# --- tests ------------------------------------------------------------------


async def test_turn_without_tool_calls_is_one_ordinary_round(
    repo: Any, workspace: Any, test_provider: Any, search_available: Path
) -> None:
    """C1: a turn the model settles in one round is untouched by the tool loop."""
    provider = test_provider(["The Rhine ", "is 1,230 km long."])
    core = ConversationCore(repo, provider, workspace, search=CannedSearch(hits=HITS))
    seen, on_node = node_recorder()

    user_node, assistant_node = core.submit("How long is the Rhine?")
    tokens = [tok async for tok in core.stream(assistant_node, on_node)]

    assert tokens == ["The Rhine ", "is 1,230 km long."]
    line = turn_line(core, user_node)
    assert kinds(line) == ["message", "message"]
    assert (line[0].role, line[1].role) == ("user", "assistant")
    assert line[1].content == "The Rhine is 1,230 km long."
    assert len(provider.tools_seen) == 1  # no extra round
    assert seen == []  # submit() already handed round 1's node to the caller


async def test_search_call_appends_a_search_node_and_runs_a_second_round(
    repo: Any, workspace: Any, search_available: Path
) -> None:
    """C2: a tool call becomes a durable node, is announced, and buys another round."""
    query = "euro area inflation October 2026"
    provider = ScriptedProvider(
        rounds=[
            ScriptedRound(
                tokens=["Let me check the latest figures."],
                tool_calls=[
                    ToolCall(id="call_1", name="search", arguments=json.dumps({"query": query}))
                ],
            ),
            ScriptedRound(tokens=["Euro area annual inflation was 2.1% in October 2026."]),
        ]
    )
    core = ConversationCore(repo, provider, workspace, search=CannedSearch(hits=HITS))
    seen, on_node = node_recorder()

    _user, assistant_node = core.submit("What is euro area inflation right now?")
    [tok async for tok in core.stream(assistant_node, on_node)]

    search_nodes = [node for node in core.nodes if node.node_type == "search"]
    assert len(search_nodes) == 1
    search_node = search_nodes[0]
    assert search_node.meta["query"] == query
    assert len(search_node.meta["hits"]) == len(HITS)
    assert search_node.content.strip() != ""

    assert search_node.id in [node.id for node in seen]
    assert len(provider.tools_seen) == 2  # the second round really ran
    assert provider.tools_seen[0] == TOOL_SCHEMAS


async def test_each_round_gets_its_own_assistant_node_in_chronological_order(
    repo: Any, workspace: Any, search_available: Path
) -> None:
    """C3: user -> assistant(round 1) -> search -> assistant(round 2), text yielded as str."""
    provider = ScriptedProvider(
        rounds=[
            ScriptedRound(
                tokens=["Let me check ", "the latest figures."],
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="search",
                        arguments=json.dumps({"query": "ECB rate decision October 2026"}),
                    )
                ],
            ),
            ScriptedRound(tokens=["The ECB ", "held rates steady."]),
        ]
    )
    core = ConversationCore(repo, provider, workspace, search=CannedSearch(hits=HITS))

    user_node, assistant_node = core.submit("Did the ECB move rates in October?")
    tokens = [tok async for tok in core.stream(assistant_node)]

    assert tokens == ["Let me check ", "the latest figures.", "The ECB ", "held rates steady."]
    line = turn_line(core, user_node)
    assert kinds(line) == ["message", "message", "search", "message"]
    assert [n.role for n in line] == ["user", "assistant", "search", "assistant"]
    assert line[1].content == "Let me check the latest figures."
    assert line[3].content == "The ECB held rates steady."


async def test_silent_round_adds_no_assistant_node_and_fetch_becomes_context(
    repo: Any, workspace: Any, search_available: Path
) -> None:
    """C4: a round that is nothing but a tool call leaves no empty bubble; fetch -> context."""
    url = "https://www.ecb.europa.eu/press/pr/date/2026/html/decision.en.html"
    page = "Monetary policy decisions\n\nThe Governing Council decided to keep rates unchanged."
    provider = ScriptedProvider(
        rounds=[
            ScriptedRound(
                tokens=["Checking two sources."],
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="search",
                        arguments=json.dumps({"query": "ECB rate decision October 2026"}),
                    )
                ],
            ),
            ScriptedRound(
                tokens=[],
                tool_calls=[
                    ToolCall(id="call_2", name="fetch", arguments=json.dumps({"url": url}))
                ],
            ),
            ScriptedRound(tokens=["Both sources agree: rates were left unchanged."]),
        ]
    )
    core = ConversationCore(repo, provider, workspace, search=CannedSearch(hits=HITS, page=page))
    seen, on_node = node_recorder()

    user_node, assistant_node = core.submit("Check the ECB decision and confirm it.")
    [tok async for tok in core.stream(assistant_node, on_node)]

    line = turn_line(core, user_node)
    assert kinds(line) == ["message", "message", "search", "context", "message"]
    assert [n.content for n in assistants(line)] == [
        "Checking two sources.",
        "Both sources agree: rates were left unchanged.",
    ]

    context_node = line[3]
    assert context_node.content == page
    assert context_node.meta["source_path"] == url
    assert context_node.meta["origin"] == "model"

    assert [n.id for n in seen] == [line[2].id, line[3].id, line[4].id]


async def test_tool_call_budget_ends_the_loop_with_a_toolless_final_round(
    repo: Any, workspace: Any, search_available: Path
) -> None:
    """C5: with the budget spent, one last round runs with no tools and the turn terminates."""
    write_search_config(search_available, max_tool_calls=2)
    provider = ScriptedProvider(
        rounds=[
            ScriptedRound(
                tokens=["Searching."],
                tool_calls=[
                    ToolCall(
                        id=f"call_{i}",
                        name="search",
                        arguments=json.dumps({"query": f"eurozone inflation source {i}"}),
                    )
                ],
            )
            for i in (1, 2, 3)
        ]
    )
    core = ConversationCore(repo, provider, workspace, search=CannedSearch(hits=HITS))

    _user, assistant_node = core.submit("Keep searching until you are sure.")
    [tok async for tok in core.stream(assistant_node)]

    assert len(provider.tools_seen) == 3
    assert provider.tools_seen[0] is not None
    assert provider.tools_seen[1] is not None
    assert provider.tools_seen[-1] is None
    assert len([n for n in core.nodes if n.node_type == "search"]) == 2


async def test_without_a_backend_key_no_tools_are_offered(
    repo: Any, workspace: Any, test_provider: Any, search_unavailable: Path
) -> None:
    """C6: no key in the environment means the feature is simply absent."""
    provider = test_provider(["Mont Blanc ", "is 4,806 m high."])
    core = ConversationCore(repo, provider, workspace, search=CannedSearch(hits=HITS))

    user_node, assistant_node = core.submit("How high is Mont Blanc?")
    tokens = [tok async for tok in core.stream(assistant_node)]

    assert tokens == ["Mont Blanc ", "is 4,806 m high."]
    assert provider.tools_seen == [None]
    line = turn_line(core, user_node)
    assert kinds(line) == ["message", "message"]
    assert line[1].content == "Mont Blanc is 4,806 m high."


async def test_consumer_stopping_mid_loop_keeps_nodes_and_leaves_the_ending_to_end_turn(
    repo: Any, workspace: Any, search_available: Path
) -> None:
    """C7: stream() rolls nothing back, stamps nothing, and never lowers the flag."""
    provider = ScriptedProvider(
        rounds=[
            ScriptedRound(
                tokens=["Searching now."],
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="search",
                        arguments=json.dumps({"query": "ECB rate decision October 2026"}),
                    )
                ],
            ),
            ScriptedRound(tokens=["The ECB ", "held rates steady."]),
        ]
    )
    core = ConversationCore(repo, provider, workspace, search=CannedSearch(hits=HITS))

    _user, assistant_node = core.submit("Did the ECB move rates in October?")
    stream = core.stream(assistant_node)
    received: list[str] = []
    async for token in stream:
        received.append(token)
        if len(received) == 2:  # round 1 done, round 2 under way
            break
    await stream.aclose()

    assert len([n for n in core.nodes if n.node_type == "search"]) == 1
    assert core.streaming is True
    assert "interrupted" not in assistant_node.meta
    assert "error" not in assistant_node.meta

    core.end_turn(assistant_node, cancelled=True)

    assert core.streaming is False
    assert assistant_node.meta["interrupted"] is True
    assert len([n for n in core.nodes if n.node_type == "search"]) == 1


async def test_failing_tool_calls_leave_breadcrumbs_and_the_turn_continues(
    repo: Any, workspace: Any, search_available: Path
) -> None:
    """C8: a backend error and malformed arguments are reported, not raised."""
    provider = ScriptedProvider(
        rounds=[
            ScriptedRound(
                tokens=["Looking that up."],
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="search",
                        arguments=json.dumps({"query": "ECB rate decision October 2026"}),
                    ),
                    ToolCall(id="call_2", name="fetch", arguments='{"url": "https://ecb.'),
                ],
            ),
            ScriptedRound(tokens=["I could not reach the web, so here is what I know offline."]),
        ]
    )
    core = ConversationCore(
        repo,
        provider,
        workspace,
        search=CannedSearch(error=SearchError("Tavily returned 401 Unauthorized")),
    )
    seen, on_node = node_recorder()

    user_node, assistant_node = core.submit("Did the ECB move rates in October?")
    tokens = [tok async for tok in core.stream(assistant_node, on_node)]

    assert tokens == [
        "Looking that up.",
        "I could not reach the web, so here is what I know offline.",
    ]
    line = turn_line(core, user_node)
    assert kinds(line) == ["message", "message", "system", "system", "message"]
    assert all(node.content.strip() != "" for node in line[2:4])
    assert [n.id for n in seen] == [line[2].id, line[3].id, line[4].id]
    assert len(provider.tools_seen) == 2  # one retry-free follow-up round
