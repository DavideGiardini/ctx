"""Behavioral tests for ctx.core.conversation.ConversationCore.

Tests are derived from the behavioral contract in tests/specs/conversation.md.
Each test cites its contract id (e.g. # C12) and asserts only on observable
behavior (return values, raised exceptions, persisted repo state) — never on
implementation internals.

C27 (BUG-3) previously recorded a known bug as xfail; it is now fixed and the marker
removed. See tests/specs/FOUND-BUGS.md.

The cancellation tests (C40 and the C42 cancellation case) model a realistic
mid-stream cancel: a provider yields a token then BLOCKS awaiting the next one;
a consuming asyncio task is cancelled while suspended awaiting that next token,
and we `await task` so the stream's cancellation handling (and its persist)
completes deterministically before we assert. No use of athrow.
"""

import asyncio
import sqlite3

import pytest

from ctx.core.config import DEFAULT_MODEL
from ctx.core.conversation import MAX_TITLE_LENGTH, ConversationCore
from ctx.core.provider import Usage
from ctx.core.storage import ConversationRepository
from ctx.models.nodes import Node


class CapturingProvider:
    def __init__(self, tokens):
        self._tokens = tokens
        self.captured_messages = None

    async def stream(self, messages, model, on_usage=None):
        self.captured_messages = messages
        for t in self._tokens:
            yield t

    async def check_connectivity(self, model):
        return (True, "ok")


class FailingProvider:
    def __init__(self, tokens):
        self._tokens = tokens

    async def stream(self, messages, model, on_usage=None):
        for t in self._tokens:
            yield t
        raise RuntimeError("boom")

    async def check_connectivity(self, model):
        return (True, "ok")


class FailingConnectivityProvider:
    def __init__(self, tokens, error):
        self._tokens = tokens
        self._error = error

    async def stream(self, messages, model, on_usage=None):
        for t in self._tokens:
            yield t

    async def check_connectivity(self, model):
        return (False, self._error)


class SaveCountingStorage:
    def __init__(self, inner):
        self._inner = inner
        self.save_count = 0

    def init(self):
        return self._inner.init()

    def save(self, cid, title, nodes, *, model="", active_leaf_id=None):
        self.save_count += 1
        return self._inner.save(
            cid, title, nodes, model=model, active_leaf_id=active_leaf_id
        )

    def load(self, cid):
        return self._inner.load(cid)

    def get_title(self, cid):
        return self._inner.get_title(cid)

    def get_model(self, cid):
        return self._inner.get_model(cid)

    def get_active_leaf(self, cid):
        return self._inner.get_active_leaf(cid)

    def list(self):
        return self._inner.list()

    def get_last(self):
        return self._inner.get_last()


class BlockingProvider:
    """Yields its first tokens, then blocks awaiting `gate` before the next token.

    Models a slow LLM suspended mid-stream so a consuming task can be cancelled
    while it is waiting for the next token (the realistic mid-stream cancel).
    """

    def __init__(self, before, gate):
        self._before = before          # tokens to yield before blocking
        self._gate = gate              # an asyncio.Event that is never set

    async def stream(self, messages, model, on_usage=None):
        for t in self._before:
            yield t
        await self._gate.wait()        # suspend here until cancelled
        yield "AFTER"                  # never reached

    async def check_connectivity(self, model):
        return (True, "ok")


async def _collect(agen):
    return [t async for t in agen]


# --------------------------------------------------------------------------
# Setup / lifecycle
# --------------------------------------------------------------------------

def test_setup_completes_and_core_usable(repo, test_provider, workspace):
    # C1
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    user_node, assistant_node = core.submit("Tell me about test setup")
    assert user_node.role == "user"
    assert assistant_node.role == "assistant"


def test_first_submit_sets_nonempty_conversation_id(repo, test_provider, workspace):
    # C2
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.submit("What is the capital of France?")
    assert isinstance(core.conversation_id, str)
    assert core.conversation_id != ""


# --------------------------------------------------------------------------
# Title derivation
# --------------------------------------------------------------------------

def test_short_newline_free_text_is_title_verbatim(repo, test_provider, workspace):
    # C3
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    text = "Plan the sprint review"
    core.submit(text)
    assert core.conversation_title == text


def test_newlines_in_short_text_become_spaces(repo, test_provider, workspace):
    # C4
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    text = "Line one\nLine two\nLine three"
    assert len(text) <= MAX_TITLE_LENGTH
    core.submit(text)
    title = core.conversation_title
    assert "\n" not in title
    assert title == text.replace("\n", " ")


def test_overlong_newline_free_text_is_truncated(repo, test_provider, workspace):
    # C5
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    text = "A" * (MAX_TITLE_LENGTH + 25)
    assert "\n" not in text
    core.submit(text)
    title = core.conversation_title
    assert len(title) == MAX_TITLE_LENGTH
    assert title == text[:MAX_TITLE_LENGTH]


# --------------------------------------------------------------------------
# Submit: node creation
# --------------------------------------------------------------------------

def test_first_submit_creates_user_and_assistant_nodes(repo, test_provider, workspace):
    # C6
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    text = "Explain dependency injection"
    core.submit(text)
    assert len(core.nodes) == 2
    assert core.nodes[-2].content == text
    assert core.nodes[-1].content == ""


def test_submit_nodes_carry_conversation_id(repo, test_provider, workspace):
    # C7
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    user_node, assistant_node = core.submit("How does TLS work?")
    assert user_node.conversation_id == core.conversation_id
    assert core.conversation_id != ""
    assert assistant_node.conversation_id == core.conversation_id


def test_submit_returns_user_then_assistant_matching_nodes(repo, test_provider, workspace):
    # C8
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    user_node, assistant_node = core.submit("Summarize the meeting notes")
    assert user_node is core.nodes[-2]
    assert assistant_node is core.nodes[-1]
    assert user_node.role == "user"
    assert assistant_node.role == "assistant"


def test_submit_persists_user_node_content(repo, test_provider, workspace):
    # C9
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    text = "What are the deployment steps?"
    core.submit(text)
    loaded = repo.load(core.conversation_id)
    assert any(n.content == text for n in loaded)


def test_second_submit_keeps_conversation_id(repo, test_provider, workspace):
    # C10
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.submit("First question about the schema")
    first_id = core.conversation_id
    core.submit("Second follow-up question")
    assert core.conversation_id == first_id
    assert core.conversation_id != ""


def test_title_fixed_after_first_message(repo, test_provider, workspace):
    # C11
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    first_text = "Design the billing module"
    core.submit(first_text)
    core.submit("Now describe the refund flow instead")
    assert core.conversation_title == first_text


def test_second_submit_grows_nodes_by_two(repo, test_provider, workspace):
    # C12
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.submit("Initial question on caching")
    n = len(core.nodes)
    text2 = "Follow up about cache invalidation"
    core.submit(text2)
    assert len(core.nodes) == n + 2
    assert core.nodes[-2].content == text2
    assert core.nodes[-1].content == ""


# --------------------------------------------------------------------------
# Model selection
# --------------------------------------------------------------------------

def test_set_model_changes_model(repo, test_provider, workspace):
    # C13
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.set_model("some/other-model")
    assert core.model == "some/other-model"


def test_set_model_appends_system_notice(repo, test_provider, workspace):
    # C14
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    model_name = "anthropic/claude-experimental"
    returned = core.set_model(model_name)
    notice = core.nodes[-1]
    assert notice.role == "system"
    assert notice.node_type == "system"
    assert model_name in notice.content
    assert returned is notice


# C15 (set_model notice now persists within an active conversation) moved to
# test_command_persistence.py CP1/CP3 under the uniform-persistence policy.


def test_set_model_preserves_persisted_user_nodes(repo, test_provider, workspace):
    # C16
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    user_text = "Persist this real user question"
    core.submit(user_text)
    core.set_model("openai/gpt-experimental")
    loaded = repo.load(core.conversation_id)
    assert any(n.content == user_text for n in loaded)


# --------------------------------------------------------------------------
# Connectivity check
# --------------------------------------------------------------------------

async def test_check_connectivity_success_notice(repo, test_provider, workspace):
    # C17
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    returned = await core.check_connectivity("anthropic/claude-3")
    notice = core.nodes[-1]
    assert returned is notice
    assert notice.role == "system"
    assert notice.node_type == "system"
    assert "some-error-xyz" not in notice.content


async def test_check_connectivity_failure_reports_error(repo, workspace):
    # C18
    provider = FailingConnectivityProvider(["hi"], "some-error-xyz")
    core = ConversationCore(repo, provider, workspace)
    core.setup()
    returned = await core.check_connectivity("anthropic/claude-3")
    notice = core.nodes[-1]
    assert returned is notice
    assert notice.role == "system"
    assert notice.node_type == "system"
    assert "some-error-xyz" in notice.content


# C19 (connectivity notice now persists within an active conversation) moved to
# test_command_persistence.py CP4 under the uniform-persistence policy.


# --------------------------------------------------------------------------
# New conversation / reset
# --------------------------------------------------------------------------

def test_new_conversation_preserves_old_persisted_nodes(repo, test_provider, workspace):
    # C20
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    user_text = "Old conversation user message"
    core.submit(user_text)
    old_id = core.conversation_id
    core.new_conversation()
    loaded = repo.load(old_id)
    assert any(n.content == user_text for n in loaded)


def test_new_conversation_resets_state(repo, test_provider, workspace):
    # C21
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.submit("Some active conversation message")
    core.set_model("custom/non-default-model")
    assert core.nodes  # non-empty before reset
    core.new_conversation()
    assert core.nodes == []
    assert core.conversation_id == ""
    assert core.conversation_title == ""
    assert core.model == DEFAULT_MODEL


def test_new_conversation_returns_transient_notice(repo, test_provider, workspace):
    # C22
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.submit("Build up some state first")
    returned = core.new_conversation()
    assert returned.role == "system"
    assert returned.node_type == "system"
    assert returned.conversation_id == ""
    assert core.nodes == []


# --------------------------------------------------------------------------
# Resume conversation
# --------------------------------------------------------------------------

def test_resume_restores_conversation_id(repo, test_provider, workspace):
    # C23
    first = ConversationCore(repo, test_provider(["hi"]), workspace)
    first.setup()
    first.submit("A question worth resuming later")
    saved_id = first.conversation_id

    fresh = ConversationCore(repo, test_provider(["hi"]), workspace)
    fresh.setup()
    fresh.resume_conversation(saved_id)
    assert fresh.conversation_id == saved_id


def test_resume_restores_title_from_first_user_text(repo, test_provider, workspace):
    # C24
    short_text = "Resume with this short title"
    first = ConversationCore(repo, test_provider(["hi"]), workspace)
    first.setup()
    first.submit(short_text)
    short_id = first.conversation_id

    fresh = ConversationCore(repo, test_provider(["hi"]), workspace)
    fresh.setup()
    fresh.resume_conversation(short_id)
    assert fresh.conversation_title == short_text

    long_text = "B" * (MAX_TITLE_LENGTH + 40)
    first2 = ConversationCore(repo, test_provider(["hi"]), workspace)
    first2.setup()
    first2.submit(long_text)
    long_id = first2.conversation_id

    fresh2 = ConversationCore(repo, test_provider(["hi"]), workspace)
    fresh2.setup()
    fresh2.resume_conversation(long_id)
    assert fresh2.conversation_title == long_text[:MAX_TITLE_LENGTH]


def test_resume_restores_node_list(repo, test_provider, workspace):
    # C25
    first = ConversationCore(repo, test_provider(["hi"]), workspace)
    first.setup()
    first.submit("First question for the resumed list")
    first.submit("Second question for the resumed list")
    saved_id = first.conversation_id
    expected = repo.load(saved_id)

    fresh = ConversationCore(repo, test_provider(["hi"]), workspace)
    fresh.setup()
    returned = fresh.resume_conversation(saved_id)
    assert returned  # non-empty
    assert len(returned) == len(expected)
    assert [(n.role, n.content) for n in returned] == [
        (n.role, n.content) for n in expected
    ]
    assert [(n.role, n.content) for n in fresh.nodes] == [
        (n.role, n.content) for n in expected
    ]


def test_resume_unknown_id_returns_empty_list(repo, test_provider, workspace):
    # C26
    fresh = ConversationCore(repo, test_provider(["hi"]), workspace)
    fresh.setup()
    result = fresh.resume_conversation("never-saved-conversation-id")
    assert result == []


def test_resume_unknown_id_leaves_current_state_unchanged(repo, test_provider, workspace):
    # C27
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.submit("An in-progress conversation that must survive")
    before_id = core.conversation_id
    before_title = core.conversation_title
    before_nodes = [(n.role, n.content) for n in core.nodes]

    core.resume_conversation("an-unknown-conversation-id")

    assert core.conversation_id == before_id
    assert core.conversation_title == before_title
    assert [(n.role, n.content) for n in core.nodes] == before_nodes


# --------------------------------------------------------------------------
# Include files (context nodes)
# --------------------------------------------------------------------------

def test_include_files_sets_conversation_id(repo, test_provider, workspace):
    # C28
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.include_files(["docs/spec.md"])
    assert isinstance(core.conversation_id, str)
    assert core.conversation_id != ""


def test_include_files_appends_context_nodes_in_order(repo, test_provider, workspace):
    # C29
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    paths = ["docs/a.md", "src/b.py", "notes/c.txt"]
    before = len(core.nodes)
    core.include_files(paths)
    new_nodes = core.nodes[before:]
    assert len(new_nodes) == 3
    assert all(n.node_type == "context" for n in new_nodes)
    assert [n.meta["source_path"] for n in new_nodes] == paths


def test_include_files_records_source_path_per_node(repo, test_provider, workspace):
    # C30
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    paths = ["docs/a.md", "src/b.py", "notes/c.txt"]
    before = len(core.nodes)
    core.include_files(paths)
    new_nodes = core.nodes[before:]
    for i, path in enumerate(paths):
        assert new_nodes[i].meta["source_path"] == path


def test_include_files_returns_appended_nodes(repo, test_provider, workspace):
    # C31
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    paths = ["docs/a.md", "src/b.py", "notes/c.txt"]
    returned = core.include_files(paths)
    assert len(returned) == len(paths)
    for i, path in enumerate(paths):
        assert returned[i].meta["source_path"] == path
    assert returned == core.nodes[-len(paths):]


def test_include_files_persists_context_node(repo, test_provider, workspace):
    # C32
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.include_files(["docs/spec.md"])
    loaded = repo.load(core.conversation_id)
    matches = [
        n for n in loaded
        if n.node_type == "context" and n.meta.get("source_path") == "docs/spec.md"
    ]
    assert len(matches) >= 1


# --------------------------------------------------------------------------
# System messages
# --------------------------------------------------------------------------

def test_add_system_message_returns_transient_notice(repo, test_provider, workspace):
    # C33
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    text = "Heads up: rate limited"
    returned = core.add_system_message(text)
    assert returned.content == text
    assert returned.role == "system"
    assert returned.node_type == "system"
    assert returned is core.nodes[-1]


# C34 (add_system_message now persists within an active conversation) moved to
# test_command_persistence.py CP5 under the uniform-persistence policy.


def test_add_system_message_notice_is_transient_without_conversation(
    repo, test_provider, workspace
):
    # C35 — no active conversation → notice carries empty conversation_id, stays transient
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    returned = core.add_system_message("A transient system note")
    assert returned.conversation_id == ""


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------

async def test_stream_yields_tokens_in_order(repo, test_provider, workspace):
    # C36
    core = ConversationCore(repo, test_provider(["Hello", ", ", "world"]), workspace)
    core.setup()
    _, assistant_node = core.submit("Greet the world")
    tokens = await _collect(core.stream(assistant_node))
    assert tokens == ["Hello", ", ", "world"]


async def test_stream_accumulates_into_assistant_content(repo, test_provider, workspace):
    # C37
    core = ConversationCore(repo, test_provider(["Hello", ", ", "world"]), workspace)
    core.setup()
    _, assistant_node = core.submit("Greet the world")
    await _collect(core.stream(assistant_node))
    assert assistant_node.content == "Hello, world"


async def test_stream_sends_prior_user_text_not_empty_assistant(repo, workspace):
    # C38
    provider = CapturingProvider(["ok"])
    core = ConversationCore(repo, provider, workspace)
    core.setup()
    user_text = "What messages get sent to the provider?"
    _, assistant_node = core.submit(user_text)
    await _collect(core.stream(assistant_node))
    messages = provider.captured_messages
    assert messages is not None
    # The prior user text must be carried to the provider.
    assert any(user_text in str(m) for m in messages)
    # No assistant message with empty content should be sent.
    for m in messages:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        if role == "assistant":
            assert content != ""


async def test_stream_excludes_streamed_node_by_identity(repo, workspace):
    # 0006 #1 — the streamed assistant node is excluded from the LLM context by
    # identity, not by position: it must be dropped even when it is NOT the last
    # node and even when it already carries (partial) content. A positional
    # `self.nodes[:-1]` would wrongly send it once another node follows it.
    provider = CapturingProvider(["ok"])
    core = ConversationCore(repo, provider, workspace)
    core.setup()
    _, assistant_node = core.submit("What gets sent?")
    # Give the streamed node detectable content and displace it from the tail.
    assistant_node.content = "SENTINEL_PARTIAL_DRAFT"
    # Append onto the active line via the real graph mutator (the flat list is now
    # a read-only projection over the append-only graph, ADR-0016).
    core._append_to_line(Node.user("A later user turn", core.conversation_id))
    await _collect(core.stream(assistant_node))
    messages = provider.captured_messages
    assert messages is not None
    # The streamed node's own content must NOT be fed back as context...
    assert all("SENTINEL_PARTIAL_DRAFT" not in str(m) for m in messages)
    # ...while the node now occupying the tail position IS included.
    assert any("A later user turn" in str(m) for m in messages)


async def test_stream_persists_full_assistant_content(repo, test_provider, workspace):
    # C39
    core = ConversationCore(repo, test_provider(["The ", "answer ", "is ", "42"]), workspace)
    core.setup()
    _, assistant_node = core.submit("What is the answer?")
    await _collect(core.stream(assistant_node))
    loaded = repo.load(core.conversation_id)
    assert any(
        n.role == "assistant" and n.content == "The answer is 42" for n in loaded
    )


async def test_stream_cancel_persists_partial_content(repo, workspace):
    # C40 — realistic mid-stream cancel: provider yields "a" then blocks; the
    # consuming task is cancelled while suspended awaiting the next token, and
    # we await the task so cancellation handling (persist) completes before we
    # assert. The streamed-so-far token "a" must be persisted.
    gate = asyncio.Event()
    core = ConversationCore(repo, BlockingProvider(["a"], gate), workspace)
    core.setup()
    _, assistant_node = core.submit("Stream something cancellable")
    first_seen = asyncio.Event()

    async def _consume():
        async for tok in core.stream(assistant_node):
            if tok == "a":
                first_seen.set()

    task = asyncio.create_task(_consume())
    await first_seen.wait()      # ensure the first token was streamed
    await asyncio.sleep(0)       # let the consumer suspend awaiting the next token
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task               # cancellation handling (persist) completes here

    loaded = repo.load(core.conversation_id)
    assert any(n.role == "assistant" and n.content == "a" for n in loaded)


async def test_stream_error_persists_partial_content(repo, workspace):
    # C41
    core = ConversationCore(repo, FailingProvider(["x", "y"]), workspace)
    core.setup()
    _, assistant_node = core.submit("Stream that will fail")
    with pytest.raises(RuntimeError):
        await _collect(core.stream(assistant_node))
    loaded = repo.load(core.conversation_id)
    assert any(n.role == "assistant" and n.content == "xy" for n in loaded)


# --------------------------------------------------------------------------
# Persist count invariant on stream completion
# --------------------------------------------------------------------------

async def test_stream_success_saves_exactly_once(repo, test_provider, workspace):
    # C42 success
    storage = SaveCountingStorage(repo)
    core = ConversationCore(storage, test_provider(["done"]), workspace)
    core.setup()
    _, assistant_node = core.submit("A successful stream")
    before = storage.save_count
    await _collect(core.stream(assistant_node))
    assert storage.save_count == before + 1


async def test_stream_cancel_saves_exactly_once(repo, workspace):
    # C42 cancellation — same realistic mid-stream cancel pattern as C40, but
    # with SaveCountingStorage. The cancellation handling must persist exactly
    # once. Snapshot save_count right before cancelling (after the stream has
    # started), then assert it increased by exactly 1 after the task raises.
    gate = asyncio.Event()
    storage = SaveCountingStorage(repo)
    core = ConversationCore(storage, BlockingProvider(["a"], gate), workspace)
    core.setup()
    _, assistant_node = core.submit("Stream something cancellable")
    first_seen = asyncio.Event()

    async def _consume():
        async for tok in core.stream(assistant_node):
            if tok == "a":
                first_seen.set()

    task = asyncio.create_task(_consume())
    await first_seen.wait()      # ensure the first token was streamed
    await asyncio.sleep(0)       # let the consumer suspend awaiting the next token
    before = storage.save_count  # snapshot AFTER stream started, BEFORE cancel
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task               # cancellation handling (persist) completes here

    assert storage.save_count == before + 1


async def test_stream_error_saves_exactly_once(repo, workspace):
    # C42 error
    storage = SaveCountingStorage(repo)
    core = ConversationCore(storage, FailingProvider(["x", "y"]), workspace)
    core.setup()
    _, assistant_node = core.submit("A stream that errors")
    before = storage.save_count
    with pytest.raises(RuntimeError):
        await _collect(core.stream(assistant_node))
    assert storage.save_count == before + 1


# --------------------------------------------------------------------------
# Persist
# --------------------------------------------------------------------------

def test_persist_reflects_in_memory_edits(repo, test_provider, workspace):
    # C43
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.submit("Original user content to be edited")
    # Edit a real (persistable) node's content in memory.
    edited = "Edited user content after the fact"
    target = None
    for n in core.nodes:
        if n.role == "user":
            target = n
    assert target is not None
    target.content = edited
    core.persist()
    loaded = repo.load(core.conversation_id)
    assert any(n.content == edited for n in loaded)


def test_persist_without_conversation_is_noop(repo, test_provider, workspace):
    # C44
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    assert core.conversation_id == ""
    core.persist()  # must not raise
    assert core.conversation_id == ""
    assert repo.load("") == []


def test_persist_excludes_idless_notices(repo, test_provider, workspace):
    # C45 — the storage filter is keyed on conversation_id, not "system-ness":
    # a breadcrumb raised before any conversation exists is id-less and dropped on
    # save, while the real turns that follow it persist.
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    idless_notice = core.add_system_message("Standalone notice before any chat")
    assert idless_notice.conversation_id == ""
    user_text = "A real user message that must persist"
    core.submit(user_text)
    loaded = repo.load(core.conversation_id)
    assert any(n.content == user_text for n in loaded)
    assert all(n.content != idless_notice.content for n in loaded)


def test_persisted_context_node_round_trips(repo, test_provider, workspace):
    # C46
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.include_files(["docs/spec.md"])
    cid = core.conversation_id
    core.persist()
    loaded = repo.load(cid)
    assert any(
        n.node_type == "context" and n.meta.get("source_path") == "docs/spec.md"
        for n in loaded
    )


class ModelCapturingProvider:
    """Captures the messages and model handed to stream()."""

    def __init__(self, tokens):
        self._tokens = tokens
        self.captured_messages = None
        self.captured_model = None

    async def stream(self, messages, model, on_usage=None):
        self.captured_messages = messages
        self.captured_model = model
        for t in self._tokens:
            yield t

    async def check_connectivity(self, model):
        return (True, "ok")


# C47 — fresh ConversationCore has empty conversation state and default model.
def test_c47_initial_state(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    assert core.conversation_id == ""
    assert core.conversation_title == ""
    assert core.model == DEFAULT_MODEL
    assert core.nodes == []


# Task 0006 #3 — the default model is sourced from config.py (the user-overridable
# default), not a hardcoded core constant. A custom config "model" must be adopted
# both at construction and on /new reset. Guards against a mutation that hardcodes
# the default (which the C21/C47 default-constant checks would not catch).
def test_default_model_sourced_from_config(
    repo, test_provider, workspace, tmp_path, monkeypatch
):
    import json

    import ctx.core.config as config_module

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"model": "test/custom-default-model"}))
    monkeypatch.setattr(config_module, "CONFIG_PATH", cfg)

    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    assert core.model == "test/custom-default-model"

    core.setup()
    core.submit("hello")
    core.set_model("other/switched-model")
    core.new_conversation()
    assert core.model == "test/custom-default-model"


# C48 — new_conversation returns a notice with non-empty string content.
def test_c48_new_conversation_notice_has_content(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.submit("What is the capital of France?")
    node = core.new_conversation()
    assert isinstance(node.content, str)
    assert node.content != ""


# C49 — connectivity success notice names the model that was checked.
async def test_c49_connectivity_notice_names_model(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    notice = await core.check_connectivity("vendor/distinct-model-name")
    assert notice.role == "system"
    assert notice.node_type == "system"
    assert "vendor/distinct-model-name" in notice.content


# C50 — resume re-derives the title from the first user message, flattening newlines.
def test_c50_resume_rederives_title_flattening_newlines(repo, test_provider, workspace):
    first = ConversationCore(repo, test_provider(["answer"]), workspace)
    first.setup()
    message = "alpha\nbeta\ngamma"
    assert len(message) <= MAX_TITLE_LENGTH
    first.submit(message)
    conversation_id = first.conversation_id

    fresh = ConversationCore(repo, test_provider(["answer"]), workspace)
    fresh.resume_conversation(conversation_id)
    assert "\n" not in fresh.conversation_title
    assert fresh.conversation_title == "alpha beta gamma"


# C51 — resume of a conversation with no user message yields empty title and no crash.
def test_c51_resume_no_user_message_empty_title(repo, test_provider, workspace):
    first = ConversationCore(repo, test_provider(["answer"]), workspace)
    first.setup()
    first.include_files(["a.md", "b.py"])
    conversation_id = first.conversation_id
    assert conversation_id != ""

    fresh = ConversationCore(repo, test_provider(["answer"]), workspace)
    nodes = fresh.resume_conversation(conversation_id)
    assert fresh.conversation_id == conversation_id
    assert isinstance(nodes, list)
    assert len(nodes) > 0
    assert fresh.conversation_title == ""


# C52 — include_files on a fresh core does not set a title.
def test_c52_include_files_leaves_title_empty(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.include_files(["docs/spec.md"])
    assert core.conversation_title == ""


# C53 — include_files returns context nodes whose role is "context".
def test_c53_context_nodes_have_context_role(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    returned = core.include_files(["docs/a.md", "src/b.py"])
    assert len(returned) > 0
    for node in returned:
        assert node.role == "context"


# C54 — stream expands an included file's body into the model context.
async def test_c54_stream_expands_included_file(repo, workspace):
    (workspace.context_dir / "notes.txt").write_text(
        "UNIQUE_FILE_BODY_XYZ", encoding="utf-8"
    )
    provider = ModelCapturingProvider(["ok"])
    core = ConversationCore(repo, provider, workspace)
    core.setup()
    core.include_files(["notes.txt"])
    _, assistant_node = core.submit("Please use the included notes")
    await _collect(core.stream(assistant_node))
    assert provider.captured_messages is not None
    assert any("UNIQUE_FILE_BODY_XYZ" in str(m) for m in provider.captured_messages)


# C55 — stream feeds the full prior multi-turn history, not just the first turn.
async def test_c55_stream_includes_full_history(repo, workspace):
    provider = ModelCapturingProvider(["ok"])
    core = ConversationCore(repo, provider, workspace)
    core.setup()

    _, first_assistant = core.submit("first question alpha")
    await _collect(core.stream(first_assistant))

    _, second_assistant = core.submit("second question beta")
    await _collect(core.stream(second_assistant))

    captured = str(provider.captured_messages)
    assert "first question alpha" in captured
    assert "second question beta" in captured


# C56 — stream is called with the core's current model.
async def test_c56_stream_uses_current_model(repo, workspace):
    provider = ModelCapturingProvider(["ok"])
    core = ConversationCore(repo, provider, workspace)
    core.setup()
    core.set_model("vendor/specific-model")
    _, assistant_node = core.submit("Which model is this?")
    await _collect(core.stream(assistant_node))
    assert provider.captured_model == "vendor/specific-model"
    assert provider.captured_model == core.model


# C57. include_files with an empty path list appends nothing and returns an empty list.
def test_c57_include_files_empty_list_is_noop(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()

    count_before = len(core.nodes)

    result = core.include_files([])

    # returns an empty list
    assert result == []
    # node count unchanged
    assert len(core.nodes) == count_before
    # no context node created
    assert not any(node.node_type == "context" for node in core.nodes)


# --------------------------------------------------------------------------
# Calibration (Task 5 — provider usage anchors the header gauge)
# --------------------------------------------------------------------------

async def _run_turn(core, message):
    """Submit a message and fully drain the resulting stream."""
    _, assistant = core.submit(message)
    tokens = [tok async for tok in core.stream(assistant)]
    return tokens


# C58 - sane usage -> positive float calibration; last_usage is exactly the fed Usage.
async def test_sane_usage_sets_positive_calibration_and_exact_usage(
    repo, test_provider, workspace
):
    fed = Usage(prompt_tokens=12, completion_tokens=5, total_tokens=17)
    core = ConversationCore(
        repo, test_provider(["Hello", " there"], usage=fed), workspace
    )
    core.setup()

    await _run_turn(core, "Summarize the meeting notes for me")

    assert isinstance(core.calibration, float)
    assert core.calibration > 0
    assert core.last_usage == fed


# C59 - calibration formula is prompt_tokens / local_sum (ratio invariant).
# Two identically-built cores measure the SAME context, so local_sum cancels:
# calibration_a / calibration_b == prompt_tokens_a / prompt_tokens_b.
async def test_calibration_ratio_matches_prompt_token_ratio(
    repo_factory, test_provider, workspace_factory
):
    message = "Draft a short reply to the client"
    pa, pb = 12, 24

    core_a = ConversationCore(
        repo_factory(),
        test_provider(["ok"], usage=Usage(pa, 4, pa + 4)),
        workspace_factory(),
    )
    core_a.setup()
    await _run_turn(core_a, message)

    core_b = ConversationCore(
        repo_factory(),
        test_provider(["ok"], usage=Usage(pb, 4, pb + 4)),
        workspace_factory(),
    )
    core_b.setup()
    await _run_turn(core_b, message)

    assert core_a.calibration > 0
    assert core_b.calibration > 0
    # local_sum identical for identical context -> ratio of calibrations == ratio of prompt_tokens
    assert abs(
        (core_a.calibration / core_b.calibration) - (pa / pb)
    ) < 1e-6


# C60 - no reported usage leaves both values at None.
async def test_no_usage_leaves_calibration_and_last_usage_none(
    repo, test_provider, workspace
):
    core = ConversationCore(repo, test_provider(["one", " two"]), workspace)
    core.setup()

    await _run_turn(core, "What is on the agenda today")

    assert core.calibration is None
    assert core.last_usage is None


# C61 - prompt_tokens == 0 is rejected.
async def test_zero_prompt_tokens_rejected(repo, test_provider, workspace):
    bogus = Usage(prompt_tokens=0, completion_tokens=6, total_tokens=6)
    core = ConversationCore(repo, test_provider(["resp"], usage=bogus), workspace)
    core.setup()

    await _run_turn(core, "Tell me a quick fact")

    assert core.calibration is None
    assert core.last_usage is None


# C62 - prompt_tokens wildly out of range is rejected.
async def test_out_of_range_prompt_tokens_rejected(repo, test_provider, workspace):
    bogus = Usage(prompt_tokens=10_000_000, completion_tokens=3, total_tokens=10_000_003)
    core = ConversationCore(repo, test_provider(["resp"], usage=bogus), workspace)
    core.setup()

    # tiny context -> local sum ~10-30 tokens, 10M is far beyond CALIBRATION_TOLERANCE x
    await _run_turn(core, "Hi")

    assert core.calibration is None
    assert core.last_usage is None


# C63 - fresh core (no streamed turn) has no calibration and no usage.
async def test_fresh_core_has_no_calibration_or_usage(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["unused"]), workspace)
    core.setup()

    assert core.calibration is None
    assert core.last_usage is None


# C64 - a trusted calibration survives a later NO-USAGE turn (left unchanged).
async def test_sane_calibration_survives_later_no_usage_turn(
    repo, varying_provider, workspace
):
    fed = Usage(prompt_tokens=12, completion_tokens=5, total_tokens=17)
    # turn 1 reports sane usage; turn 2 reports nothing.
    provider = varying_provider([(["a"], fed), (["b"], None)])
    core = ConversationCore(repo, provider, workspace)
    core.setup()

    await _run_turn(core, "First question please")
    sane_calibration = core.calibration
    assert sane_calibration is not None
    assert core.last_usage == fed

    await _run_turn(core, "Second question please")

    assert core.calibration == sane_calibration
    assert core.last_usage == fed


# C66 - usage_generation bumps only when a usage is ADOPTED, and is immune to
# the provider reusing one Usage object across turns. A fresh core is 0; a sane
# turn bumps it; a no-usage turn and a bogus-usage turn leave it; a later turn
# reporting the SAME object as turn 1 bumps it again (identity must not matter).
async def test_usage_generation_bumps_only_on_adoption(
    repo, varying_provider, workspace
):
    fed = Usage(prompt_tokens=12, completion_tokens=5, total_tokens=17)
    bogus = Usage(prompt_tokens=10_000_000, completion_tokens=3, total_tokens=10_000_003)
    # turn 4 feeds the SAME `fed` object as turn 1 on purpose.
    provider = varying_provider(
        [(["a"], fed), (["b"], None), (["c"], bogus), (["d"], fed)]
    )
    core = ConversationCore(repo, provider, workspace)
    core.setup()

    assert core.usage_generation == 0

    await _run_turn(core, "First question please")
    assert core.usage_generation == 1

    await _run_turn(core, "Second question please")  # no usage
    assert core.usage_generation == 1

    await _run_turn(core, "Third question please")  # bogus usage
    assert core.usage_generation == 1

    await _run_turn(core, "Fourth question please")  # same Usage object as turn 1
    assert core.usage_generation == 2


# C65 - a trusted calibration survives a later BOGUS-USAGE turn (left unchanged).
async def test_sane_calibration_survives_later_bogus_usage_turn(
    repo, varying_provider, workspace
):
    fed = Usage(prompt_tokens=12, completion_tokens=5, total_tokens=17)
    bogus = Usage(prompt_tokens=10_000_000, completion_tokens=3, total_tokens=10_000_003)
    provider = varying_provider([(["a"], fed), (["b"], bogus)])
    core = ConversationCore(repo, provider, workspace)
    core.setup()

    await _run_turn(core, "First question please")
    sane_calibration = core.calibration
    assert sane_calibration is not None
    assert core.last_usage == fed

    await _run_turn(core, "Second question please")

    assert core.calibration == sane_calibration
    assert core.last_usage == fed


# --------------------------------------------------------------------------
# Append-only conversation graph (ADR-0016). See conversation.md C67-C78:
# current_view()/nodes project the active line (root-first walk of prev_id from
# the tip); rewind moves the tip inclusively without deleting the abandoned tail;
# submit after a rewind diverges; migrated linear DBs project to rowid order.
# --------------------------------------------------------------------------

# A pre-graph flat DB (has the `model` column but no graph columns), for the
# migrated-linear-equivalence test C78. init() must add + backfill the graph.
_PRE_GRAPH_SCHEMA = """
CREATE TABLE conversations (
    id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE nodes (
    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', node_type TEXT NOT NULL DEFAULT 'message',
    meta TEXT NOT NULL DEFAULT '{}'
);
"""


def _make_pre_graph_db(db_path, cid, rows):
    """Build a pre-graph (flat/linear) conversation DB via raw sqlite3.

    rows: list of (node_id, role, content) inserted in order; sqlite assigns
    rowid in insertion order, which defines the linear ordering the migration
    must preserve.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_PRE_GRAPH_SCHEMA)
        conn.execute(
            "INSERT INTO conversations (id, title, model, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (cid, "Migrated chat", "test-model", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        for node_id, role, content in rows:
            conn.execute(
                "INSERT INTO nodes (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
                (node_id, cid, role, content),
            )
        conn.commit()
    finally:
        conn.close()


# C67
def test_c67_fresh_core_empty_view(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    assert core.current_view() == []
    assert core.nodes == []


# C68
def test_c68_two_turns_root_first_order(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    u1, a1 = core.submit("What is the capital of France?")
    u2, a2 = core.submit("And its population?")
    view = core.current_view()
    assert [n.id for n in view] == [u1.id, a1.id, u2.id, a2.id]
    assert view[0].id == u1.id
    assert view[0].role == u1.role
    assert view[0].content == u1.content
    assert view[-1].id == a2.id
    assert view[-1].role == a2.role
    assert view[-1].content == a2.content


# C69
def test_c69_nodes_property_recomputed(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    u1, a1 = core.submit("Explain recursion briefly.")
    assert [n.id for n in core.nodes] == [n.id for n in core.current_view()]
    assert [n.id for n in core.nodes] == [u1.id, a1.id]
    u2, a2 = core.submit("Now give an example.")
    # A fresh read of the property reflects the new state, not a frozen snapshot.
    assert [n.id for n in core.nodes] == [u1.id, a1.id, u2.id, a2.id]


# C70
def test_c70_rewind_shortens_view(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    u1, a1 = core.submit("First question about databases.")
    u2, a2 = core.submit("Second follow-up question.")
    u3, a3 = core.submit("Third follow-up question.")
    core.rewind(a1.id)
    view = core.current_view()
    assert [n.id for n in view] == [u1.id, a1.id]
    assert view[-1].id == a1.id
    view_ids = {n.id for n in view}
    for dropped in (u2.id, a2.id, u3.id, a3.id):
        assert dropped not in view_ids


# C71
def test_c71_rewind_returns_current_view(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    u1, a1 = core.submit("Question one.")
    u2, a2 = core.submit("Question two.")
    u3, a3 = core.submit("Question three.")
    r = core.rewind(a1.id)
    after = core.current_view()
    assert [n.id for n in r] == [n.id for n in after]
    assert [n.id for n in r] == [u1.id, a1.id]


# C72
def test_c72_rewind_to_tip_is_noop(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    u1, a1 = core.submit("Tell me about oceans.")
    u2, a2 = core.submit("Tell me about mountains.")
    view_before = [n.id for n in core.current_view()]
    assert view_before == [u1.id, a1.id, u2.id, a2.id]
    core.rewind(a2.id)
    assert [n.id for n in core.current_view()] == view_before


# C73
def test_c73_rewind_unknown_id_raises(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.submit("Some initial question.")
    core.submit("A second question.")
    view_before = [n.id for n in core.current_view()]
    with pytest.raises(ValueError):
        core.rewind("nonexistent-node-id")
    assert [n.id for n in core.current_view()] == view_before


# C74
def test_c74_rewind_to_abandoned_tail_raises(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    u1, a1 = core.submit("Original question one.")
    u2, a2 = core.submit("Original question two.")
    u3, a3 = core.submit("Original question three.")
    core.rewind(a1.id)
    core.submit("A divergent branch question.")  # u4, a4
    view_before = [n.id for n in core.current_view()]
    with pytest.raises(ValueError):
        core.rewind(u3.id)  # u3 is on the abandoned tail, off the active line
    assert [n.id for n in core.current_view()] == view_before


# C75
def test_c75_resume_after_rewind_uses_rewind_tip(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    u1, a1 = core.submit("Persisted question one.")
    u2, a2 = core.submit("Persisted question two.")
    u3, a3 = core.submit("Persisted question three.")
    cid = core.conversation_id
    core.rewind(a1.id)

    reloaded = ConversationCore(repo, test_provider(["hi"]), workspace)
    reloaded.resume_conversation(cid)
    view = reloaded.current_view()
    assert [n.id for n in view] == [u1.id, a1.id]
    assert view[-1].id == a1.id
    assert view[0].role == u1.role
    assert view[0].content == u1.content
    assert view[-1].role == a1.role
    assert view[-1].content == a1.content


# C76
def test_c76_abandoned_tail_preserved_after_reload(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    u1, a1 = core.submit("Branching question one.")
    u2, a2 = core.submit("Branching question two.")
    u3, a3 = core.submit("Branching question three.")
    core.rewind(a1.id)
    core.submit("Divergent branch question.")  # u4, a4
    cid = core.conversation_id

    reloaded = ConversationCore(repo, test_provider(["hi"]), workspace)
    reloaded.resume_conversation(cid)

    full = repo.load(cid)
    by_id = {n.id: n for n in full}
    for original in (u2, a2, u3, a3):
        assert original.id in by_id, f"abandoned node {original.id} was deleted"
        assert by_id[original.id].content == original.content
    # Abandoned tail chains back to the rewind point.
    assert by_id[u2.id].prev_id == a1.id
    # Active view excludes the abandoned tail.
    view_ids = {n.id for n in reloaded.current_view()}
    for abandoned in (u2.id, a2.id, u3.id, a3.id):
        assert abandoned not in view_ids


# C77
def test_c77_divergent_branch_same_core(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    u1, a1 = core.submit("Same-core question one.")
    u2, a2 = core.submit("Same-core question two.")
    u3, a3 = core.submit("Same-core question three.")
    core.rewind(a1.id)
    u4, a4 = core.submit("Same-core divergent question.")
    view = core.current_view()
    assert [n.id for n in view] == [u1.id, a1.id, u4.id, a4.id]
    view_ids = {n.id for n in view}
    for abandoned in (u2.id, a2.id, u3.id, a3.id):
        assert abandoned not in view_ids


# C78
def test_c78_migrated_linear_equivalence(tmp_path, test_provider, workspace):
    db_path = tmp_path / "pre_graph.db"
    cid = "migrated-conversation-001"
    rows = [
        ("node-1", "user", "Hello, can you help me plan a trip?"),
        ("node-2", "assistant", "Of course, where would you like to go?"),
        ("node-3", "user", "I'm thinking of visiting Japan in spring."),
        ("node-4", "assistant", "Spring is a great time for cherry blossoms."),
    ]
    _make_pre_graph_db(db_path, cid, rows)

    repo2 = ConversationRepository(str(db_path))
    core = ConversationCore(repo2, test_provider(["hi"]), workspace)
    core.setup()  # runs repo.init() -> migrates the flat DB into the graph schema
    core.resume_conversation(cid)

    assert [n.id for n in core.current_view()] == [n.id for n in repo2.load(cid)]


# C79
def test_c79_root_node_prev_id_is_none(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    u1, a1 = core.submit("First turn establishes the root.")
    # The root of the line has no predecessor (null/None marks the root).
    assert u1.prev_id is None
    # The invariant survives persistence: first loaded node (insertion order) is root.
    loaded = repo.load(core.conversation_id)
    assert loaded[0].prev_id is None


# C80
def test_c80_resume_dangling_active_leaf_falls_back_to_last(
    repo, test_provider, workspace, make_node
):
    cid = "conv-dangling"
    n1 = make_node(role="user", content="root turn", conversation_id=cid)
    n2 = make_node(role="assistant", content="second turn", conversation_id=cid)
    n2.prev_id = n1.id
    n3 = make_node(role="user", content="third turn", conversation_id=cid)
    n3.prev_id = n2.id
    # Store the linear chain with a BOGUS active tip pointer (stale/dangling edge).
    repo.save(cid, "Dangling tip", [n1, n2, n3], active_leaf_id="nonexistent-node-id")

    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.resume_conversation(cid)
    # Fall back to the last stored node (n3) as the tip: full stored line, not empty.
    assert [n.id for n in core.current_view()] == [n1.id, n2.id, n3.id]


# ---------------------------------------------------------------------------
# current_view() compression folding (ADR-0016 Q1) — C81..C90
# ---------------------------------------------------------------------------


def _view_core(repo, test_provider, workspace):
    """Build a ConversationCore with a no-op canned provider for view tests."""
    return ConversationCore(repo, test_provider([]), workspace)


def _chain(*nodes):
    """Link nodes into a prev_id chain (nodes[0] is root) and return them."""
    for prev, cur in zip(nodes, nodes[1:], strict=False):
        cur.prev_id = prev.id
    return nodes


# C81
def test_c81_no_compression_identical_to_walk(repo, test_provider, workspace, make_node):
    a = make_node(content="what is a monad")
    b = make_node(role="assistant", content="a monoid in the category of endofunctors")
    c = make_node(content="explain that for humans")
    _chain(a, b, c)

    core = _view_core(repo, test_provider, workspace)
    core._graph = {n.id: n for n in (a, b, c)}
    core._active_leaf_id = c.id

    view = core.current_view()
    assert [n.id for n in view] == [a.id, b.id, c.id]
    assert [n.node_type for n in view] == ["message", "message", "message"]


# C82
def test_c82_folded_tip_ends_with_k(repo, test_provider, workspace, make_node):
    a = make_node(content="first question")
    b = make_node(role="assistant", content="first answer")
    c = make_node(content="tail that gets folded")
    _chain(a, b, c)
    k = make_node(role="compression", content="summary of tail", node_type="compression")
    c.compressed_into = k.id

    core = _view_core(repo, test_provider, workspace)
    core._graph = {n.id: n for n in (a, b, c, k)}
    core._active_leaf_id = c.id

    view = core.current_view()
    assert [n.id for n in view] == [a.id, b.id, k.id]
    assert [n.node_type for n in view] == ["message", "message", "compression"]


# C83
def test_c83_append_after_folded_tip(repo, test_provider, workspace, make_node):
    a = make_node(content="opening line")
    b = make_node(role="assistant", content="reply")
    c = make_node(content="folded tip node")
    _chain(a, b, c)
    k = make_node(role="compression", content="folded summary", node_type="compression")
    c.compressed_into = k.id

    # New node is chained from the REAL leaf c (not K) and becomes the tip.
    new = make_node(content="brand new message after folding")
    new.prev_id = c.id

    core = _view_core(repo, test_provider, workspace)
    core._graph = {n.id: n for n in (a, b, c, k, new)}
    core._active_leaf_id = new.id

    view = core.current_view()
    assert [n.id for n in view] == [a.id, b.id, k.id, new.id]
    assert view[-1].id == new.id
    # K stays off the line.
    assert k.prev_id is None


# C84
def test_c84_middle_fold_in_place(repo, test_provider, workspace, make_node):
    a = make_node(content="anchor before run")
    b = make_node(role="assistant", content="folded 1")
    c = make_node(content="folded 2")
    d = make_node(role="assistant", content="folded 3")
    e = make_node(content="anchor after run")
    _chain(a, b, c, d, e)
    k = make_node(role="compression", content="middle summary", node_type="compression")
    for child in (b, c, d):
        child.compressed_into = k.id

    core = _view_core(repo, test_provider, workspace)
    core._graph = {n.id: n for n in (a, b, c, d, e, k)}
    core._active_leaf_id = e.id

    view = core.current_view()
    assert [n.id for n in view] == [a.id, k.id, e.id]
    assert [n.node_type for n in view] == ["message", "compression", "message"]


# C85
def test_c85_two_independent_compressions(repo, test_provider, workspace, make_node):
    a = make_node(content="head")
    b = make_node(role="assistant", content="run1 a")
    c = make_node(content="run1 b")
    d = make_node(role="assistant", content="unfolded middle")
    e = make_node(content="run2 folded")
    f = make_node(role="assistant", content="surviving tail")
    _chain(a, b, c, d, e, f)
    k1 = make_node(role="compression", content="summary one", node_type="compression")
    k2 = make_node(role="compression", content="summary two", node_type="compression")
    b.compressed_into = k1.id
    c.compressed_into = k1.id
    e.compressed_into = k2.id  # f left unfolded → surviving tail after K2

    core = _view_core(repo, test_provider, workspace)
    core._graph = {n.id: n for n in (a, b, c, d, e, f, k1, k2)}
    core._active_leaf_id = f.id

    view = core.current_view()
    assert [n.id for n in view] == [a.id, k1.id, d.id, k2.id, f.id]
    assert [n.node_type for n in view] == [
        "message", "compression", "message", "compression", "message",
    ]


# C86
def test_c86_single_node_fold(repo, test_provider, workspace, make_node):
    a = make_node(content="before")
    b = make_node(role="assistant", content="the only folded node")
    c = make_node(content="after")
    _chain(a, b, c)
    k = make_node(role="compression", content="single summary", node_type="compression")
    b.compressed_into = k.id

    core = _view_core(repo, test_provider, workspace)
    core._graph = {n.id: n for n in (a, b, c, k)}
    core._active_leaf_id = c.id

    view = core.current_view()
    assert [n.id for n in view] == [a.id, k.id, c.id]
    assert [n.node_type for n in view] == ["message", "compression", "message"]


# C87
def test_c87_dangling_compressed_into_treated_as_unfolded(
    repo, test_provider, workspace, make_node
):
    a = make_node(content="alpha")
    b = make_node(role="assistant", content="points at a missing K")
    c = make_node(content="gamma")
    _chain(a, b, c)
    b.compressed_into = "missing-compression-id-not-in-graph"

    core = _view_core(repo, test_provider, workspace)
    core._graph = {n.id: n for n in (a, b, c)}  # no K stored
    core._active_leaf_id = c.id

    view = core.current_view()
    assert [n.id for n in view] == [a.id, b.id, c.id]
    assert [n.node_type for n in view] == ["message", "message", "message"]


# C88
def test_c88_empty_conversation(repo, test_provider, workspace):
    core = _view_core(repo, test_provider, workspace)
    core._graph = {}
    core._active_leaf_id = None

    assert core.current_view() == []


# C89
def test_c89_save_reload_roundtrip_fold(repo, test_provider, workspace, make_node):
    cid = "conv-fold-roundtrip"
    a = make_node(content="persisted head", conversation_id=cid)
    b = make_node(role="assistant", content="persisted folded 1", conversation_id=cid)
    c = make_node(content="persisted folded 2", conversation_id=cid)
    d = make_node(role="assistant", content="persisted folded 3", conversation_id=cid)
    e = make_node(content="persisted tail", conversation_id=cid)
    _chain(a, b, c, d, e)
    k = make_node(
        role="compression",
        content="persisted summary",
        node_type="compression",
        conversation_id=cid,
    )
    for child in (b, c, d):
        child.compressed_into = k.id

    repo.save(cid, "roundtrip", [a, b, c, d, e, k], active_leaf_id=e.id)

    core = _view_core(repo, test_provider, workspace)
    core.resume_conversation(cid)

    view = core.current_view()
    assert [n.id for n in view] == [a.id, k.id, e.id]
    assert [n.node_type for n in view] == ["message", "compression", "message"]


# C90
def test_c90_root_fold_view_starts_with_k(repo, test_provider, workspace, make_node):
    a = make_node(content="folded root 1")
    b = make_node(role="assistant", content="folded root 2")
    c = make_node(content="surviving tail")
    _chain(a, b, c)
    k = make_node(role="compression", content="head summary", node_type="compression")
    a.compressed_into = k.id
    b.compressed_into = k.id

    core = _view_core(repo, test_provider, workspace)
    core._graph = {n.id: n for n in (a, b, c, k)}
    core._active_leaf_id = c.id

    view = core.current_view()
    assert [n.id for n in view] == [k.id, c.id]
    assert [n.node_type for n in view] == ["compression", "message"]
    assert view[0].prev_id is None


# ---------------------------------------------------------------------------
# Task 13g: resume must not clobber the title; rewind must reject off-line
# nodes (ADR-0016 Q1). Documented additions per the task-10 precedent — the
# scenarios come from the PRD task, not the implementation.
# ---------------------------------------------------------------------------


# C91 — compress the whole tip → save → resume → the stored title survives a
# further persist (the folded view has no user turn, so the old derive-from-view
# path blanked it and the next persist() overwrote the stored title for good).
def test_c91_resume_whole_tip_folded_keeps_stored_title(
    repo, test_provider, workspace
):
    original = "The original opening question"
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.submit(original)
    core.submit("A follow-up question")
    cid = core.conversation_id
    view = core.current_view()
    core.commit_compression(view[0].id, view[-1].id, "summary of everything")
    assert core.conversation_title == original  # commit leaves the title alone

    fresh = ConversationCore(repo, test_provider(["hi"]), workspace)
    fresh.resume_conversation(cid)
    assert fresh.conversation_title == original
    fresh.persist()  # the write that used to clobber the stored title with ""

    fresh2 = ConversationCore(repo, test_provider(["hi"]), workspace)
    fresh2.resume_conversation(cid)
    assert fresh2.conversation_title == original


# C92 — when the stored title IS empty, resume derives from the raw line, not
# the folded (user-less) view. Whole conversation folded, stored title blanked.
def test_c92_resume_empty_stored_title_derives_from_raw_line(
    repo, test_provider, workspace
):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.submit("Raw line first user turn")
    core.submit("Second turn")
    cid = core.conversation_id
    view = core.current_view()
    core.commit_compression(view[0].id, view[-1].id, "summary")
    core.conversation_title = ""  # force resume down the derivation branch
    core.persist()

    fresh = ConversationCore(repo, test_provider(["hi"]), workspace)
    fresh.resume_conversation(cid)
    assert fresh.conversation_title == "Raw line first user turn"


# C93 — partly folded, empty stored title: derivation picks the FIRST user turn
# on the raw line (even though it is folded), never a later turn that happens to
# be the folded view's first user node. Graph built directly to place a prefix
# fold the 3a tip guard would otherwise forbid (S4/task 22 territory).
def test_c93_resume_partly_folded_derives_first_raw_user(
    repo, test_provider, workspace, make_node
):
    cid = "conv-c93"
    u1 = make_node(role="user", content="Alpha original title", conversation_id=cid)
    a1 = make_node(role="assistant", content="answer one", conversation_id=cid)
    u2 = make_node(role="user", content="Beta a later turn", conversation_id=cid)
    a2 = make_node(role="assistant", content="answer two", conversation_id=cid)
    _chain(u1, a1, u2, a2)
    k = make_node(
        role="compression",
        content="summary of the head",
        node_type="compression",
        conversation_id=cid,
        meta={"prompt": "", "range": [u1.id, a1.id]},
    )
    u1.compressed_into = k.id
    a1.compressed_into = k.id
    repo.save(cid, "", [u1, a1, u2, a2, k], active_leaf_id=a2.id)

    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.resume_conversation(cid)
    # The folded view's first user node is u2 ("Beta…"); the raw line's is u1.
    assert core.conversation_title == "Alpha original title"


# C94 — rewind(K.id) raises and leaves the graph unmutated. K is in the view but
# off the prev_id line; rewinding to it would collapse the view to [K] and land K
# on the line on the next submit (Q1).
def test_c94_rewind_to_compression_node_raises(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.submit("First question")
    core.submit("Second question")
    view = core.current_view()
    k = core.commit_compression(view[0].id, view[-1].id, "summary")
    leaf_before = core._active_leaf_id
    view_before = [n.id for n in core.current_view()]
    ids_before = set(core._graph)
    with pytest.raises(ValueError):
        core.rewind(k.id)
    assert core._active_leaf_id == leaf_before
    assert [n.id for n in core.current_view()] == view_before
    assert set(core._graph) == ids_before


# C95 — rewind to a folded child raises (folded children are on the raw line but
# rejected for now; guards the compressed_into clause).
def test_c95_rewind_to_folded_child_raises(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    u1, a1 = core.submit("First question")
    core.submit("Second question")
    view = core.current_view()
    core.commit_compression(view[0].id, view[-1].id, "summary")
    leaf_before = core._active_leaf_id
    with pytest.raises(ValueError):
        core.rewind(u1.id)  # u1 is folded (compressed_into set)
    assert core._active_leaf_id == leaf_before


# C96 — rewind(E.id) raises: an expand event node is off the line (prev_id=None)
# and never a rewind target.
def test_c96_rewind_to_expand_event_raises(repo, test_provider, workspace):
    core = ConversationCore(repo, test_provider(["hi"]), workspace)
    core.setup()
    core.submit("First question")
    core.submit("Second question")
    view = core.current_view()
    k = core.commit_compression(view[0].id, view[-1].id, "summary")
    core.expand_compression(k.id)
    e_id = next(
        n.id for n in core._graph.values() if n.node_type == "expand"
    )
    leaf_before = core._active_leaf_id
    view_before = [n.id for n in core.current_view()]
    with pytest.raises(ValueError):
        core.rewind(e_id)
    assert core._active_leaf_id == leaf_before
    assert [n.id for n in core.current_view()] == view_before
