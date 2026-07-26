"""Reaching the web: the search seam and its litellm adapter.

litellm already normalizes fourteen search backends behind one call, so this
module adds no per-backend layer of its own (ADR-0018 §5) — only the domain
types, the seam, and the wrapping that keeps litellm out of the rest of ctx.
"""

import os
from dataclasses import dataclass
from typing import Protocol

import httpx
import trafilatura
from litellm import asearch

from ctx.core.config import get_config
from ctx.core.log import logger

# How long a single page fetch may take before it becomes a SearchError. Long
# enough for a slow news site, short enough that a hung host does not hold the
# turn open indefinitely.
FETCH_TIMEOUT_SECONDS = 20.0

# httpx's default User-Agent is refused outright by a good share of publishers,
# which would turn most fetches into a SearchError for no real reason.
_FETCH_USER_AGENT = "Mozilla/5.0 (compatible; ctx conversation IDE)"

# What TestSearch hands back from fetch() when the caller supplies no page.
CANNED_PAGE = (
    "# ctx0 and the append-only graph\n\n"
    "A conversation in ctx is an append-only node graph: every turn, every\n"
    "import and every compaction is a node, and nothing is ever mutated or\n"
    "deleted."
)

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

    async def fetch(self, url: str) -> str:
        """Return the readable body of the page at ``url`` as markdown.

        The whole extracted page is returned, never truncated: the gauge and
        compaction are the user's lever, not a hidden cap (D10). Raises
        ``SearchError`` for every failure.
        """
        ...


class LiteLLMSearch:
    """Concrete adapter using ``litellm.asearch``.

    The backend and result count come from the ``search`` config section, read
    per call so editing one config line swaps backends with no restart.

    ``fetch`` is ours rather than litellm's: litellm has no page-extraction API,
    and a backend-specific extract endpoint would break the moment the user
    swapped ``search.provider`` (D13). Pass ``transport`` to hand the internal
    ``httpx`` client a stub (``httpx.MockTransport``) so tests never reach the
    network.
    """

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

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

    async def fetch(self, url: str) -> str:
        """Retrieve ``url`` and extract its main content as markdown.

        Navigation, ads and sidebars are stripped — what comes back is the page
        body a reader would care about, uncapped (D10). Raises ``SearchError``
        for every failure: a transport error, a non-2xx status, a page
        Trafilatura cannot parse, and a page whose extraction is empty (an
        empty string would otherwise reach the model as a successful fetch of
        nothing).
        """
        logger.info("fetch started | url=%s", url)
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=FETCH_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": _FETCH_USER_AGENT},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                # AIDEV-NOTE: favor_precision matters — without it Trafilatura's
                # fallback pass "rescues" a content-free app shell as its nav
                # labels, which would reach the model as a successful fetch of
                # nothing. It leaves real article bodies untouched.
                extracted = trafilatura.extract(
                    response.text,
                    output_format="markdown",
                    include_comments=False,
                    favor_precision=True,
                )
        except Exception as exc:
            # Transport failure, non-2xx status, or a page the extractor chokes
            # on — all become the domain error, so no httpx type leaks out.
            logger.warning("fetch failed | url=%s | error=%s", url, exc)
            raise SearchError(str(exc)) from exc

        # AIDEV-NOTE: raised OUTSIDE the try — inside, the `except Exception`
        # above would catch it and re-chain it as its own cause.
        if not extracted or not extracted.strip():
            logger.warning("fetch empty | url=%s", url)
            raise SearchError(f"no readable content at {url}")

        logger.info("fetch done | url=%s | chars=%d", url, len(extracted))
        return extracted


class TestSearch:
    """Test adapter returning canned results, never touching the network.

    Pass ``hits`` for the results every search returns and ``page`` for the body
    every fetch returns, or ``error`` for an exception both ``search`` and
    ``fetch`` raise instead.
    """

    def __init__(
        self,
        hits: list[SearchHit] | None = None,
        page: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self._hits = hits or []
        self._page = CANNED_PAGE if page is None else page
        self._error = error

    async def search(self, query: str) -> list[SearchHit]:
        if self._error is not None:
            raise self._error
        return self._hits

    async def fetch(self, url: str) -> str:
        if self._error is not None:
            raise self._error
        return self._page


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
