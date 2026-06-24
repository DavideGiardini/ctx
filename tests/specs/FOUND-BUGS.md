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

_(none — all confirmed bugs below have been fixed and their xfail markers removed)_

<!--
Example row:
| ctx/core/storage.py | C7 | test_c7_load_unknown_id_returns_empty | load() of an unknown id returns [] | raises sqlite3.OperationalError |
-->

## Fixed
_(rows move here when the code is fixed and the xfail marker removed)_

Fixed on branch `develop` (test suite green, all 8 quarantine markers removed):

| Module | Contract | (formerly xfail) test | Fix |
|--------|----------|------------|-----|
| ctx/core/storage.py | C18 | test_c18_zero_persisted_empty_list_not_listed | `save()` no longer inserts a row for a brand-new conversation with no persistable nodes (only `INSERT` when `persistable`); an existing conversation still updates/clears (C7) |
| ctx/core/storage.py | C18 | test_c18_zero_persisted_all_filtered_not_listed | same fix — `persistable = [n for n in nodes if n.conversation_id]` gates the `INSERT` |
| ctx/core/storage.py | C24 | test_c24_same_instant_saves_ordered_most_recent_first | `list()`/`get_last()` order by `updated_at DESC, rowid DESC` — rowid is the monotonic tiebreak |
| ctx/core/config.py | C17 | test_c17_nested_mutation_does_not_persist | `get_config()` returns `copy.deepcopy(_DEFAULTS)` on every path → deep isolation |
| ctx/core/config.py | C18 | test_c18_wrong_typed_sections_do_not_raise | each section re-merged only when `isinstance(value, dict)`; wrong-typed section falls back to a deepcopy of its default |
| ctx/core/config.py | C19 | test_c19_non_object_root_does_not_raise | non-dict root short-circuits to the deepcopied defaults before `update()` |
| ctx/core/workspace.py | C24 | test_c24_read_file_sibling_prefix_dir_raises_valueerror | guard is now `target.is_relative_to(self._context.resolve())` (resolved-path containment) instead of string `startswith` |
| ctx/core/conversation.py | C27 | test_resume_unknown_id_leaves_current_state_unchanged | `resume_conversation` loads into a local and only assigns `self.nodes`/id/title once the load is non-empty |

---

### Notes per module
- **`ctx/core/context.py`** — no contract violations found (19/19 green; see `context.md`).
- **`ctx/core/storage.py`** — two violations (C18, C24); **both fixed**.
  C18: a conversation with zero persisted nodes used to leak into `list()`/`get_last()`;
  `save()` now only inserts a row for a brand-new conversation when at least one node
  persists (an existing conversation still updates/clears — see C7). C24: recency ordering
  now has a monotonic tiebreak — `ORDER BY updated_at DESC, rowid DESC`. See `storage.md`.
- **`ctx/core/config.py`** — three violations (C17, C18, C19); **all fixed**.
  C17: `get_config()` now returns `copy.deepcopy(_DEFAULTS)` on every path, so a caller
  mutating a nested value can't poison the module-level defaults. C18: each known section is
  re-merged only when the user value `isinstance(value, dict)`, otherwise it falls back to a
  deepcopy of that section's default, so a misshapen-but-parseable section no longer crashes.
  C19: a valid-JSON but non-object root (`5`, `[1,2]`) short-circuits to the deepcopied
  defaults before `update()`. See `config.md`.
- **`ctx/core/workspace.py`** — one violation (C24); **fixed**.
  The `read_file` sandbox guard is now a resolved-path containment check
  (`target.is_relative_to(self._context.resolve())`) instead of a string-prefix test, so a
  sibling directory whose name *starts with* the context dir's name (e.g. `.ctx/context-extra/`
  next to `.ctx/context/`) is correctly rejected. The other security items still pass — C23
  (absolute path) and C25 (escaping symlink) raise because `.resolve()` precedes the check,
  and C27 (`read_file("")` → the context dir itself) still raises an OSError-family error.
  See `workspace.md`.
- **`ctx/core/conversation.py`** — one violation (C27); **fixed**.
  `resume_conversation(id)` now loads into a local and only assigns `self.nodes`/`id`/`title`
  once the load is non-empty, so resuming an UNKNOWN id leaves the in-progress conversation
  untouched and returns `[]` (adjudicated intent: preserve current state). See
  `conversation.md`.
