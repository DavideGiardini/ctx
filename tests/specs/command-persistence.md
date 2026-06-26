# Behavioral contract — uniform command persistence

Derived purely from the statement of intent (PRD task + ADR 0006 #6) and the
public interface of `ConversationCore` and `Node.system`. No implementation was
read. The governing rule:

> A breadcrumb persists **iff** it was raised inside an active conversation.
> Mechanically: an active conversation means `conversation_id != ""`; a node
> carrying a non-empty `conversation_id` is written; storage skips any node
> whose `conversation_id == ""`, so breadcrumbs raised before a conversation
> exists stay transient.

A "breadcrumb" is the system node returned by `set_model`,
`check_connectivity`, and `add_system_message`.

---

CP1. set_model breadcrumb persists inside an active conversation
  Given:    a core with a conversation already established (a prior `submit(...)`),
            then `node = core.set_model("anthropic/claude-3-opus")`.
  Expect:   `repo.load(core.conversation_id)` contains a node whose `content`
            equals `node.content`, with `role == "system"` and
            `conversation_id == core.conversation_id`. The returned `node` itself
            has `role == "system"`, `node_type == "system"`, and the same
            `conversation_id`.
  Rationale:Intent: switching model while a conversation is active must persist
            the "Model set to: X" notice so it reappears on resume; persistence
            is now uniform across command methods.

CP2. set_model breadcrumb content names the model
  Given:    `node = core.set_model("openai/gpt-4o")` inside an active conversation.
  Expect:   the model string `"openai/gpt-4o"` is a substring of `node.content`
            (docstring: breadcrumb reads "Model set to: <model>").
  Rationale:The persisted notice must identify which model was set so the resumed
            transcript is meaningful, not an opaque marker.

CP3. set_model breadcrumb survives a fresh reload (round-trip on resume)
  Given:    after `submit` then `set_model("mistral/large")`, capture
            `cid = core.conversation_id` and the returned breadcrumb content.
  Expect:   `repo.load(cid)` (the storage-of-record query a resume would issue)
            returns a list that includes a system node with that content; i.e. the
            breadcrumb is present in storage independent of the in-memory `nodes`.
  Rationale:The user-visible consequence in intent is "reappears when that
            conversation is resumed"; resume reads from storage, so the assertion
            must hit storage, not the live object.

CP4. check_connectivity breadcrumb persists inside an active conversation
  Given:    an active conversation, then
            `node = await core.check_connectivity("anthropic/claude-3-opus")`
            with the default (success) provider.
  Expect:   `repo.load(core.conversation_id)` contains a node whose `content`
            equals `node.content`, `role == "system"`,
            `conversation_id == core.conversation_id`; returned `node` has
            `node_type == "system"`.
  Rationale:Connectivity results were previously transient; uniform policy now
            persists them when raised inside a conversation.

CP5. add_system_message breadcrumb persists inside an active conversation
  Given:    an active conversation, then
            `node = core.add_system_message("Context budget exceeded; trimming.")`.
  Expect:   `repo.load(core.conversation_id)` contains a node whose `content`
            equals `"Context budget exceeded; trimming."` (== `node.content`),
            `role == "system"`, `conversation_id == core.conversation_id`;
            returned `node` has `node_type == "system"`.
  Rationale:Ad-hoc system messages are breadcrumbs too and must obey the same
            uniform persistence rule.

CP6. Breadcrumb raised with NO active conversation is transient (set_model)
  Given:    a freshly set-up core with `core.conversation_id == ""` and no prior
            `submit`; then `node = core.set_model("openai/gpt-4o-mini")`.
  Expect:   `node.conversation_id == ""`, and `repo.load("")` does NOT contain a
            node whose content equals `node.content` (storage skips nodes lacking
            a conversation_id). The structural exception, not a special case.
  Rationale:Intent: a command with no conversation yet produces an empty
            `conversation_id`; storage skips it, so it stays transient.

CP7. Breadcrumb raised with NO active conversation is transient (add_system_message)
  Given:    fresh core, no prior submit;
            `node = core.add_system_message("Standalone notice before any chat.")`.
  Expect:   `node.conversation_id == ""`; `repo.load("")` does not contain a node
            with that content.
  Rationale:Same structural rule applied to the ad-hoc system message path.

CP8. Breadcrumb raised with NO active conversation is transient (check_connectivity)
  Given:    fresh core, no prior submit;
            `node = await core.check_connectivity("anthropic/claude-3-opus")`.
  Expect:   `node.conversation_id == ""`; `repo.load("")` does not contain a node
            with that content.
  Rationale:Same structural rule applied to the async connectivity path.

CP9. Node.system factory honors durability via conversation_id argument
  Given:    `transient = Node.system("note")` and
            `durable = Node.system("note", conversation_id="conv-123")`.
  Expect:   both have `role == "system"`, `node_type == "system"`,
            `content == "note"`, and empty `meta`; `transient.conversation_id == ""`
            while `durable.conversation_id == "conv-123"`.
  Rationale:The factory is the single seam that decides durability; the optional
            `conversation_id` defaulting to "" is what makes "no conversation"
            transient. (Tests the contract of the factory directly.)

CP10. Breadcrumbs carry the SAME conversation_id as the conversation that owns them
  Given:    active conversation; raise one of each breadcrumb
            (`set_model`, `add_system_message`).
  Expect:   every returned breadcrumb's `conversation_id` equals
            `core.conversation_id`, and each appears under `repo.load(core.conversation_id)`.
  Rationale:Persistence "carrying the active conversation_id" means the breadcrumb
            is filed under the live conversation, not orphaned or misfiled.

CP11. A breadcrumb raised after submit coexists with the conversation's real turns
  Given:    `submit("Summarize the design doc.")`, then `set_model("openai/gpt-4o")`.
  Expect:   `repo.load(core.conversation_id)` contains BOTH a node whose content is
            the user text `"Summarize the design doc."` (role == "user") AND the
            system breadcrumb (role == "system"); the breadcrumb does not displace
            or overwrite the conversation's turns.
  Rationale:Uniform persistence adds breadcrumbs to the transcript; it must not
            erase the real turns it sits alongside.

---

## Intent ambiguities assumed past (flag for human)

A1. The exact wording of the connectivity success breadcrumb is unspecified
    (intent only says "describing the result"). Tests therefore assert on
    `node.content == <persisted node content>` rather than on a literal string,
    and do not assume the success text. The failure/warning text shape
    ("includes the error text") is left untested here because triggering a
    failure requires a non-default provider whose contract isn't specified.

A2. `set_model` is documented to "switch the active model"; whether it also
    updates `core.model` is implied but not part of the persistence policy, so
    CP1-CP3 do not assert on `core.model`. (Could add if desired.)

A3. "active conversation" is identified by `conversation_id != ""`. The interface
    states the empty-string sentinel explicitly, so this is treated as defined,
    not assumed.

A4. Whether `repo.load("")` raises vs. returns `[]` is unspecified. CP6-CP8 are
    written to tolerate either by asserting absence-of-content rather than length,
    and by guarding the load in a way that treats a raise as "nothing persisted."
