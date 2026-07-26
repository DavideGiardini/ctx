"""Tool dispatch for the model's two web tools.

Behavioral contract: ``tests/specs/search-dispatch.md`` (items C1-C5).
Nothing here touches the network: every backend is canned or local.
"""

from __future__ import annotations

import json

import pytest

from ctx.core.provider import ToolCall
from ctx.core.search import (
    TOOL_SCHEMAS,
    SearchError,
    SearchHit,
    dispatch_tool_call,
)
from ctx.core.search import (
    TestSearch as CannedSearch,
)

CONVERSATION_ID = "conv-1"

RANKED_HITS = [
    SearchHit(
        title="IPCC AR6 Synthesis Report: Summary for Policymakers",
        url="https://www.ipcc.ch/report/ar6/syr/",
        snippet="Human activities have unequivocally caused warming of 1.1C above 1850-1900.",
        date="2023-03-20",
    ),
    SearchHit(
        title="NASA Vital Signs: Global Temperature",
        url="https://climate.nasa.gov/vital-signs/global-temperature/",
        snippet="The GISTEMP record of global surface temperature anomalies, updated monthly.",
        date=None,
    ),
    SearchHit(
        title="Copernicus: 2024 was the first year above 1.5C",
        url="https://climate.copernicus.eu/copernicus-2024-first-year-exceed-15degc",
        snippet="ERA5 reanalysis puts the 2024 annual average at 1.60C above pre-industrial.",
        date="2025-01-10",
    ),
]


def as_dicts(hits: list[SearchHit]) -> list[dict]:
    """The hit list as the plain JSON-able dicts the graph has to persist."""
    return [{"title": h.title, "url": h.url, "snippet": h.snippet, "date": h.date} for h in hits]


class RecordingSearch:
    """A backend that succeeds but remembers every argument it was handed."""

    def __init__(self, hits: list[SearchHit], page: str) -> None:
        self._hits = hits
        self._page = page
        self.searched: list[object] = []
        self.fetched: list[object] = []

    async def search(self, query: str) -> list[SearchHit]:
        self.searched.append(query)
        return list(self._hits)

    async def fetch(self, url: str) -> str:
        self.fetched.append(url)
        return self._page


# C1
@pytest.mark.asyncio
async def test_search_call_records_query_and_backend_ranking() -> None:
    query = "atlantic meridional overturning circulation collapse risk"
    call = ToolCall(id="call_a1b2", name="search", arguments=json.dumps({"query": query}))

    node, result_text = await dispatch_tool_call(
        call, CannedSearch(hits=RANKED_HITS), CONVERSATION_ID
    )

    assert node.node_type == "search"
    assert node.role == "search"
    assert node.conversation_id == CONVERSATION_ID
    assert node.meta["query"] == query
    # The backend owns the ranking: same hits, same order, nothing trimmed,
    # and stored as plain dicts so the node survives a resume from SQLite.
    assert node.meta["hits"] == as_dicts(RANKED_HITS)
    json.dumps(node.meta["hits"])
    # The model is handed exactly the block the user sees on the node.
    assert result_text == node.content
    assert result_text != ""


# C2
@pytest.mark.asyncio
async def test_fetch_call_becomes_whole_page_context_import_from_the_model() -> None:
    url = "https://www.nature.com/articles/s41560-024-01508-8"
    page = (
        "Grid-scale storage in 2024\n\n"
        + (
            "Lithium-iron-phosphate cells now dominate new grid installations, "
            "displacing nickel-manganese-cobalt chemistries on cost per cycle. "
        )
        * 400
    )
    call = ToolCall(id="call_c3d4", name="fetch", arguments=json.dumps({"url": url}))

    node, result_text = await dispatch_tool_call(call, CannedSearch(page=page), CONVERSATION_ID)

    assert node.node_type == "context"
    assert node.conversation_id == CONVERSATION_ID
    assert node.meta["source_path"] == url
    assert node.meta["origin"] == "model"
    assert node.meta["prompt"] == ""
    # No length cap, by explicit product decision: the page arrives whole.
    assert node.content == page
    assert page in result_text


# C3
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("call", "mentions"),
    [
        pytest.param(
            ToolCall(
                id="call_e5f6",
                name="browse_web",
                arguments=json.dumps({"query": "who won the 2026 olympics"}),
            ),
            "browse_web",
            id="unknown-tool-name",
        ),
        pytest.param(
            ToolCall(
                id="call_g7h8",
                name="search",
                arguments='{"query": "atlantic overturning circu',
            ),
            "json",
            id="arguments-are-not-valid-json",
        ),
        pytest.param(
            ToolCall(
                id="call_i9j0",
                name="fetch",
                arguments=json.dumps({"link": "https://www.ipcc.ch/report/ar6/syr/"}),
            ),
            "url",
            id="required-argument-missing",
        ),
        pytest.param(
            ToolCall(id="call_k1l2", name="search", arguments=json.dumps({"query": 42})),
            "query",
            id="required-argument-not-a-string",
        ),
    ],
)
async def test_malformed_call_is_reported_and_never_reaches_the_backend(
    call: ToolCall, mentions: str
) -> None:
    backend = RecordingSearch(hits=RANKED_HITS, page="unused page body")

    node, result_text = await dispatch_tool_call(call, backend, CONVERSATION_ID)

    assert backend.searched == []
    assert backend.fetched == []
    assert node.node_type == "system"
    assert node.role == "system"
    assert node.conversation_id == CONVERSATION_ID
    # A system node never reaches the model, so the error text does not linger
    # in context on every subsequent turn.
    assert node.goes_to_model() is False
    assert result_text != ""
    assert mentions in result_text.lower()
    assert result_text in node.content


# C4
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            ToolCall(
                id="call_m3n4",
                name="search",
                arguments=json.dumps({"query": "sea level rise projections 2100"}),
            ),
            id="search",
        ),
        pytest.param(
            ToolCall(
                id="call_o5p6",
                name="fetch",
                arguments=json.dumps({"url": "https://climate.nasa.gov/vital-signs/sea-level/"}),
            ),
            id="fetch",
        ),
    ],
)
async def test_backend_failure_comes_back_as_text_not_an_exception(call: ToolCall) -> None:
    message = "search backend returned 429 Too Many Requests"

    node, result_text = await dispatch_tool_call(
        call, CannedSearch(error=SearchError(message)), CONVERSATION_ID
    )

    assert message in result_text
    assert node.node_type == "system"
    assert node.conversation_id == CONVERSATION_ID
    assert node.goes_to_model() is False
    assert result_text in node.content


# C5
def test_tool_schemas_offer_search_and_fetch_with_neutral_descriptions() -> None:
    functions = [schema["function"] for schema in TOOL_SCHEMAS]
    by_name = {fn["name"]: fn for fn in functions}

    assert set(by_name) == {"search", "fetch"}
    assert len(functions) == 2

    for name, argument in (("search", "query"), ("fetch", "url")):
        params = by_name[name]["parameters"]
        assert params["properties"][argument]["type"] == "string"
        assert params["required"] == [argument]

    guidance = ("when you", "if you", "you should", "always", "never", "prefer", "make sure to")
    for fn in functions:
        descriptions = [fn["description"]] + [
            prop.get("description", "") for prop in fn["parameters"]["properties"].values()
        ]
        assert fn["description"].strip() != ""
        # Neutral capability statements only: the model's judgment about *when*
        # to search must stay unbiased.
        for text in descriptions:
            assert not any(phrase in text.lower() for phrase in guidance), text
