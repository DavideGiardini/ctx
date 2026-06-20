---
name: ralph-tasks
description: Decompose one or more features into a Ralph PRD — small, independent, ordered tasks that autonomous loop iterations can each implement in a single fresh session. Invoke while brainstorming/planning when the user wants to "break this feature down for Ralph", "write a PRD", "split this into tasks for the autonomous agent", or "plan loop work". Produces scripts/ralph/PRD.md.
---

# Write Ralph Tasks

Turn a feature (or several) into a **PRD**: an ordered checklist of tasks that the
attended Ralph loop (`scripts/ralph/`) works through one at a time. Each loop
iteration is a *fresh* agent with no memory, so the decomposition is what makes or
breaks the run. Read `scripts/ralph/README.md` and `scripts/ralph/PROMPT.md` once
to remember exactly how tasks are consumed (topmost unchecked first; one task per
iteration; commit only when `scripts/check.sh` is green).

## What a good Ralph task looks like

Hold every task to all five rules:

1. **One fresh session.** Sized to fit a single context window — one component,
   function, widget, method, or migration. If it needs more than that, split it.
2. **Leaves the tree green and shippable.** Because each task commits
   independently and must pass `scripts/check.sh`, a task may NOT depend on a
   *later* task to compile, type-check, or run. Prefer vertical slices that work
   end-to-end over horizontal layers that are dead until a future task wires them.
3. **Independent where possible; ordered where not.** Minimize dependencies. When
   a real dependency exists, place the prerequisite *above* its dependent — the
   loop always takes the topmost unchecked task. Note the dependency in the task.
4. **Has a checkable acceptance criterion.** State an observable result that
   `scripts/check.sh` (ruff/mypy/pytest) OR the `qa-tester` subagent can verify.
   For UI/behavior tasks, write the criterion as the snapshot/state qa-tester
   should observe (e.g. "after `/export`, snapshot shows a system message
   'Exported to …'"). No acceptance criterion → not a task yet.
5. **Respects the architecture.** Follow the "Designing new modules" guidance in
   `AGENTS.md` (deep modules, core stays framework-free, seams only on a second
   real implementation). New domain logic lands in `ctx/core/*`; the UI is a thin
   adapter. Reuse existing modules/patterns — name them in the task.

Avoid: vague tasks ("improve persistence"), tasks that only make sense as a pair,
"refactor everything" mega-tasks, and tasks with no observable outcome.

## Process

### 1. Understand the feature(s)
Clarify scope before decomposing. If the goal, constraints, or boundaries are
ambiguous, ask the user 2–4 focused questions (AskUserQuestion) — what's in vs.
out, any UX expectations, any module they want reused or avoided. Don't invent
requirements.

### 2. Ground in the codebase
Use the `Explore` subagent to find the real modules, patterns, and seams the
tasks will touch, and read any relevant ADRs in `docs/decisions/`. Tasks must
reference actual files (e.g. `ConversationCore` in `ctx/core/conversation.py`),
not hypothetical ones. This is also where you catch hidden dependencies that
dictate ordering.

### 3. Decompose
Break each feature into tasks satisfying the five rules. Sequence them so:
- shared/core pieces that others build on come first,
- each step leaves the app working,
- UI wiring comes after the core capability it exposes exists.
Keep tasks at a consistent grain — if one task is 5× another, the big one
probably needs splitting. When unsure how small, err smaller: a fresh agent
recovers better from a too-small task than a too-big one.

### 4. Review with the user
Present the proposed task list (titles + one-line each + the ordering rationale,
and call out any dependencies). Let the user reorder, merge, drop, or resize
before anything is written. Treat this as the brainstorming step it is.

### 5. Write the PRD
Write `scripts/ralph/PRD.md` following the shape of `scripts/ralph/PRD.template.md`
exactly (Goal, Constraints/notes, Tasks as `- [ ]` with **bold title** — what —
_Acceptance:_, Out of scope). Each task line must be self-contained enough that a
fresh agent who reads only the PRD, `AGENTS.md`, and `PROGRESS.md` can execute it.
Then tell the user how to run it:
```
git switch -c feat/<name>     # if not already on a feature branch
scripts/ralph/loop.sh
```

## Notes
- One PRD = one coherent unit of work (a feature or a tight cluster). For several
  unrelated features, either write several PRDs or group them under clearly
  separated sections — but keep the single ordered task list the loop reads.
- It's fine for the *last* task to be "verify the whole feature end-to-end via
  qa-tester" when the criteria span multiple earlier tasks.
- If decomposition reveals an architectural decision worth not re-litigating,
  suggest recording it as an ADR (`docs/decisions/`) rather than burying it in a
  task.
