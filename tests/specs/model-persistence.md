# Behavioral contract — conversation model persistence

Derived purely from the PRD intent + decision note 0014 #2 and the public interface.
Numbered MP1.. so tests can cite them.

---

## Storage layer (`ConversationRepository`)

MP1. save stores the model; get_model returns it
  Given:    A conversation saved with a non-empty `model` (e.g. "claude-opus-4")
            and at least one persistable node.
  Expect:   `get_model(conversation_id)` returns exactly that model string.
  Rationale:Intent #1 — saving a conversation also stores its model and loading it
            back returns that model. The model conceptually belongs to the
            conversation and must round-trip through storage.

MP2. save with default/empty model returns ""
  Given:    A conversation saved without the `model` keyword (defaults to ""),
            with a persistable node.
  Expect:   `get_model(conversation_id)` returns "" (the empty string), NOT None.
  Rationale:Interface contract: a row saved with an empty/default model returns "".
            This distinguishes "row exists, no model" from "no row".

MP3. get_model of an unknown conversation returns None
  Given:    A conversation_id that was never saved.
  Expect:   `get_model(conversation_id)` returns None.
  Rationale:Intent #4 — asking for the model of a non-existent conversation returns
            None. None vs "" is the observable signal that there is no row at all.

MP4. re-saving a conversation updates its model
  Given:    A conversation saved with model "model-a", then saved again (same id)
            with model "model-b".
  Expect:   `get_model(conversation_id)` returns "model-b".
  Rationale:Intent #1 + save semantics: the conversation owns the model; a later
            save reflects the current model, not a stale one.

MP5. saving only non-persistable nodes for a new id creates no row
  Given:    A `save` for a brand-new id whose nodes are all non-persistable (no
            conversation_id on them), with any model value.
  Expect:   `get_model(conversation_id)` returns None (no row was created).
  Rationale:Persistence note: a save with only non-persistable nodes and a
            not-yet-existing id creates no conversation row at all; therefore there
            is no stored model and get_model must report None.

---

## Conversation layer (`ConversationCore`) — round-trip

MP6. set_model + submit persists the chosen model (floor test)
  Given:    A core; `set_model("claude-opus-4")`; then `submit("hello there")`
            (which assigns a conversation_id and persists).
  Expect:   On a FRESH `ConversationCore` sharing the same repo, after
            `resume_conversation(<that id>)`, `core.model == "claude-opus-4"`.
  Rationale:Intent #1 + #2 — the model must round-trip through storage and be
            restored on resume, surviving the loss of in-memory state (new core /
            restart). This is the mandatory floor behavior.

MP7. resume restores the model active at save time, overriding the resumer's model
  Given:    Conversation saved by core A with model "model-stored". A FRESH core B
            whose current model differs (e.g. set to "model-current") resumes that id.
  Expect:   After resume, `core_b.model == "model-stored"`.
  Rationale:Intent #2 — resuming restores the model that was active when the
            conversation was saved, not whatever the resumer happened to be using.

MP8. backward-compat: stored "" must NOT clobber the resumer's current model
  Given:    A conversation persisted with an empty model ("") but with persistable
            nodes (a pre-feature-style row). A FRESH core whose model has been set
            to a known non-default value (e.g. "model-current") resumes that id.
  Expect:   After resume, `core.model == "model-current"` (unchanged); the resume
            does NOT overwrite it with "".
  Rationale:Intent #3 — a conversation predating the model feature (stored model "")
            must not clobber the resumer's current/default model; the existing
            in-memory model is kept.

MP9. resuming an unknown id returns [] and leaves the model untouched
  Given:    A fresh core with a known model (e.g. set to "model-current"); call
            `resume_conversation("does-not-exist")`.
  Expect:   The call returns [] and `core.model == "model-current"` (unchanged).
  Rationale:Interface contract: unknown id → returns [] and changes nothing,
            including the model.

MP10. resume restores the persisted nodes too (round-trip integrity)
  Given:    A core that submits a message and persists, then a fresh core resumes
            the id.
  Expect:   `resume_conversation` returns a non-empty list of nodes (the persisted
            conversation), confirming the resume actually loaded a real row rather
            than a no-op that left the default model coincidentally correct.
  Rationale:Guards MP6/MP7 against a false pass where resume silently does nothing:
            a genuine restore must surface the stored nodes alongside the model.

---

## Intent ambiguities assumed past (flag for human)

A. The exact `DEFAULT_MODEL` constant value is not given. MP6/MP7/MP8/MP9 therefore
   avoid asserting the literal default; instead they set an explicit, distinct model
   on the resumer (or the saver) and assert against that known value. The floor test
   (MP6) asserts the saved model equals a model we explicitly set — independent of
   the default.

B. MP8 assumes a "pre-feature" row can be produced via the storage layer by saving
   with model="" plus a persistable node (no raw-schema/migration manipulation, per
   instructions). If empty-model rows cannot arise through the public save path this
   case may need a different setup — but the interface explicitly states
   save(..., model="") is valid and get_model then returns "", so this is sound.

C. "Drive a submit so it persists" (MP6): submit is documented to assign a
   conversation_id and persist, so no explicit persist() call is asserted as
   required; the test reads back through a fresh core, which is implementation-
   agnostic about whether submit or a later persist did the write.
