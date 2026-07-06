# PRD — <feature name>

Copy this to `scripts/ralph/PRD.md` and fill it in before running the loop.
Keep it out of version control if it's throwaway; commit it if the plan is shared.

## Goal
<One paragraph: what we're building and why. The intended outcome.>

## Constraints / notes
- <Anything the agent must respect: existing modules to reuse, ADRs that apply,
  things NOT to change.>

## Tasks
Each task must be **right-sized for a single fresh session** (one component,
function, widget, or migration). Order them top-to-bottom by priority — the loop
always picks the topmost unchecked one. Give each a concrete **acceptance
criterion** the `qa-tester` subagent (or the test gate) can check. For **visual**
UI tasks (color, layout, spacing, alignment), state the **visible outcome** as a
VLM-checkable sentence — `qa-tester` can't see appearance; the agent renders it via
`tools/agent/visual.py` and looks (PROMPT.md step 7). Always name a deterministic
floor (snapshot field / CSS class / unit test) under the picture.

- [ ] **<Task 1 title>** — <what to do>. _Acceptance:_ <observable result; for a
      behavioral UI task, the snapshot/state qa-tester should see; for a *visual*
      task, the visible outcome to look at + the deterministic floor>.
- [ ] **<Task 2 title>** — <what to do>. _Acceptance:_ <…>.
- [ ] **<Task 3 title>** — <what to do>. _Acceptance:_ <…>.

<!-- As tasks complete, the loop PRUNES them (PROMPT.md step 8): the finished
task's full body is cut from here and moved to `PRD-done.md`, leaving a one-line
entry under a "## Completed" ledger below. This keeps the live PRD lean because the
loop re-reads the whole file every iteration. Start with no Completed section; it
grows as the ledger, and `PRD-done.md` is created on the first completion. -->

## Out of scope
- <Explicitly list what this feature does NOT include, so the loop doesn't drift.>
