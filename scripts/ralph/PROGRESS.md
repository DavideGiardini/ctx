# Ralph Progress Log

Append-only cross-iteration memory. Each fresh loop iteration reads the tail of
this file, then adds an entry describing what it did, key decisions, and any
gotcha the next iteration must know. Newest entries at the bottom.

Git history is the source of truth for *what changed*; this file captures the
*why* and the *watch-outs* that don't fit in a commit message.

---

<!-- Example entry:
## 2026-06-20 — Task: add /export command
- Added `export` handler to ConversationCore returning the rendered transcript.
- Decision: kept formatting in core (pure) so it's testable without the UI.
- Gotcha: HistoryScreen caches the conversation list; call `refresh_list()` after
  mutations or the new entry won't appear until reopen.
-->
