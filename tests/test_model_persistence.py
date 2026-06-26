"""Tests for conversation model persistence (contract specs/model-persistence.md).

Code-blind: assertions trace to the contract's Expect clauses, never to assumed
implementation values. Observable surfaces only: get_model(), resume_conversation()
return values, and core.model after a round-trip through a FRESH core/repo.
"""

from ctx.core.conversation import ConversationCore

# ---------------------------------------------------------------------------
# Storage layer
# ---------------------------------------------------------------------------

# MP1 — save stores the model; get_model returns it.
def test_save_stores_model_and_get_model_returns_it(repo, make_node):
    node = make_node(role="user", content="Summarize the design doc", conversation_id="conv-mp1")
    repo.save("conv-mp1", "Design review", [node], model="claude-opus-4")

    assert repo.get_model("conv-mp1") == "claude-opus-4"


# MP2 — save with default/empty model returns "" (not None).
def test_save_with_default_model_returns_empty_string(repo, make_node):
    node = make_node(role="user", content="What time is the standup?", conversation_id="conv-mp2")
    repo.save("conv-mp2", "Standup", [node])  # model defaults to ""

    assert repo.get_model("conv-mp2") == ""


# MP3 — get_model of an unknown conversation returns None.
def test_get_model_unknown_conversation_returns_none(repo):
    assert repo.get_model("conv-never-saved") is None


# MP4 — re-saving a conversation updates its model.
def test_resaving_conversation_updates_model(repo, make_node):
    node = make_node(role="user", content="Draft the release notes", conversation_id="conv-mp4")
    repo.save("conv-mp4", "Release notes", [node], model="model-a")
    repo.save("conv-mp4", "Release notes", [node], model="model-b")

    assert repo.get_model("conv-mp4") == "model-b"


# MP5 — saving only non-persistable nodes for a new id creates no row.
def test_save_only_nonpersistable_nodes_creates_no_row(repo, make_node):
    # conversation_id="" makes the node non-persistable (no owning conversation).
    transient = make_node(
        role="system",
        content="Switched model to claude-opus-4",
        node_type="message",
        conversation_id="",
    )
    repo.save("conv-mp5", "Ghost", [transient], model="claude-opus-4")

    assert repo.get_model("conv-mp5") is None


# ---------------------------------------------------------------------------
# Conversation layer — round-trip
# ---------------------------------------------------------------------------

# MP6 — floor test: set_model + submit persists; a FRESH core restores it.
def test_model_round_trips_through_fresh_core(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.set_model("claude-opus-4")
    user_node, _assistant_node = core.submit("Hello, can you help me plan a trip?")
    conv_id = user_node.conversation_id
    assert conv_id  # submit assigns a real conversation_id

    fresh = ConversationCore(repo, test_provider(["hi"]), workspace)
    fresh.resume_conversation(conv_id)

    assert fresh.model == "claude-opus-4"


# MP7 — resume restores the saved model, overriding the resumer's own model.
def test_resume_overrides_resumers_model_with_stored_model(repo, workspace, test_provider):
    saver = ConversationCore(repo, test_provider(["hi"]), workspace)
    saver.set_model("model-stored")
    user_node, _ = saver.submit("Write a haiku about autumn leaves")
    conv_id = user_node.conversation_id

    resumer = ConversationCore(repo, test_provider(["hi"]), workspace)
    resumer.set_model("model-current")  # different from the stored one
    resumer.resume_conversation(conv_id)

    assert resumer.model == "model-stored"


# MP8 — backward-compat: a stored "" model must NOT clobber the resumer's model.
def test_empty_stored_model_does_not_clobber_resumers_model(
    repo, workspace, test_provider, make_node
):
    # A pre-feature-style row: persistable node, empty model.
    persistable = make_node(
        role="user",
        content="What's on my calendar tomorrow?",
        conversation_id="conv-mp8",
    )
    repo.save("conv-mp8", "Legacy chat", [persistable], model="")
    assert repo.get_model("conv-mp8") == ""  # confirm the legacy shape

    resumer = ConversationCore(repo, test_provider(["hi"]), workspace)
    resumer.set_model("model-current")
    nodes = resumer.resume_conversation("conv-mp8")

    assert nodes  # it really resumed an existing row (guards a no-op false pass)
    assert resumer.model == "model-current"  # in-memory model preserved


# MP9 — resuming an unknown id returns [] and leaves the model untouched.
def test_resume_unknown_id_returns_empty_and_keeps_model(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.set_model("model-current")

    result = core.resume_conversation("conv-does-not-exist")

    assert result == []
    assert core.model == "model-current"


# MP10 — resume actually loads the persisted nodes (round-trip integrity guard).
def test_resume_loads_persisted_nodes(repo, workspace, test_provider):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.set_model("claude-opus-4")
    user_node, _ = core.submit("Explain the difference between TCP and UDP")
    conv_id = user_node.conversation_id

    fresh = ConversationCore(repo, test_provider(["hi"]), workspace)
    nodes = fresh.resume_conversation(conv_id)

    assert nodes  # a real conversation was restored, not a silent no-op
