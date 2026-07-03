"""Behavioral tests for ``hash_context`` — see tests/specs/reconstruction-hash.md.

Code-blind: assertions trace to contract Expect clauses, not to any assumed
implementation output. Relational (equal / not-equal) oracles are preferred over
hardcoded magic digests; only the output shape (length 64, lowercase hex) is
asserted as a literal, per the interface's stated sha256-hex guarantee.
"""

import string

from ctx.core.reconstruction import hash_context

_HEXDIGITS = set(string.hexdigits.lower())


def _is_hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in _HEXDIGITS for c in value)
    )


# C1 — determinism / purity
def test_same_input_hashes_identically():
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"},
        {"role": "assistant", "content": "The capital of France is Paris."},
    ]
    assert hash_context(messages) == hash_context(messages)


# C2 — key-order independence
def test_key_insertion_order_does_not_change_hash():
    ordered = [{"role": "user", "content": "Summarize the meeting notes."}]
    reordered = [{"content": "Summarize the meeting notes.", "role": "user"}]
    assert hash_context(ordered) == hash_context(reordered)


# C3 — content sensitivity
def test_changing_content_changes_hash():
    base = [{"role": "user", "content": "Deploy the service to staging."}]
    changed = [{"role": "user", "content": "Deploy the service to production."}]
    assert hash_context(base) != hash_context(changed)


# C4 — role sensitivity
def test_changing_role_changes_hash():
    as_user = [{"role": "user", "content": "The build succeeded."}]
    as_assistant = [{"role": "assistant", "content": "The build succeeded."}]
    assert hash_context(as_user) != hash_context(as_assistant)


# C5 — order sensitivity
def test_reordering_messages_changes_hash():
    first = [
        {"role": "user", "content": "List the open pull requests."},
        {"role": "assistant", "content": "There are three open pull requests."},
    ]
    swapped = [first[1], first[0]]
    assert hash_context(first) != hash_context(swapped)


# C6 — count sensitivity (append)
def test_adding_message_changes_hash():
    shorter = [
        {"role": "system", "content": "Answer concisely."},
        {"role": "user", "content": "Ping?"},
    ]
    longer = shorter + [{"role": "assistant", "content": "Pong."}]
    assert hash_context(shorter) != hash_context(longer)


# C7 — output shape (populated list)
def test_output_is_64_char_lowercase_hex():
    messages = [
        {"role": "user", "content": "Explain recursion in one sentence."},
    ]
    assert _is_hex64(hash_context(messages))


# C7 — output shape (empty list is stable and valid, no error)
def test_empty_list_returns_stable_hex_digest():
    first = hash_context([])
    second = hash_context([])
    assert _is_hex64(first)
    assert first == second


# C8 — unicode handled, deterministic, and content-sensitive
def test_unicode_content_is_deterministic_and_distinguishable():
    cafe = [{"role": "user", "content": "café"}]
    japanese = [{"role": "user", "content": "日本語"}]
    # deterministic across calls on the same unicode input
    assert hash_context(cafe) == hash_context(cafe)
    assert _is_hex64(hash_context(cafe))
    # distinct unicode contents must hash differently
    assert hash_context(cafe) != hash_context(japanese)
