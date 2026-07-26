"""Deterministic, no-arg ChatApp for headless agent driving.

Wires ``ChatApp`` with a ``HarnessProvider`` (canned tokens and scripted tool
turns, no network), a ``HarnessSearch`` (canned hits, no network) and a
``Workspace`` rooted in a fresh temp directory, so agent runs are reproducible
and never touch the network or pollute the repo's ``.ctx/``.

No-arg constructible so ``textual-mcp-server``'s loader can instantiate it as
``tools.agent.harness:HarnessApp``. The temp directory is ephemeral (left to the
OS temp cleaner); each instantiation gets its own.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

from ctx.core.provider import ToolCall, Usage
from ctx.core.search import SearchError, SearchHit, TestSearch
from ctx.core.workspace import Workspace
from ctx.ui import app as ctx_app

CANNED_RESPONSE = ["This ", "is ", "a ", "canned ", "test ", "response."]

# A canned provider usage so the header-gauge calibration path is exercised in
# headless runs. ``prompt_tokens`` is small enough to stay within the core's
# ``CALIBRATION_TOLERANCE`` (10×) of any short typed message's local estimate,
# so the gauge sheds its ``~`` after a turn instead of staying perpetually
# approximate.
CANNED_USAGE = Usage(prompt_tokens=20, completion_tokens=6, total_tokens=26)

SAMPLE_FILE_NAME = "sample.txt"
SAMPLE_FILE_BODY = "Sample context file for agent testing.\nLine two.\n"

# The ranked hits every harness search returns. The URLs are under the reserved
# ``.invalid`` TLD (RFC 2606) so a bug that let a real fetch through would fail
# to resolve rather than quietly reach a live site.
HARNESS_HITS: list[SearchHit] = [
    SearchHit(
        title="ctx0 — the append-only conversation graph",
        url="https://ctx0.example.invalid/graph",
        snippet=(
            "Every turn, every import and every compaction is a node, and "
            "nothing is ever mutated or deleted."
        ),
        date="2026-07-01",
    ),
    SearchHit(
        title="Compacting a conversation without losing it",
        url="https://ctx0.example.invalid/compaction",
        snippet="A K folds a range of nodes into one summary; x expands it again.",
    ),
]

# The lead-in a scripted turn streams before its first tool call, when it streams
# one at all — a turn that opens on a silent call leaves round 1's assistant node
# empty, which is a case the view has to handle and the harness must be able to
# produce.
LEAD_IN = "Let me look that up. "

_UI_DIR = Path(ctx_app.__file__).parent


@dataclass(frozen=True)
class _Script:
    """One trigger word's scripted turn: an opening line and a tool per round.

    ``calls`` names the tool each round asks for, indexed by how many calls the
    turn has already made; a round past the end asks for nothing and answers
    instead. ``endless`` ignores the index and repeats the last tool forever,
    modelling a model that never stops searching.
    """

    opening: str
    calls: tuple[str, ...]
    endless: bool = False

    def call_for(self, round_index: int) -> str | None:
        if self.endless:
            return self.calls[-1]
        if round_index < len(self.calls):
            return self.calls[round_index]
        return None


# AIDEV-NOTE: iteration order is load-bearing — "SEARCHFAIL" and "SEARCHLOOP"
# both contain "SEARCH", so the specific triggers must be matched before it.
_SCRIPTS: dict[str, _Script] = {
    "SEARCHFAIL": _Script(LEAD_IN, ("search",)),
    "SEARCHLOOP": _Script("", ("search",), endless=True),
    "SEARCH": _Script(LEAD_IN, ("search",)),
    "FETCH": _Script("", ("search", "fetch")),
}


def _last_user_text(messages: list[dict]) -> str:
    """The content of the newest user message — the text the user just submitted."""
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else ""
    return ""


def _triggered(messages: list[dict]) -> tuple[_Script | None, str]:
    """The script the submitted message asks for, and the message itself."""
    text = _last_user_text(messages)
    for trigger, script in _SCRIPTS.items():
        if trigger in text:
            return script, text
    return None, text


def _scripted_call(tool: str, round_index: int, query: str) -> ToolCall:
    """The tool call round ``round_index`` asks for.

    A ``search`` is issued with the user's message *verbatim*, trigger word
    included. That is deliberate and load-bearing: it is what carries
    ``SEARCHFAIL`` through to ``HarnessSearch``, so neither double needs to share
    mutable state with the other to agree on what this turn is supposed to do.
    """
    arguments = {"query": query} if tool == "search" else {"url": HARNESS_HITS[0].url}
    return ToolCall(
        id=f"harness-call-{round_index + 1}",
        name=tool,
        arguments=json.dumps(arguments),
    )


class HarnessSearch(TestSearch):
    """Canned search backend that fails on demand.

    Returns ``HARNESS_HITS`` for every query and the inherited canned page for
    every fetch — except that a query carrying the ``SEARCHFAIL`` trigger word
    raises ``SearchError``, which is how a harness run exercises a failed tool
    call without a network in sight.
    """

    def __init__(self) -> None:
        super().__init__(hits=list(HARNESS_HITS))

    async def search(self, query: str) -> list[SearchHit]:
        """The canned hits, or ``SearchError`` when ``query`` carries the trigger."""
        if "SEARCHFAIL" in query:
            raise SearchError("the harness search backend is scripted to fail")
        return await super().search(query)


class HarnessProvider:
    """Provider double whose turn shape is scripted by a trigger word.

    Plays an ordinary one-round canned turn (``CANNED_RESPONSE``) unless the
    submitted message carries a trigger word, in which case it scripts a
    multi-round tool turn:

    * ``SEARCH`` — round 1 streams ``LEAD_IN`` and asks for a ``search``; round 2
      streams the canned answer.
    * ``FETCH`` — round 1 asks for a ``search`` with no text at all; round 2 asks
      for a ``fetch`` of the first hit's URL; round 3 streams the answer.
    * ``SEARCHFAIL`` — as ``SEARCH``, but the query carries the trigger onward so
      the search backend raises; round 2 still answers.
    * ``SEARCHLOOP`` — asks for a ``search`` on *every* round, forever, so only
      the core's own tool budget can end the turn.

    A round offered no tools (``tools is None``) always answers, whatever the
    trigger: that is the core telling the model its budget is spent, and a model
    that cannot call a tool must answer from what it has.

    Which round is in flight is *derived*, never counted: past turns replay as
    text rather than as native tool messages (ADR-0018 §3), so the ``role="tool"``
    messages in a request are exactly this turn's completed calls. The double
    therefore holds no per-turn state that could fall out of step with the core.
    """

    async def stream(
        self,
        messages: list[dict],
        model: str,
        on_usage: Callable[[Usage], None] | None = None,
        tools: list[dict] | None = None,
        on_tool_calls: Callable[[list[ToolCall]], None] | None = None,
    ) -> AsyncIterator[str]:
        """Stream one round of the scripted turn, reporting its tool calls."""
        script, query = _triggered(messages) if tools else (None, "")
        round_index = sum(1 for message in messages if message.get("role") == "tool")
        wanted = script.call_for(round_index) if script is not None else None

        if wanted is None or script is None:
            for token in CANNED_RESPONSE:
                yield token
        else:
            if round_index == 0 and script.opening:
                yield script.opening
            if on_tool_calls is not None:
                on_tool_calls([_scripted_call(wanted, round_index, query)])

        if on_usage is not None:
            on_usage(CANNED_USAGE)

    async def check_connectivity(self, model: str) -> tuple[bool, str]:
        return True, "ok"


class HarnessApp(ctx_app.ChatApp):
    """ChatApp pre-wired for deterministic, network-free agent runs."""

    # ChatApp.CSS_PATH is relative to ctx/ui/. As a subclass defined in
    # tools/agent/, Textual would resolve those paths against tools/agent/, so we
    # re-anchor them to the real UI directory (reusing the base list).
    CSS_PATH = [str(_UI_DIR / path) for path in ctx_app.ChatApp.CSS_PATH]

    def __init__(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="ctx-harness-"))
        workspace = Workspace(root)
        # Seed one context file so /include and the file-viewer split are
        # exercisable out of the box.
        workspace.ensure()
        (workspace.context_dir / SAMPLE_FILE_NAME).write_text(
            SAMPLE_FILE_BODY, encoding="utf-8"
        )
        # AIDEV-NOTE: the web tools are offered only while search_available()
        # (D4), which looks for the configured backend's API key in the
        # environment — so without a key planted here a harness run would script
        # tool calls the core never asks for, and silently behave pre-Phase-4.
        # Safe because HarnessSearch is canned: the key is never spent. Assumes
        # the default search.provider ("tavily"); a user config naming another
        # backend would want that backend's key instead.
        os.environ.setdefault("TAVILY_API_KEY", "harness-placeholder-not-a-real-key")
        super().__init__(
            provider=HarnessProvider(),
            search=HarnessSearch(),
            workspace=workspace,
        )
