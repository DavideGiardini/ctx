# Behavioral contract — `ctx/core/config.py` :: `get_config`

The oracle of record for `get_config() -> dict`. Authored code-blind from intent
(see `.claude/skills/write-tests`), then human-adjudicated. Tests in
`tests/test_config.py` cite these item ids. **When behavior changes, update this
contract first**, then the tests.

`get_config()` returns the EFFECTIVE configuration: built-in defaults overlaid with
the user's overrides read from the module-level `CONFIG_PATH`
(`~/.config/ctx/config.json`). It is a convenience layer — a missing, empty,
invalid, or unreadable config file must fall back to defaults WITHOUT raising.
Overrides merge per-section, never wholesale: a user who sets one color keeps every
other default color.

`get_config()` is not injectable; it reads the module-level `CONFIG_PATH` directly.
Tests isolate it by monkeypatching `ctx.core.config.CONFIG_PATH` (and `CONFIG_DIR`)
to a `tmp_path` location, then making the file absent / writing JSON / writing raw
bytes before calling. (An injectable-path refactor consistent with ADR-0004/0005 was
considered and deferred — out of scope for this session.)

Throughout, **`D`** denotes the baseline defaults obtained by calling `get_config()`
once with **no config file present**. All merge expectations are phrased relative to
`D`, so no exact hex codes or line counts are pinned — only the documented set of
section/key names. Tests must capture a **deep snapshot** of `D` before any
mutation-isolation test runs (C17/C18 mutate returned dicts).

## Contract

**C1. Returns a dict.** Any valid setup (file absent, or present with valid JSON) →
`get_config()` returns a `dict`.

**C2. Defaults on absence.** The config file does not exist → the result deep-equals
the baseline defaults `D`; does not raise.

**C3. Defaults expose the documented structure.** Baseline `D` contains a `"colors"`
dict whose keys are exactly `{user, assistant, system, context}` (values are
strings); and a `"ui"` dict containing a `"truncation_lines"` dict whose keys are
exactly `{human, assistant, context, system}` (values are ints). *(adjudicated A3:
the defaults' top level is exactly `{colors, ui}` — no other top-level keys.)*

**C4. Never crashes on a missing file.** File absent → returns a dict, raises nothing.

**C5. Never crashes on invalid JSON.** File contains bytes that are not valid JSON
(e.g. `not: valid: json {{{`) → does not raise; returns `D` (deep-equal). Broken
input is treated as "no overrides".

**C6. Never crashes on an empty file.** File exists but is zero bytes → does not
raise; returns `D` (deep-equal). *(adjudicated A4: empty is treated as "no
overrides", observably identical to invalid JSON — both yield `D`.)*

**C7. Never crashes on an unreadable file.** The config path cannot be read as a file
→ does not raise; returns `D` (deep-equal). *(adjudicated A7: simulated portably by
pointing `CONFIG_PATH` at a directory, which makes `open()` fail with an `OSError`
subclass; chmod-based denial is unreliable under some CI/root environments.)*

**C8. Empty JSON object yields defaults.** File contains `{}` → result deep-equals
`D`; does not raise. No overrides specified means nothing changes.

**C9. A single color override preserves the other colors.** File =
`{"colors": {"user": "#123456"}}` (distinct from `D["colors"]["user"]`) →
`result["colors"]["user"] == "#123456"`, and for every other key `k` in
`D["colors"]`, `result["colors"][k] == D["colors"][k]`.

**C10. Multiple color overrides preserve the unspecified ones.** File overrides two
roles (e.g. `user` and `assistant`, both distinct from defaults) → both overridden
roles equal the new values; every remaining role in `D["colors"]` equals its default.

**C11. A single truncation_lines override preserves the others.** File =
`{"ui": {"truncation_lines": {"human": 7}}}` (distinct from default) →
`result["ui"]["truncation_lines"]["human"] == 7`, and for every other key `k` in
`D["ui"]["truncation_lines"]`, the value equals `D["ui"]["truncation_lines"][k]`.

**C12. A partial `ui` override preserves the rest of `ui`, including full
truncation_lines defaults.** File sets `ui` content that does NOT mention
`truncation_lines` (e.g. `{"ui": {"some_other_flag": true}}`) →
`result["ui"]["truncation_lines"]` deep-equals `D["ui"]["truncation_lines"]`
(untouched), `result["ui"]["some_other_flag"] == true`, and any other keys in
`D["ui"]` are preserved. *(adjudicated A2: `ui` merges over default `ui` — unknown
sub-keys are ADDED, existing defaults preserved; it is not a wholesale replacement.)*

**C13. Section overrides don't leak across sections.** Overriding only `colors.user`
leaves `result["ui"]` deep-equal to `D["ui"]`; and overriding only a
`ui.truncation_lines` key leaves `result["colors"]` deep-equal to `D["colors"]`.

**C14. An unknown top-level key is added; sections are untouched.** File =
`{"editor": "vim"}` → `result["editor"] == "vim"`, and both `result["colors"]` and
`result["ui"]` still deep-equal their defaults. *(adjudicated A3: there are no
scalar known top-level keys to override, so "add new top-level key" is the only
top-level case; the draft's separate C15 collapsed into this item.)*

**C15. Stable / idempotent across calls.** With the file absent (or fixed), calling
`get_config()` twice returns dicts that deep-equal each other and `D`.

**C16. Top-level mutation isolation.** Call once → `r1`; replace a key at `r1`'s top
level (`r1["colors"] = {}`, `r1["new_key"] = "x"`); call again → `r2`. Then `r2`
deep-equals the original `D` — `r2["colors"]` is intact and `"new_key"` is absent.
A caller's top-level mutation must not corrupt the next call.

**C17. Deep mutation isolation.** *(BUG RECORD — currently violated; see below.)*
Call once → `r1`; mutate a NESTED dict in place (`r1["colors"]["user"] = "#deadbe"`);
call again → `r2`. Then `r2["colors"]["user"]` equals the original `D` value,
unaffected by the nested mutation of `r1`. *(adjudicated: deep isolation IS part of
the contract — callers must not be able to corrupt the next call's defaults at any
depth.)*

**C18. Never crashes on a misshapen section.** *(BUG RECORD — currently violated; see
below.)* File supplies a section of the wrong type — valid JSON but wrong shape, e.g.
`{"colors": "not-a-dict"}` or `{"ui": 42}` → `get_config()` does not raise and
returns a `dict`. A hand-edited config with a type slip is still "a broken user
config", which intent says must never take down the app. *(adjudicated A5: the firm
oracle is no-raise + returns-a-dict; the exact recovered structure is not pinned.)*

**C19. Never crashes on a non-object JSON root. — CONTRACT VIOLATION (BUG record); test
quarantined `xfail(strict=True)`.** File contains valid JSON whose top-level value is not an
object — e.g. `5`, `"hi"`, or `[1, 2]` → `get_config()` does not raise and returns a `dict`
(falls back to `D`). A hand-edited config with a top-level type slip is still "a broken user
config", which (like C18) intent says must never take down the app. *(adjudicated A9: same
firm oracle as C18 — no-raise + returns-a-dict; the exact recovered structure is not pinned.
This is the root-level sibling of C18's section-level wrong-type case.)*

**C20. A truncation_lines value of `"auto"` is accepted and passed through.**
*(The defaults' docstring documents `"auto"` as a legal value that disables truncation for a
role; a user override of `{"ui": {"truncation_lines": {"assistant": "auto"}}}` is valid
config, not a type error.)* File = `{"ui": {"truncation_lines": {"assistant": "auto"}}}` →
does not raise; `result["ui"]["truncation_lines"]["assistant"] == "auto"`, and every other
truncation key keeps its default value `D["ui"]["truncation_lines"][k]` (per C11's merge).

## Contract violations found

Where the code violates this (correct, intended) contract, the test is kept as the
executable spec of correct behavior and **quarantined** with
`@pytest.mark.xfail(reason="BUG: … — contract <Cn>; see tests/specs/FOUND-BUGS.md",
strict=True)`. The suite stays green (so mutmut can run); `strict=True` means the day
the code is fixed the test XPASSes and forces removal of the marker. Production code is
**not** modified by the test-writing session — fixes are a separate, human-reviewed
effort. Both findings are logged in `tests/specs/FOUND-BUGS.md`. Two items are
quarantined:

- **C17 (deep mutation isolation).** The no-file path returns a shallow copy of the
  defaults, so the nested `colors`/`ui` dicts are shared. Mutating
  `r1["colors"]["user"]` corrupts the process-global defaults for the next call. Fix:
  return a deep copy.
- **C18 (misshapen section never crashes).** A wrong-type section (e.g.
  `{"colors": "blue"}`) raises an uncaught `TypeError` at `config.py:37` — the merge
  spreads the value as a mapping, and the `except` clause only catches
  `(JSONDecodeError, OSError)`. Fix: guard the merge / widen the fallback so
  misshapen-but-parseable config returns defaults.
- **C19 (non-object JSON root never crashes).** A valid-JSON but non-object root (e.g.
  `5` or `[1, 2]`) raises an uncaught `TypeError` at `config.py:35` — `merged.update(value)`
  requires a mapping, and the `except` clause only catches `(JSONDecodeError, OSError)`.
  This is the root-level sibling of C18. Fix: guard the root's type before merging / widen
  the fallback so a non-object root returns defaults.

All other items (C1–C16, C20) pass against the current implementation.

## Adjudication notes / ambiguities
- **A1 (deep isolation):** resolved as IN contract (C17). Currently a bug.
- **A2 (unknown `ui` sub-keys):** resolved — `ui` merges, unknown sub-keys added,
  defaults preserved (C12).
- **A3 (top-level keys):** resolved — defaults are exactly `{colors, ui}`; no scalar
  known top-level keys, so the draft's C15 folded into C14.
- **A4 (empty file):** resolved — treated as no-overrides, yields `D` (C6).
- **A5 (wrong-type section):** resolved as IN contract — must not crash (C18).
  Currently a bug. Recovered structure intentionally not pinned.
- **A6 (partial-validity files):** left unspecified — no item asserts mixed
  valid/invalid sections within one file. Revisit only if a real need appears.
- **A7 (unreadable simulation):** resolved — point `CONFIG_PATH` at a directory.
- **A9 (non-object JSON root):** resolved as IN contract — must not crash (C19), same firm
  oracle as C18. Currently a bug. Recovered structure intentionally not pinned.
- **A8 (baseline snapshot):** test-authoring note — deep-snapshot `D` before the
  mutation-isolation tests run.

## Mutation testing (mutmut)
**43 mutants, 43 killed, 0 survivors** (focused run:
`scripts/mutate.sh run 'ctx.core.config.*'`). No equivalent-mutant exceptions to
document. The two quarantined bugs (C17/C18) are `xfail(strict=True)`, which keeps the
baseline green so mutmut can run.

**Test-isolation note:** `get_config()` shares the module-level defaults dict
(`ctx.core.config._DEFAULTS`) by reference, so a test that mutates a returned config
leaks into that global. Under mutmut (which runs the suite multiple times in one
process) this caused C17's strict-xfail to XPASS on a later pass and abort the run. An
autouse fixture (`_isolate_config_defaults`) now deep-copies and restores `_DEFAULTS`
around each test, guaranteeing per-test isolation. Once the C17 deep-copy fix lands, the
underlying leak disappears too.
