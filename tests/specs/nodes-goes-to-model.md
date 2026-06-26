# Behavioral contract — `Node.goes_to_model()`

Module: `ctx/models/nodes.py` — `Node.goes_to_model() -> bool`

Single source of truth for "which nodes reach the LLM when building context".
The rule is role-or-node_type based: True when the node is a user/assistant
chat turn OR a context import; False otherwise.

## Mandated truth table (acceptance floor)

### G1. A user node goes to the model
- Given:    a node built as a user chat turn (`role="user"`, `node_type="message"`)
- Expect:   `goes_to_model()` returns `True`
- Rationale: PRD truth table — user turns are part of the conversation sent to the LLM.

### G2. An assistant node goes to the model
- Given:    a node built as an assistant chat turn (`role="assistant"`, `node_type="message"`)
- Expect:   `goes_to_model()` returns `True`
- Rationale: PRD truth table — assistant turns are part of the conversation sent to the LLM.

### G3. A context node goes to the model
- Given:    a node built as a context import (`node_type="context"`, `role="context"`)
- Expect:   `goes_to_model()` returns `True`
- Rationale: PRD truth table — context imports are injected into the prompt. Note the
             role is "context", not user/assistant, so this case proves the predicate
             keys off `node_type` for context, not role.

### G4. A system node does not go to the model
- Given:    a node built as a system breadcrumb (`role="system"`, `node_type="system"`)
- Expect:   `goes_to_model()` returns `False`
- Rationale: PRD truth table — system breadcrumbs are bookkeeping, not LLM input.

## Edge cases implied by the intent

### G5. A node that is neither a chat role nor a context type does not go to the model
- Given:    a node with a role outside {"user","assistant","context"} and a
            node_type outside {"context"}, e.g. `role="tool"`, `node_type="message"`
- Expect:   `goes_to_model()` returns `False`
- Rationale: The rule is True only for the named kinds; "everything else does not".
             Default-deny for unrecognized kinds.

### G6. A context node is recognized via node_type even when its role is not the context role
- Given:    a node with `node_type="context"` but a role that is NOT "context"
            (e.g. `role=""`)
- Expect:   `goes_to_model()` returns `True`
- Rationale: Intent states a context import is identified by its node_type
             ("context"), not by role. The node_type signal alone must trigger True.

### G7. A node whose role is a chat role goes to the model regardless of node_type
- Given:    a node with `role="user"` and a non-message node_type (e.g.
            `node_type="system"`)
- Expect:   `goes_to_model()` returns `True`
- Rationale: The rule is an OR: a user/assistant role qualifies on its own. This
             pins that the role branch does not require node_type=="message".
- Ambiguity flagged: see A1 below — the intent does not explicitly cover a
  role/node_type mismatch. Assumed the OR is literal (role OR node_type), so a
  chat role alone suffices.

### G8. A default/empty node does not go to the model
- Given:    a node constructed with no role and the default `node_type="message"`
            (`role=""`, `node_type="message"`)
- Expect:   `goes_to_model()` returns `False`
- Rationale: An empty role is not a chat role and message is not the context type,
             so the predicate defaults to deny.

### G9. The predicate returns a real bool
- Given:    any of the above nodes
- Expect:   the return value is of type `bool` (e.g. `True is x`, not a truthy
            string/int)
- Rationale: Signature is `-> bool`; downstream `build_context` branches on it, so it
             must be a genuine boolean, not an arbitrary truthy value.

## Intent ambiguities assumed past

- A1 (covered by G7): Behavior when role and node_type disagree (e.g. role="user"
  with node_type="system", or role="system" with node_type="context") is not stated
  explicitly. I assumed the predicate is a literal OR of the two independent signals:
  True if `role in {"user","assistant"}` OR `node_type == "context"`. Under that
  reading a chat role alone, or the context node_type alone, each independently
  yields True. If the real rule is conjunctive (role AND node_type must both match a
  recognized kind), G6 and G7 would need revision — flagging for human resolution.
- A2: Case-sensitivity and whitespace (e.g. role="User", " user", node_type="Context")
  are not specified. I assumed exact, case-sensitive string matching with no trimming,
  consistent with the factory classmethods producing exact lowercase values. Not
  asserted as a contract item to avoid over-specifying; noted for the human.
