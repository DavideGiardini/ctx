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
criterion** the `qa-tester` subagent (or the test gate) can check.

- [ ] **<Task 1 title>** — <what to do>. _Acceptance:_ <observable result;
      for UI tasks, the snapshot/state the qa-tester should see>.
- [ ] **<Task 2 title>** — <what to do>. _Acceptance:_ <…>.
- [ ] **<Task 3 title>** — <what to do>. _Acceptance:_ <…>.

## Out of scope
- <Explicitly list what this feature does NOT include, so the loop doesn't drift.>
