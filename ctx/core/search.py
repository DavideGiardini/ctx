"""Reaching the web: the search seam and its litellm adapter.

litellm already normalizes fourteen search backends behind one call, so this
module adds no per-backend layer of its own (ADR-0018 §5) — only the domain
types, the seam, and the wrapping that keeps litellm out of the rest of ctx.
"""

import os
from dataclasses import dataclass
from typing import Protocol

from litellm import asearch

from ctx.core.config import get_config
from ctx.core.log import logger

# Which environment variable each of litellm's bundled search backends needs
# before it can run a query — the one thing litellm does not expose as data
# (its provider→config map imports every backend eagerly, and some of those
# imports fail on optional dependencies we don't ship). A backend mapped to
# None needs no key; a provider name absent from this table is unknown to us
# and reports unavailable, so a typo'd config line quietly offers no tools
# rather than offering tools that always fail (D4).
_API_KEY_ENV: dict[str, str | None] = {
    "tavily": "TAVILY_API_KEY",
    "brave": "BRAVE_API_KEY",
    "exa_ai": "EXA_API_KEY",
    "perplexity": "PERPLEXITYAI_API_KEY",
    "firecrawl": "FIRECRAWL_API_KEY",
    "google_pse": "GOOGLE_PSE_API_KEY",
    "linkup": "LINKUP_API_KEY",
    "parallel_ai": "PARALLEL_AI_API_KEY",
    "searchapi": "SEARCHAPI_API_KEY",
    "serper": "SERPER_API_KEY",
    "searxng": "SEARXNG_API_KEY",
    "dataforseo": "DATAFORSEO_LOGIN",
    "duckduckgo": None,
}


@dataclass(frozen=True)
class SearchHit:
    """One ranked result from a web search.

    ``date`` is the backend's publication date for the page when it reports
    one, and ``None`` otherwise — backends differ on whether they supply it.
    """

    title: str
    url: str
    snippet: str
    date: str | None = None


class SearchError(Exception):
    """Raised when a web search fails.

    Wraps the backend-specific exception so callers handle search failures
    without importing or catching litellm/httpx types — no backend type leaks
    through the ``SearchBackend`` seam. The original exception is chained via
    ``__cause__`` (``raise SearchError(...) from exc``), the same discipline
    ``ProviderError`` follows in ``ctx/core/provider.py``.
    """


class SearchBackend(Protocol):
    """Seam for reaching the web."""

    async def search(self, query: str) -> list[SearchHit]:
        """Run ``query`` against the configured backend, best hit first.

        Returns an empty list when the backend found nothing. Raises
        ``SearchError`` for every failure.
        """
        ...


class LiteLLMSearch:
    """Concrete adapter using ``litellm.asearch``.

    The backend and result count come from the ``search`` config section, read
    per call so editing one config line swaps backends with no restart.
    """

    async def search(self, query: str) -> list[SearchHit]:
        settings = get_config()["search"]
        logger.info(
            "search started | provider=%s | query=%s", settings["provider"], query
        )
        try:
            response = await asearch(
                query,
                search_provider=settings["provider"],
                max_results=settings["max_results"],
            )
            hits = [
                SearchHit(
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet,
                    date=result.date,
                )
                for result in response.results
            ]
        except Exception as exc:
            # Any backend failure — request error, or a result shape we can't
            # read — becomes the domain error, so no litellm type leaks out.
            logger.warning("search failed | query=%s | error=%s", query, exc)
            raise SearchError(str(exc)) from exc
        logger.info("search done | hits=%d", len(hits))
        return hits


class TestSearch:
    """Test adapter returning canned hits, never touching the network.

    Pass ``hits`` for the results every search returns, or ``error`` for an
    exception every search raises instead.
    """

    def __init__(
        self,
        hits: list[SearchHit] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._hits = hits or []
        self._error = error

    async def search(self, query: str) -> list[SearchHit]:
        if self._error is not None:
            raise self._error
        return self._hits


def search_available() -> bool:
    """Whether the configured backend can be reached right now.

    True when the API key the configured ``search.provider`` needs is present
    in the environment (or when that backend needs no key at all). False when
    the key is missing, so the tools are simply never offered to the model
    (D4). An unrecognized provider name reports False.

    Read from the environment on every call, never cached: a key exported after
    launch lights search up without a restart.
    """
    provider = get_config()["search"]["provider"]
    if provider not in _API_KEY_ENV:
        return False
    env_var = _API_KEY_ENV[provider]
    return env_var is None or bool(os.environ.get(env_var))
