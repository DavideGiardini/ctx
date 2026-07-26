"""Tests for the web-search seam (``ctx/core/search.py``).

Contract: ``tests/specs/search.md``. Nothing here touches the network: the litellm
entry point bound as ``ctx.core.search.asearch`` is monkeypatched with async stubs.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import ctx.core.config
import ctx.core.search
from ctx.core.search import LiteLLMSearch, SearchError, SearchHit, search_available

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
