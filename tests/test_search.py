"""Tests for the web-search seam (``ctx/core/search.py``).

Contract: ``tests/specs/search.md``. Nothing here touches the network: the litellm
entry point bound as ``ctx.core.search.asearch`` is monkeypatched with async stubs.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import ctx.core.config
import ctx.core.search
from ctx.core.search import (
    FETCH_TIMEOUT_SECONDS,
    LiteLLMSearch,
    SearchError,
    SearchHit,
    search_available,
)

# Aliased on import: pytest tries to collect any module-level ``Test*`` class in a
# test module, and warns because the double takes constructor arguments.
from ctx.core.search import TestSearch as CannedSearch


def _result(title: str, url: str, snippet: str, date: str | None) -> SimpleNamespace:
    """One normalized backend result, as litellm hands them over."""
    return SimpleNamespace(title=title, url=url, snippet=snippet, date=date)


def _response(*results: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(results=list(results))


@pytest.fixture
def search_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    """Point config at a throwaway file and keep a plausible key in the env."""
    monkeypatch.setattr(ctx.core.config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ctx.core.config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key-not-real")

    def write(section: dict[str, Any]) -> None:
        (tmp_path / "config.json").write_text(json.dumps({"search": section}))

    return write


@pytest.mark.asyncio
async def test_unknown_backend_exception_becomes_search_error(
    monkeypatch: pytest.MonkeyPatch, search_config: Any
) -> None:
    """C1: any backend failure surfaces as SearchError with the original chained."""

    class TavilyRateLimitError(Exception):
        """An exception type this module has never heard of."""

    boom = TavilyRateLimitError("429 too many requests")

    async def exploding_asearch(*args: Any, **kwargs: Any) -> Any:
        raise boom

    monkeypatch.setattr(ctx.core.search, "asearch", exploding_asearch)

    with pytest.raises(SearchError) as excinfo:
        await LiteLLMSearch().search("who won the 2026 tour de france")

    assert excinfo.value.__cause__ is boom


@pytest.mark.asyncio
async def test_successful_search_returns_ordered_domain_hits(
    monkeypatch: pytest.MonkeyPatch, search_config: Any
) -> None:
    """C2: normalized results become SearchHits, backend order kept, date optional."""

    async def stub_asearch(*args: Any, **kwargs: Any) -> Any:
        return _response(
            _result(
                "Textual 1.0 released",
                "https://textual.textualize.io/blog/2024/12/12/textual-10/",
                "Textual reaches 1.0 with a stable widget API.",
                "2024-12-12",
            ),
            _result(
                "Building TUIs in Python",
                "https://realpython.com/python-textual/",
                "A walkthrough of Textual's layout and reactivity model.",
                None,
            ),
        )

    monkeypatch.setattr(ctx.core.search, "asearch", stub_asearch)

    hits = await LiteLLMSearch().search("textual python tui")

    assert [type(hit) for hit in hits] == [SearchHit, SearchHit]
    assert hits[0] == SearchHit(
        title="Textual 1.0 released",
        url="https://textual.textualize.io/blog/2024/12/12/textual-10/",
        snippet="Textual reaches 1.0 with a stable widget API.",
        date="2024-12-12",
    )
    assert hits[1].url == "https://realpython.com/python-textual/"
    assert hits[1].date is None


@pytest.mark.asyncio
async def test_configured_provider_and_result_count_reach_the_backend(
    monkeypatch: pytest.MonkeyPatch, search_config: Any
) -> None:
    """C3: provider/max_results are read from config per call, query forwarded."""
    search_config({"provider": "exa", "max_results": 3})
    monkeypatch.setenv("EXA_API_KEY", "exa-test-key-not-real")

    passed: list[Any] = []

    async def recording_asearch(*args: Any, **kwargs: Any) -> Any:
        passed.extend(args)
        passed.extend(kwargs.values())
        return _response()

    monkeypatch.setattr(ctx.core.search, "asearch", recording_asearch)

    await LiteLLMSearch().search("append-only conversation graph design")

    assert "exa" in passed
    assert 3 in passed
    assert "append-only conversation graph design" in passed


def test_search_available_tracks_the_env_and_unknown_providers(
    monkeypatch: pytest.MonkeyPatch, search_config: Any
) -> None:
    """C5 + C6: availability follows TAVILY_API_KEY uncached; unknown provider is off."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert search_available() is False

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key-not-real")
    assert search_available() is True

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert search_available() is False

    # C6: a provider litellm does not recognize fails closed, key or no key.
    search_config({"provider": "askjeeves"})
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key-not-real")
    assert search_available() is False


@pytest.mark.asyncio
async def test_test_search_double_returns_canned_hits_or_raises() -> None:
    """C7: TestSearch is query-independent and can be driven into failure."""
    canned = [
        SearchHit(
            title="ADR 0018: model-callable web search",
            url="https://example.org/ctx/adr-0018",
            snippet="litellm ships the multi-backend search abstraction.",
            date="2026-07-01",
        )
    ]
    double = CannedSearch(hits=canned)

    assert await double.search("adr 0018") == canned
    assert await double.search("something else entirely") == canned

    failure = RuntimeError("backend unreachable")
    with pytest.raises(RuntimeError) as excinfo:
        await CannedSearch(error=failure).search("adr 0018")
    assert excinfo.value is failure


def test_search_config_defaults_and_partial_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """C8: search section defaults, and a partial override keeps the other keys."""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(ctx.core.config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ctx.core.config, "CONFIG_PATH", config_path)

    assert ctx.core.config.get_config()["search"] == {
        "provider": "tavily",
        "max_results": 5,
        "max_tool_calls": 12,
    }

    config_path.write_text(json.dumps({"search": {"provider": "brave"}}))

    assert ctx.core.config.get_config()["search"] == {
        "provider": "brave",
        "max_results": 5,
        "max_tool_calls": 12,
    }


# A plausible blog post: chrome and promo links outside the article, five real
# paragraphs inside it. Trafilatura needs genuine prose to call a block the main body.
ARTICLE_PAGE = """<!DOCTYPE html>
<html lang="en">
<head><title>Why we store conversations as an append-only graph</title></head>
<body>
<header><a href="/">The Terminal Notebook</a> <a href="/archive">Archive</a></header>
<nav><ul>
<li><a href="#main">Skip to main content</a></li>
<li><a href="/tags/python">Python</a></li>
<li><a href="/tags/llm">Language models</a></li>
</ul></nav>
<aside class="sidebar"><h3>Elsewhere</h3><ul>
<li><a href="/p/terminal-tricks">Ten terminal tricks</a></li>
<li><a href="/p/rust-for-pythonistas">Rust for Pythonistas</a></li>
<li><a href="/newsletter">Subscribe to the newsletter</a></li>
</ul></aside>
<article id="main">
<h1>Why we store conversations as an append-only graph</h1>
<p>Most chat tools keep the transcript as a mutable list of messages, and that one
decision quietly costs them everything interesting. When you edit a turn, the version
the model actually answered is overwritten, so afterwards nobody can explain why the
assistant said what it said. The transcript stops being evidence and becomes a draft.</p>
<p>An append-only graph makes a different promise: nothing already written is ever
changed or removed. A rewind is a new branch, never a deletion, and the turns you walked
away from stay on disk as a sibling path you can return to. Two answers to the same
question can sit side by side instead of one silently replacing the other.</p>
<p>Summarization works the same way. Compressing a range of turns appends a compression
node that stands in front of the originals rather than replacing them, so the long
version is still there when the summary turns out to have thrown away the one detail
that mattered. Expanding it again is another append, not an undo.</p>
<p>The honest cost is that storage only ever grows. A conversation you prune repeatedly
never actually gets smaller on disk, and the reader has to know which nodes reach the
model and which are historical sediment. We pay that because a conversation you cannot
audit is a conversation you cannot trust.</p>
<p>None of this hides the price of a long conversation from you. The token gauge stays
the only honest signal of how much context you are carrying, and manual compaction
stays the only lever that shrinks it. We would rather show you the number than quietly
drop the middle of your work.</p>
</article>
<footer><p>Copyright 2026 The Terminal Notebook. All rights reserved.</p></footer>
</body>
</html>
"""

# A client-rendered app shell: chrome and empty containers, no prose to extract.
EMPTY_PAGE = """<!DOCTYPE html>
<html lang="en">
<head><title>Dashboard</title></head>
<body>
<nav><a href="/">Home</a> <a href="/login">Log in</a></nav>
<div id="app"></div>
<div class="loading-spinner"></div>
<footer><a href="/terms">Terms</a> <a href="/privacy">Privacy</a></footer>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_fetch_returns_the_whole_body_stripped_of_boilerplate() -> None:
    """C9 + C10 + C13: full uncapped article body, redirect followed, timeout bounded."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/r/graph":
            return httpx.Response(
                301,
                headers={"Location": "https://blog.example.org/2026/append-only-graph"},
            )
        return httpx.Response(200, html=ARTICLE_PAGE)

    backend = LiteLLMSearch(transport=httpx.MockTransport(handler))

    body = await backend.fetch("http://blog.example.org/r/graph")

    # C9: the article's own prose survives, from the first paragraph to the last.
    assert "the transcript as a mutable list of messages" in body
    assert "rewind is a new branch, never a deletion" in body
    assert "token gauge stays" in body
    assert "the only lever that shrinks it" in body

    # C9: navigation and sidebar promo are not part of the readable body.
    assert "Skip to main content" not in body
    assert "Subscribe to the newsletter" not in body

    # C10: the short link's redirect was followed to the canonical https URL.
    assert [str(request.url) for request in seen] == [
        "http://blog.example.org/r/graph",
        "https://blog.example.org/2026/append-only-graph",
    ]

    # C13: a hung host cannot hold the turn open — the request carries the bound.
    assert seen[0].extensions.get("timeout", {}).get("read") == FETCH_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_fetch_wraps_transport_and_http_failures_in_search_error() -> None:
    """C11: a dead host and a 404 both become SearchError; no httpx type escapes."""
    refused = httpx.ConnectError("[Errno 111] Connection refused")

    def refusing(request: httpx.Request) -> httpx.Response:
        raise refused

    with pytest.raises(SearchError) as excinfo:
        await LiteLLMSearch(transport=httpx.MockTransport(refusing)).fetch(
            "https://blog.example.org/2026/append-only-graph"
        )
    assert excinfo.value.__cause__ is refused

    def not_found(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, html="<html><body><h1>404 Not Found</h1></body></html>")

    with pytest.raises(SearchError):
        await LiteLLMSearch(transport=httpx.MockTransport(not_found)).fetch(
            "https://blog.example.org/2026/deleted-post"
        )


@pytest.mark.asyncio
async def test_fetch_treats_an_empty_extraction_as_a_failure() -> None:
    """C12: a page with no readable content raises rather than returning ""."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=EMPTY_PAGE)

    with pytest.raises(SearchError) as excinfo:
        await LiteLLMSearch(transport=httpx.MockTransport(handler)).fetch(
            "https://app.example.com/dashboard"
        )

    # No library exception underlies this one — it is the module's own judgement.
    assert excinfo.value.__cause__ is None
