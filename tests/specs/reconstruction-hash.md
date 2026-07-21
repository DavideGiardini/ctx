# Behavioral contract — `hash_context`

Module: `ctx/core/context.py`
Symbol under test: `hash_context(messages: list[dict[str, Any]]) -> str`

Scope: this document pins down only `hash_context`, the canonical tripwire
hasher for a rendered `build_context` message list.

Domain: `messages` is a litellm-style list of dicts, each typically
`{"role": "user"|"assistant"|"system", "content": "<text>"}`. The digest is the
per-turn verification anchor: it is computed at generation time and later
recompared against an independently reconstructed context. The oracle is the
mathematical relationship between hashes of related inputs, NOT any specific
magic digest value.

---

C1. Determinism / purity
  Given:    the same message list passed to `hash_context` twice.
  Expect:   both calls return the exact same string.
  Rationale:Intent (property 1) requires a pure function so a generation-time
            hash can be recomputed identically later; without this the tripwire
            would produce false drift alarms.

C2. Key-order independence
  Given:    two dicts with identical key/value pairs but different key insertion
            order, e.g. `{"role": "user", "content": "hi"}` vs
            `{"content": "hi", "role": "user"}`.
  Expect:   the two lists hash to the SAME string.
  Rationale:`sort_keys=True` (intent property 2) means the digest depends on
            content, not on Python dict insertion order, which is an
            implementation artifact and not a semantic difference.

C3. Content sensitivity
  Given:    two lists identical except one message's `content` string differs.
  Expect:   the two lists hash to DIFFERENT strings.
  Rationale:Intent property 3: any semantic change to message content must be
            detectable by the tripwire.

C4. Role sensitivity
  Given:    two lists identical except one message's `role` value differs
            (e.g. "user" vs "assistant").
  Expect:   the two lists hash to DIFFERENT strings.
  Rationale:Intent property 4: a role change is a semantic difference the
            reconstruction oracle must catch.

C5. Order sensitivity
  Given:    the same set of two distinct messages, in swapped order.
  Expect:   the two lists hash to DIFFERENT strings.
  Rationale:Intent property 5: message ordering is semantically meaningful in a
            conversation context, so reordering must change the digest.

C6. Count sensitivity
  Given:    a list, and the same list with one additional message appended
            (or one removed).
  Expect:   the two lists hash to DIFFERENT strings.
  Rationale:Intent property 6: adding/removing turns changes the context and
            must change the digest.

C7. Output shape
  Given:    any valid message list (including the empty list `[]`).
  Expect:   the return value is a `str` of exactly 64 characters, all of which
            are lowercase hexadecimal (0-9, a-f); the empty list produces such a
            digest without raising.
  Rationale:Intent property 7: the result is a hex sha256 digest (64 lowercase
            hex chars), and an empty context is a valid stable input.

C8. Unicode handling
  Given:    messages whose content contains non-ASCII text (e.g. "café",
            "日本語").
  Expect:   `hash_context` returns without error, is deterministic across two
            calls on the same unicode input, AND two different unicode contents
            hash to different strings.
  Rationale:Intent property 8 (`ensure_ascii=False`): unicode must be handled
            losslessly and deterministically. Tests assert relational
            properties, never a hardcoded magic digest.

---

## Intent ambiguities assumed past (flag for human)

- **Non-string / extra keys**: the interface types values as `Any` and dicts may
  carry keys beyond `role`/`content`. The intent only exercises the typical
  role/content shape, so this contract does not pin behavior for non-JSON-
  serializable values (e.g. sets, bytes) — `json.dumps` would raise, but that is
  not asserted here.
- **`None` input**: passing `None` instead of a list is out of the stated
  interface (type is `list[dict]`); not contracted.
