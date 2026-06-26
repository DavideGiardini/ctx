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

import pytest

from ctx.core.config import DEFAULT_MODEL
from ctx.core.conversation import MAX_TITLE_LENGTH, ConversationCore


class CapturingProvider:
    def __init__(self, tokens):
        self._tokens = tokens
        self.captured_messages = None

    async def stream(self, messages, model):
        self.captured_messages = messages
        for t in self._tokens:
            yield t

    async def check_connectivity(self, model):
        return (True, "ok")


class FailingProvider:
    def __init__(self, tokens):
        self._tokens = tokens

    async def stream(self, messages, model):
        for t in self._tokens:
            yield t
        raise RuntimeError("boom")

    async def check_connectivity(self, model):
        return (True, "ok")


class FailingConnectivityProvider:
    def __init__(self, tokens, error):
        self._tokens = tokens
        self._error = error

    async def stream(self, messages, model):
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

    def save(self, cid, title, nodes, *, model=""):
        self.save_count += 1
        return self._inner.save(cid, title, nodes, model=model)

    def load(self, cid):
        return self._inner.load(cid)

    def get_model(self, cid):
        return self._inner.get_model(cid)

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

    async def stream(self, messages, model):
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

    async def stream(self, messages, model):
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
