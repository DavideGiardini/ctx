# PRD — Deferred cleanups (round 2)

## Goal
The small, lower-priority cleanups deferred from the first hardening PRD. Each is
independent and green-keeping. Rationale lives in the cited `docs/decisions/` notes;
PRD-1 (core hardening) is already complete — see git history and the `PROGRESS.md`
entries dated 2026-06-26.

## Constraints / notes
- Follow `AGENTS.md` "Designing new modules": deep modules, `core/` framework-free,
  reuse existing seams/patterns, deletion test before abstraction.
- Read the cited note before starting — it carries the *why* and, for task 1, the
  full design decision.
- Shared fixtures in `tests/conftest.py` (`repo`, `workspace`, `test_provider`,
  `make_node`, `stub_loader`) — reuse them.
- Task 2 is a pure refactor: rely on the existing suite staying green; do NOT add
  trivial new tests for it (per the test-strategy rule in `PROMPT.md`).
- Task 3 edits ADRs, which are **immutable** (`docs/decisions/README.md`): *annotate*
  with a correction pointer; do NOT rewrite the Decision/Consequences text.

## Tasks
Top-to-bottom by priority; the loop always takes the topmost unchecked task.

- [x] **Harden `list_files` — bounded text-sniff + traversal guard** — in
      `ctx/core/workspace.py`, replace the full-file `read_text` validation in
      `list_files()` with a **bounded sniff**: read only the first ~8 KB of each file
      and reject it if that prefix contains a NUL byte or is not valid UTF-8 (decode
      tolerantly at the chunk boundary so a multi-byte char split across it isn't a
      false negative). No extension allowlist — extensionless text files must pass.
      *Also* apply the same containment guard `read_file()` uses (`resolve()` +
      `is_relative_to(self._context.resolve())`) so `list_files` never lists a file
      `read_file` would reject. (Refs: 0008 #1 — see its **Decision** block — and
      0008 #2.) _Acceptance:_ unit tests in `tests/test_workspace.py` — (a) an
      extensionless text file (e.g. named `Dockerfile`) is listed; (b) a file whose
      first bytes contain a NUL byte is skipped; (c) a large valid-UTF-8 text file is
      listed (and is not fully read — assert via a read-size spy or a file larger than
      the sniff window); (d) a symlink under `.ctx/context/` that resolves outside it
      is not listed. `scripts/check.sh` green.

- [ ] **Extract a `_derive_title` helper** — in `ctx/core/conversation.py`, factor the
      duplicated title logic (`content[:MAX_TITLE_LENGTH].replace("\n", " ")`, used in
      `_ensure_conversation` and `resume_conversation`) into one private helper and call
      it from both. Pure refactor, no behavior change. (Ref: 0006 #5.) _Acceptance:_
      the existing `tests/test_conversation.py` title tests stay green unchanged; no
      new tests are warranted. `scripts/check.sh` green.

- [ ] **Annotate the two stale ADRs with a correction pointer** — ADRs are immutable,
      so do NOT rewrite their bodies. Append a brief, clearly-marked **Correction:**
      line to each: `docs/decisions/0003-conversation-repository.md` (its `:memory:`
      "supports tests" claim is false given the connection-per-method design — point to
      `0013`) and `docs/decisions/0004-pure-context-builder.md` (its "no side effects"
      claim is overstated — `build_context` logs — point to `0014 #3`). (Refs: 0013 #1,
      0014 #3.) _Acceptance:_ each of the two ADRs carries a one-line correction pointer
      to its observation note; Decision/Consequences text is unchanged; `scripts/check.sh`
      green (docs-only, nothing should break).

## Out of scope
- **Caching the text-sniff verdict** — deliberately deferred (see 0008): the sniff is
  already cheap for `.ctx/context/`; a `(path, mtime, size)`-keyed cache on `Workspace`
  is worth it only once the KB widens to the whole launch directory.
- All feature-gated items (persistence-model rework 0006 #2, import snapshots 0009,
  import escaping 0007 #3) and `Node` subclassing remain out of scope.
- Do not touch `main`/`develop`, `uv.lock` (use `uv`), `.ctx/`, or `.env`.
- DO NOT COMMIT `docs/Sprint Roadmap.md`, commit only your touched files.
