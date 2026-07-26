"""Reaching the web: the search seam and its litellm adapter.

litellm already normalizes fourteen search backends behind one call, so this
module adds no per-backend layer of its own (ADR-0018 §5) — only the domain
types, the seam, and the wrapping that keeps litellm out of the rest of ctx.
"""

import json
import os
from dataclasses import asdict, dataclass
from typing import Protocol

import httpx
import trafilatura
from litellm import asearch

from ctx.core.config import get_config
from ctx.core.log import logger
from ctx.core.provider import ToolCall
from ctx.models.nodes import Node

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


# The two tools offered to the model, in OpenAI function-calling format. The
# descriptions are deliberately neutral capability statements: they say what each
# tool does and nothing about when to reach for it, so the model's own judgment
# about whether a question needs the web stays unbiased (D6).
TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": (
                "Search the web. Returns ranked results, each with a title, a URL, a "
                "short extract, and a publication date where the source reports one."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch",
            "description": (
                "Retrieve one web page and return its readable text in full, with "
                "navigation, adverts and sidebars stripped out."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The address of the page to retrieve.",
                    },
                },
                "required": ["url"],
            },
        },
    },
]

# The tool roster, single-sourced from the schemas the model was actually offered.
_TOOL_NAMES = frozenset(schema["function"]["name"] for schema in TOOL_SCHEMAS)


async def dispatch_tool_call(
    call: ToolCall, backend: SearchBackend, conversation_id: str
) -> tuple[Node, str]:
    """Run one tool call the model asked for, as a node plus its reply text.

    Returns ``(node, result_text)``: the node to append to the conversation
    graph, and the text that goes back to the model in the ``role="tool"``
    message answering ``call.id``.

    A ``search`` call becomes a ``Node.search`` carrying the query and its
    ranked hits. A ``fetch`` call becomes ``Node.context(page,
    source_path=url, origin="model")`` — a fetched page is an import whose
    source happens to be a URL, not a node kind of its own (ADR-0018 §4).

    **Never raises.** Every failure — an unknown tool name, arguments that are
    not valid JSON, a missing or non-string argument, and any ``SearchError``
    from the backend — comes back as an explanatory ``result_text`` for the
    model, which is free to try something else; the turn continues and nothing
    is retried (D8). A failed call still produces a node, so the attempt stays
    visible to the user rather than vanishing.
    """
    if call.name not in _TOOL_NAMES:
        offered = ", ".join(sorted(_TOOL_NAMES))
        return _tool_failure(
            f'"{call.name}" is not an available tool. The tools are: {offered}.',
            conversation_id,
        )

    try:
        arguments = json.loads(call.arguments)
    except ValueError:
        arguments = None
    if not isinstance(arguments, dict):
        return _tool_failure(
            f'The arguments for "{call.name}" were not a valid JSON object.',
            conversation_id,
        )

    if call.name == "search":
        query = _string_argument(arguments, "query")
        if query is None:
            return _tool_failure(_missing_argument(call.name, "query"), conversation_id)
        try:
            hits = await backend.search(query)
        except SearchError as exc:
            return _tool_failure(f'The search for "{query}" failed: {exc}', conversation_id)
        node = Node.search(query, [asdict(hit) for hit in hits], conversation_id)
        # An empty hit list renders to empty content; the model still needs to be
        # told *something* happened, or the tool message would arrive blank.
        return node, node.content or f'No results for "{query}".'

    url = _string_argument(arguments, "url")
    if url is None:
        return _tool_failure(_missing_argument(call.name, "url"), conversation_id)
    try:
        page = await backend.fetch(url)
    except SearchError as exc:
        return _tool_failure(f"Fetching {url} failed: {exc}", conversation_id)
    # A fetched page is an import whose source is a URL (ADR-0018 §4), stamped
    # origin="model" so the view can tell it from a hand-driven /include.
    node = Node.context(page, source_path=url, conversation_id=conversation_id, origin="model")
    return node, page


def _string_argument(arguments: dict, name: str) -> str | None:
    """The named argument when the model supplied a usable string, else ``None``.

    A missing key and a key holding a number (or an empty string) are the same
    problem from here: there is nothing to search for or fetch.
    """
    value = arguments.get(name)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _missing_argument(tool: str, name: str) -> str:
    return f'The "{tool}" tool needs a non-empty "{name}" string argument.'


def _tool_failure(message: str, conversation_id: str) -> tuple[Node, str]:
    """A failed tool call: one explanation, told to the model and to the user.

    The user-facing half is a durable system breadcrumb rather than an empty
    search/context node, and that choice is load-bearing: a system node never
    reaches the model, so the failure the model already saw once as a tool result
    does not linger in the context of every later turn.
    """
    logger.warning("tool call failed | %s", message)
    return Node.system(message, conversation_id=conversation_id), message


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
