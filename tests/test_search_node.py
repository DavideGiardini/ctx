"""Search nodes and how they reach the model.

Contract: ``tests/specs/search-node.md`` (items S1-S7).
"""

from typing import Any

from ctx.core.context import build_context, model_facing_form
from ctx.models.nodes import Node

CONVERSATION_ID = "conv-7f3a91"


def _never_load(path: str) -> str:
    """``load_file`` stub: this change must never touch the legacy path."""
    raise AssertionError(f"load_file was called unexpectedly for {path!r}")


def _hits() -> list[dict[str, Any]]:
    """Three ranked hits, best first: one dated, one date-less, one date=None."""
    return [
        {
            "title": "Textual 3.0 release notes",
            "url": "https://textual.textualize.io/blog/2026/03/11/textual-3-0/",
            "snippet": "Reactive attributes now call watch methods after the "
            "compositor settles, which changes refresh ordering.",
            "date": "2026-03-11",
        },
        {
            "title": "Watch methods and reactive attributes - Textual guide",
            "url": "https://textual.textualize.io/guide/reactivity/",
            "snippet": "A watch_<name> method runs whenever the reactive "
            "attribute <name> is assigned a different value.",
        },
        {
            "title": "Why my watch method fires twice (discussion #4821)",
            "url": "https://github.com/Textualize/textual/discussions/4821",
            "snippet": "Assigning the same value twice is a no-op unless the "
            "reactive is declared with always_update=True.",
            "date": None,
        },
    ]


# S1
def test_search_factory_shape_and_meta_vocabulary() -> None:
    query = "textual reactive attribute watch method ordering"
    hits = _hits()

    node = Node.search(query=query, results=hits, conversation_id=CONVERSATION_ID)

    assert node.role == "search"
    assert node.node_type == "search"
    assert node.meta["query"] == query
    assert node.meta["hits"] == hits


# S2
def test_rendered_block_carries_every_hit_in_ranked_order() -> None:
    hits = _hits()
    node = Node.search(
        query="textual reactive attribute watch method ordering",
        results=hits,
        conversation_id=CONVERSATION_ID,
    )
    body = node.content

    for hit in hits:
        assert hit["title"] in body
        assert hit["url"] in body
        assert hit["snippet"] in body

    positions = [body.index(hit["url"]) for hit in hits]
    assert positions == sorted(positions), "hits must render best-first, as given"

    # A hit that reports a date shows it; hits without one render nothing bogus.
    assert "2026-03-11" in body
    assert "None" not in body


# S3
def test_search_node_reaches_the_model() -> None:
    node = Node.search(
        query="litellm web search tool support",
        results=_hits()[:1],
        conversation_id=CONVERSATION_ID,
    )

    assert node.goes_to_model() is True


# S4
def test_search_results_wrapper_carries_the_query_as_user_text() -> None:
    query = "litellm web search tool support"
    hits = _hits()
    node = Node.search(query=query, results=hits, conversation_id=CONVERSATION_ID)

    assert model_facing_form(node, _never_load) == ("user", node.content)

    messages = build_context([node], _never_load)

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    content = messages[0]["content"]
    opening = f'<search_results query="{query}">'
    assert opening in content
    assert "</search_results>" in content
    assert (
        content.index(opening)
        < content.index(hits[0]["url"])
        < content.index("</search_results>")
    )


# S5
def test_search_merges_into_adjacent_user_material() -> None:
    user_text = "What changed about watch methods in Textual 3.0?"
    follow_up = "So do I need always_update for the counter?"
    search_a = Node.search(
        query="textual 3.0 watch method ordering change",
        results=_hits()[:2],
        conversation_id=CONVERSATION_ID,
    )
    search_b = Node.search(
        query="textual reactive always_update semantics",
        results=_hits()[2:],
        conversation_id=CONVERSATION_ID,
    )
    nodes = [
        Node.user(user_text, CONVERSATION_ID),
        search_a,
        Node.assistant(
            CONVERSATION_ID,
            content="Watch methods now run after the compositor settles.",
        ),
        search_b,
        Node.user(follow_up, CONVERSATION_ID),
    ]

    messages = build_context(nodes, _never_load)

    roles = [m["role"] for m in messages]
    assert roles == ["user", "assistant", "user"]
    assert all(
        a != b for a, b in zip(roles, roles[1:], strict=False)
    ), "roles must alternate"

    first = messages[0]["content"]
    assert f"{user_text}\n\n<search_results" in first
    assert search_a.meta["query"] in first

    last = messages[-1]["content"]
    assert search_b.meta["query"] in last
    assert last.endswith(f"\n\n{follow_up}")


# S6
def test_empty_search_contributes_nothing() -> None:
    empty = Node.search(
        query="quantum error correction 2026 benchmarks",
        results=[],
        conversation_id=CONVERSATION_ID,
    )
    user_text = "Any 2026 numbers on quantum error correction?"

    assert empty.content == ""
    assert model_facing_form(empty, _never_load) is None

    messages = build_context(
        [Node.user(user_text, CONVERSATION_ID), empty], _never_load
    )

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == user_text


# S7
def test_origin_marks_only_a_model_fetched_import() -> None:
    url = "https://textual.textualize.io/guide/reactivity/"
    page = "Reactive attributes call watch methods on change."

    fetched = Node.context(
        content=page,
        source_path=url,
        conversation_id=CONVERSATION_ID,
        origin="model",
    )
    included = Node.context(
        content=page, source_path=url, conversation_id=CONVERSATION_ID
    )

    assert fetched.meta["origin"] == "model"
    assert "origin" not in included.meta
    for node in (fetched, included):
        assert node.role == "context"
        assert node.node_type == "context"
        assert node.meta["source_path"] == url
