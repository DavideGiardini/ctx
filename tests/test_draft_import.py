"""Tests for ConversationCore.draft_import and .commit_import (ctx0 §4.2).

The prompt front door of the condense engine: draft an AI extract of a file's
raw content, then commit the edited extract as a content-on-node context node.
Assertions trace to the ctx0 concept and the docstrings' stated contract, never
to incidental implementation output.
"""

import pytest
from conftest import RecordingProvider

from ctx.core.conversation import DEFAULT_IMPORT_PROMPT, ConversationCore


def _core(repo, workspace, provider):
    core = ConversationCore(repo, provider, workspace)
    core.setup()
    return core


def _role(msg):
    return msg["role"] if isinstance(msg, dict) else msg.role


def _content(msg):
    return msg["content"] if isinstance(msg, dict) else msg.content


async def _drain(agen):
    return [tok async for tok in agen]


# --- draft_import -----------------------------------------------------------


async def test_draft_import_sends_system_then_user(repo, workspace, test_provider):
    # Exactly [system, user]; the raw file body is the user message.
    core = _core(repo, workspace, test_provider(["ok"]))
    rec = RecordingProvider(["extract"])
    core._provider = rec

    await _drain(core.draft_import("RAW FILE BODY", prompt="pull out signatures"))

    assert rec.called is True
    assert [_role(m) for m in rec.captured] == ["system", "user"]
    assert _content(rec.captured[0]) == "pull out signatures"
    assert _content(rec.captured[1]) == "RAW FILE BODY"


@pytest.mark.parametrize("blank", [None, "   "])
async def test_draft_import_blank_prompt_falls_back_to_default(
    repo, workspace, test_provider, blank
):
    core = _core(repo, workspace, test_provider(["ok"]))
    rec = RecordingProvider(["extract"])
    core._provider = rec

    await _drain(core.draft_import("some body", prompt=blank))

    assert _content(rec.captured[0]) == DEFAULT_IMPORT_PROMPT


async def test_draft_import_streams_tokens_verbatim(repo, workspace, test_provider):
    core = _core(repo, workspace, test_provider(["ok"]))
    core._provider = RecordingProvider(["ex", "tract"])

    tokens = await _drain(core.draft_import("body", prompt="p"))

    assert "".join(tokens) == "extract"


async def test_draft_import_empty_source_raises_before_provider_call(
    repo, workspace, test_provider
):
    core = _core(repo, workspace, test_provider(["ok"]))
    rec = RecordingProvider(["extract"])
    core._provider = rec

    with pytest.raises(ValueError):
        await _drain(core.draft_import("   \n  ", prompt="p"))
    assert rec.called is False


async def test_draft_import_is_a_meta_op_no_gauge_and_no_mutation(
    repo, workspace, test_provider
):
    # Drafting must not anchor the gauge (usage_generation unchanged) nor mutate
    # or append any node — committing is the separate commit_import.
    core = _core(repo, workspace, test_provider(["ok"]))
    core._provider = RecordingProvider(["extract"])
    gen_before = core.usage_generation
    nodes_before = list(core.nodes)

    await _drain(core.draft_import("body", prompt="p"))

    assert core.usage_generation == gen_before
    assert core.nodes == nodes_before


# --- commit_import ----------------------------------------------------------


def test_commit_import_builds_content_on_node_context_node(repo, workspace, test_provider):
    core = _core(repo, workspace, test_provider(["ok"]))

    node = core.commit_import(
        "docs/api.py",
        source_content="the entire raw file",
        extract="just the signatures",
        prompt="pull out signatures",
    )

    assert node.node_type == "context"
    assert node.role == "context"
    # content is the model-facing extract; the raw source is kept in meta.
    assert node.content == "just the signatures"
    assert node.meta["source_path"] == "docs/api.py"
    assert node.meta["prompt"] == "pull out signatures"
    assert node.meta["source_content"] == "the entire raw file"


def test_commit_import_appends_to_line_and_persists(repo, workspace, test_provider):
    core = _core(repo, workspace, test_provider(["ok"]))

    node = core.commit_import(
        "f.txt", source_content="raw", extract="ex", prompt="p"
    )

    assert node in core.nodes
    loaded = repo.load(core.conversation_id)
    assert any(n.id == node.id and n.content == "ex" for n in loaded)
