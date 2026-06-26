"""Behavioral tests for uniform command persistence in ConversationCore.

Contract: tests/specs/command-persistence.md
Code-blind: assertions trace to contract Expect clauses, never to assumed
implementation values.
"""

from ctx.core.conversation import ConversationCore
from ctx.models.nodes import Node


def _make_core(repo, test_provider, workspace, tokens=("hello",)):
    core = ConversationCore(repo, test_provider(list(tokens)), workspace)
    core.setup()
    return core


def _load_safe(repo, conversation_id):
    """Resume-style storage read. Treats a raise on the empty-id sentinel as
    'nothing persisted' (see ambiguity A4)."""
    try:
        return repo.load(conversation_id)
    except Exception:
        return []


def _contents(nodes):
    return [n.content for n in nodes]


# CP1 — set_model breadcrumb persists inside an active conversation
def test_set_model_breadcrumb_persists_when_active(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    core.submit("Draft a migration plan for the auth service.")

    node = core.set_model("anthropic/claude-3-opus")

    assert node.role == "system"
    assert node.node_type == "system"
    assert node.conversation_id == core.conversation_id

    loaded = repo.load(core.conversation_id)
    match = [n for n in loaded if n.content == node.content]
    assert match, "set_model breadcrumb was not persisted"
    persisted = match[0]
    assert persisted.role == "system"
    assert persisted.conversation_id == core.conversation_id


# CP2 — set_model breadcrumb content names the model
def test_set_model_breadcrumb_names_model(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    core.submit("What model are we using?")

    node = core.set_model("openai/gpt-4o")

    assert "openai/gpt-4o" in node.content


# CP3 — set_model breadcrumb survives a fresh reload (resume reads storage)
def test_set_model_breadcrumb_present_on_reload(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    core.submit("Pick a model for this thread.")

    node = core.set_model("mistral/large")
    cid = core.conversation_id

    reloaded = repo.load(cid)
    assert any(
        n.content == node.content and n.role == "system" for n in reloaded
    ), "breadcrumb did not survive a storage round-trip"


# CP4 — check_connectivity breadcrumb persists inside an active conversation
async def test_check_connectivity_breadcrumb_persists_when_active(
    repo, test_provider, workspace
):
    core = _make_core(repo, test_provider, workspace)
    core.submit("Is the provider reachable?")

    node = await core.check_connectivity("anthropic/claude-3-opus")

    assert node.role == "system"
    assert node.node_type == "system"
    assert node.conversation_id == core.conversation_id

    loaded = repo.load(core.conversation_id)
    match = [n for n in loaded if n.content == node.content]
    assert match, "check_connectivity breadcrumb was not persisted"
    assert match[0].role == "system"
    assert match[0].conversation_id == core.conversation_id


# CP5 — add_system_message breadcrumb persists inside an active conversation
def test_add_system_message_persists_when_active(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    core.submit("Continue the design discussion.")

    content = "Context budget exceeded; trimming oldest turns."
    node = core.add_system_message(content)

    assert node.content == content
    assert node.role == "system"
    assert node.node_type == "system"
    assert node.conversation_id == core.conversation_id

    loaded = repo.load(core.conversation_id)
    match = [n for n in loaded if n.content == content]
    assert match, "add_system_message breadcrumb was not persisted"
    assert match[0].role == "system"
    assert match[0].conversation_id == core.conversation_id


# CP6 — set_model breadcrumb is transient with NO active conversation
def test_set_model_transient_without_conversation(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    assert core.conversation_id == ""

    node = core.set_model("openai/gpt-4o-mini")

    assert node.conversation_id == ""
    loaded = _load_safe(repo, "")
    assert node.content not in _contents(loaded), (
        "breadcrumb raised with no conversation must not be persisted"
    )


# CP7 — add_system_message breadcrumb is transient with NO active conversation
def test_add_system_message_transient_without_conversation(
    repo, test_provider, workspace
):
    core = _make_core(repo, test_provider, workspace)
    assert core.conversation_id == ""

    content = "Standalone notice before any chat has started."
    node = core.add_system_message(content)

    assert node.conversation_id == ""
    loaded = _load_safe(repo, "")
    assert content not in _contents(loaded)


# CP8 — check_connectivity breadcrumb is transient with NO active conversation
async def test_check_connectivity_transient_without_conversation(
    repo, test_provider, workspace
):
    core = _make_core(repo, test_provider, workspace)
    assert core.conversation_id == ""

    node = await core.check_connectivity("anthropic/claude-3-opus")

    assert node.conversation_id == ""
    loaded = _load_safe(repo, "")
    assert node.content not in _contents(loaded)


# CP9 — Node.system factory honors durability via conversation_id argument
def test_node_system_factory_durability_seam():
    transient = Node.system("Heads up: rate limited.")
    durable = Node.system("Heads up: rate limited.", conversation_id="conv-123")

    for n in (transient, durable):
        assert n.role == "system"
        assert n.node_type == "system"
        assert n.content == "Heads up: rate limited."
        assert n.meta == {}

    assert transient.conversation_id == ""
    assert durable.conversation_id == "conv-123"


# CP10 — breadcrumbs carry the SAME conversation_id as the owning conversation
def test_breadcrumbs_filed_under_active_conversation(
    repo, test_provider, workspace
):
    core = _make_core(repo, test_provider, workspace)
    core.submit("Open a thread about deployment.")
    cid = core.conversation_id

    model_node = core.set_model("openai/gpt-4o")
    sys_node = core.add_system_message("Deployment window confirmed for Friday.")

    assert model_node.conversation_id == cid
    assert sys_node.conversation_id == cid

    loaded_contents = _contents(repo.load(cid))
    assert model_node.content in loaded_contents
    assert sys_node.content in loaded_contents


# CP11 — breadcrumb coexists with the conversation's real turns
def test_breadcrumb_does_not_displace_real_turns(repo, test_provider, workspace):
    core = _make_core(repo, test_provider, workspace)
    user_text = "Summarize the design doc."
    core.submit(user_text)

    breadcrumb = core.set_model("openai/gpt-4o")

    loaded = repo.load(core.conversation_id)
    user_nodes = [n for n in loaded if n.role == "user" and n.content == user_text]
    system_nodes = [n for n in loaded if n.content == breadcrumb.content]

    assert user_nodes, "the real user turn was lost after a breadcrumb was raised"
    assert system_nodes, "the breadcrumb is missing from the transcript"
