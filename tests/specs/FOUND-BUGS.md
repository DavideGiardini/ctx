# Contract violations found by the test suite

Bugs surfaced by the contract-first tests — cases where a test (whose oracle was derived
from *intent* and human-adjudicated) fails because the **implementation** disagrees with
the contract. These are findings, **not** fixed here: the `/write-tests` sessions never
modify production code. Each is quarantined with `@pytest.mark.xfail(strict=True)` so the
suite stays green (and mutmut can run), while the failing test remains as an executable
specification of the correct behavior. Fixing them is a separate, human-reviewed effort.

Because the xfail is `strict`, fixing the code makes the test XPASS (a failure), which
forces removal of the marker — so an entry here can't be silently resolved and forgotten.

## How to add an entry
When a session confirms a real bug, append a row and mark the test `xfail(strict=True)`
with `reason="BUG: <summary> — contract <Cn>; see tests/specs/FOUND-BUGS.md"`.

## Open

| Module | Contract | xfail test | Expected (per contract) | Actual (current code) |
|--------|----------|------------|-------------------------|-----------------------|
| ctx/core/storage.py | C18 | test_c18_zero_persisted_empty_list_not_listed | A save with `nodes==[]` (no persisted nodes) leaves no conversation in `list()`/`get_last()` | `save()` always inserts the conversation row, so it appears in `list()`/`get_last()` |
| ctx/core/storage.py | C18 | test_c18_zero_persisted_all_filtered_not_listed | A save whose nodes all have `conversation_id==""` (all filtered) leaves no conversation in `list()`/`get_last()` | same: the conversation row is inserted regardless of whether any node persists |
| ctx/core/storage.py | C24 | test_c24_same_instant_saves_ordered_most_recent_first | Two saves at the same instant still order most-recently-saved first in `list()`/`get_last()` | ordered by `updated_at` alone (no tiebreak) → same-instant order is undefined |
| ctx/core/config.py | C17 | test_c17_nested_mutation_does_not_persist | Mutating a nested value in the returned config must not affect the next `get_config()` call (deep isolation) | `get_config()` returns a shallow copy of the defaults, so a nested mutation corrupts the process-global defaults seen by the next call |
| ctx/core/config.py | C18 | test_c18_wrong_typed_sections_do_not_raise | A wrong-type but valid-JSON section (e.g. `{"colors": "blue"}`) falls back to defaults without raising | `get_config()` raises an uncaught `TypeError` at `config.py:37` — the merge spreads the value as a mapping and the `except` only catches `JSONDecodeError`/`OSError` |
| ctx/core/config.py | C19 | test_c19_non_object_root_does_not_raise | A valid-JSON but non-object root (e.g. `5` or `[1,2]`) falls back to defaults without raising | `get_config()` raises an uncaught `TypeError: 'int' object is not iterable` at `config.py:35` (`merged.update(user_config)`) — the root-level sibling of C18; the `except` only catches `JSONDecodeError`/`OSError` |
| ctx/core/workspace.py | C24 | test_c24_read_file_sibling_prefix_dir_raises_valueerror | `read_file("../context-extra/secret.txt")` — a sibling dir merely sharing a name *prefix* with `context` is out of bounds → `ValueError` | The guard is `str(target).startswith(str(context_dir.resolve()))` (no separator); `.../.ctx/context-extra/secret.txt` matches the prefix `.../.ctx/context`, so the guard passes and the **out-of-sandbox file is read** (returns its contents, no raise) — a sandbox escape |
| ctx/core/conversation.py | C27 | test_resume_unknown_id_leaves_current_state_unchanged | Resuming an unknown id leaves the in-progress conversation intact (`nodes`/`conversation_id`/`conversation_title` unchanged); only `[]` is returned | `resume_conversation` does `self.nodes = storage.load(id)` (== `[]` for an unknown id) *before* the early `return []`, wiping the current `nodes` to `[]` while `conversation_id`/`conversation_title` keep their old values — a half-destroyed in-memory state |

<!--
Example row:
| ctx/core/storage.py | C7 | test_c7_load_unknown_id_returns_empty | load() of an unknown id returns [] | raises sqlite3.OperationalError |
-->

## Fixed
_(move rows here when the code is fixed and the xfail marker removed — note the commit/PR)_

---

### Notes per module
- **`ctx/core/context.py`** — no contract violations found (19/19 green; see `context.md`).
- **`ctx/core/storage.py`** — two violations (C18, C24); both quarantined `xfail(strict=True)`.
  C18: a conversation with zero persisted nodes is a first-class entity it shouldn't be —
  it leaks into `list()`/`get_last()`. C24: recency ordering lacks a tiebreak, so
  same-instant saves are unordered. Fix hint for C24: add a monotonic secondary sort
  (sequence column or `rowid`). See `storage.md`.
- **`ctx/core/config.py`** — two violations (C17, C18); both quarantined `xfail(strict=True)`.
  C17: `get_config()` shallow-copies the defaults, so a caller mutating a nested value
  (`result["colors"]["user"] = ...`) poisons the module-level defaults for the rest of the
  process. Fix hint: return a `copy.deepcopy` (and the no-file path must deep-copy too).
  C18: a misshapen-but-parseable config crashes instead of falling back — the per-section
  merge assumes each section is a mapping, but the `except` only catches
  `JSONDecodeError`/`OSError`. Fix hint: guard each section's type before spreading, or
  widen the fallback. See `config.md`.
  C19: the root-level sibling of C18 — a valid-JSON but non-object root (`5`, `[1,2]`)
  crashes at `merged.update(user_config)` (`config.py:35`) because `update` requires a
  mapping. Same `except` gap. Fix hint: guard the root's type before merging (or widen the
  fallback). See `config.md`.
- **`ctx/core/workspace.py`** — one violation (C24); quarantined `xfail(strict=True)`.
  The `read_file` sandbox guard is a string-prefix test
  (`str(target).startswith(str(context_dir.resolve()))`) with no path-separator boundary,
  so a sibling directory whose name *starts with* the context dir's name (e.g.
  `.ctx/context-extra/` next to `.ctx/context/`) passes the check and its files are read —
  a path-traversal/sandbox escape. The blind contract pinned this as C24 (security-critical).
  Fix hint: compare resolved paths with `Path.is_relative_to(context_dir.resolve())` (or
  `os.path.commonpath`), not string `startswith`. Note: the other security items pass —
  C25 (symlink whose resolved target escapes) is correctly rejected because `.resolve()`
  follows the link before the check. See `workspace.md`.
- **`ctx/core/conversation.py`** — one violation (C27); quarantined `xfail(strict=True)`.
  `resume_conversation(id)` assigns `self.nodes = storage.load(id)` *before* the
  `if not self.nodes: return []` guard, so resuming an UNKNOWN id (load returns `[]`) wipes
  the current in-memory `nodes` to `[]` while leaving `conversation_id`/`conversation_title`
  set — a half-destroyed state that can silently discard an in-progress conversation.
  Adjudicated intent (the user chose "preserve current state"): an unknown-id resume must
  leave `nodes`/`id`/`title`/`model` untouched and only return `[]`. Fix hint: load into a
  local, and only assign `self.nodes`/adopt the id once the load is non-empty. See
  `conversation.md`.
