---
name: plan-feature
description: Brainstorm and plan a new feature for ctx before any code is written. Use when the user wants to "plan a feature", "brainstorm a feature", "design how to add X", or "think through" a change before building. Drives a back-and-forth until every decision is settled, checks the web for current best practices, and produces a plan that includes a precise test plan for the qa-tester subagent. It does NOT implement.
---

# Plan a Feature

Turn a rough feature idea into a fully-decided, testable plan — *without writing
feature code*. Your job here is to think, search, question, and decide together
with the user. Implementation is a separate step that happens only after the plan
is agreed.

Compose with the skills already in this repo instead of duplicating them:
`/grilling` (the interview loop), `codebase-design` (deep-module vocabulary),
`improve-codebase-architecture` (if the feature exposes architectural friction),
and `/ralph-tasks` (to decompose the agreed plan for the autonomous loop).

## Hard rules
- **Do not implement.** No feature code, no scaffolding, no stubs while this skill
  runs. It ends with an agreed plan, not a diff. (If the user explicitly says
  "stop planning, build it," hand off — but don't drift there on your own.)
- **Don't settle on stale knowledge.** Your training data has a cutoff. For
  anything that evolves — library/framework capabilities (Textual, litellm), APIs,
  model features, algorithms, "state of the art" approaches — **use your web search
  tool / search MCP to check the current state as of today** before locking a
  decision. Check the actual current date; don't assume your memory is current.
  Say what you searched and what you found that changed (or confirmed) the design.
- **One decision at a time, no premature convergence.** Keep going back and forth
  with the user until every open branch is resolved. Recommend, don't just
  enumerate — but the user decides.

## Process

### 1. Frame the feature
Restate the goal in one or two sentences and confirm it with the user. Surface the
obvious unknowns immediately (scope, who it's for, what "done" looks like).

### 2. Research the current state (when relevant)
If the feature touches anything that may have moved since your training cutoff,
search the web first. Examples worth a search: a Textual widget/API you'd rely on,
a litellm capability, a model's feature set, a known-good pattern for the problem.
Summarize findings that affect the design; cite what you used. Skip this only when
the feature is purely internal and nothing external is in play.

### 3. Ground in the codebase and the vision
Use the `Explore` subagent to find the modules, seams, and patterns the feature
touches. Read relevant ADRs in `docs/decisions/` and the "Designing new modules"
guidance in `AGENTS.md`. Decide where the feature lives (core vs. ui), what to
reuse, and which seam it sits behind — use `codebase-design` vocabulary.

The product being built is **ctx0** — read `docs/ctx0_Product_Concept.md` to make
sure the feature fits its scope tests (essential / useful at moment zero / has a
soul). Planning is also the **only** sanctioned time to consult the long-term
north star in `docs/north-star/` (the full ctx Product Concept and the parked
Sprint Roadmap, which holds settled design worth reusing — e.g. the S5 import
grill). Read those to make sure this feature is a coherent *step toward* the
vision and doesn't paint us into a corner. Reading them triggers a permission
prompt (they're gated so implementation agents never see them) — approving that
prompt here is expected and correct. Do **not** drag the vision's future
features into this plan beyond the step being planned now.

**Keep the concept in sync.** The ctx0 Product Concept is the shipping spec, so it
must not silently drift out of date. Whenever a decision taken during this session
**shifts away from what the concept describes** — changes a behavior, renames or
restructures a concept, or deliberately diverges from a documented design — stop and
**ask the user whether to update `docs/ctx0_Product_Concept.md`** to reflect the new
decision.
Distinguish this from an *intermediate implementation* (a stepping stone on the way
to the documented goal, which should leave the concept untouched): if you can't tell
which it is, ask. Don't edit the concept on your own initiative — surface the
divergence, propose the specific edit, and let the user decide.

### 4. Grill until every decision is made
Run the interview loop (lean on `/grilling`). Drive the conversation back and
forth, using `AskUserQuestion` for concrete forks, until none of these are open:
scope and out-of-scope, UX / interaction (keys, commands, modes), data/state
changes, module placement and interface shape, error and edge-case behavior,
migration/back-compat, and any external dependency choices (informed by step 2).
Present trade-offs with a recommendation each time. Do not move on while a
load-bearing question is unanswered — if the user is unsure, help them decide.

### 5. Define the test plan (mandatory)
A feature is not planned until you've said exactly how it will be verified. Write
this as part of the plan:

- **Deterministic gate** — what `scripts/check.sh` should cover: the points to
  unit-test (and, when the Pilot-driven pytest layer exists, the assertions on
  `describe_state()`), and that ruff + mypy stay green.
- **Behavioral QA via the `qa-tester` subagent** — write the *exact brief* you
  will hand the subagent, precise enough to run as-is:
  - **Mode** — usually `verify-feature` (use `verify-fix` for bug work,
    `stress-test` for hardening).
  - **Setup** — launch `tools.agent.harness:HarnessApp`.
  - **Steps** — the ordered keypresses / commands to drive the flow.
  - **Expected results** — for each checkpoint, the observable state the
    `ctx_snapshot` should show (e.g. "after `/export`, snapshot shows a system
    node containing 'Exported to …' and `streaming=no`"). Express every acceptance
    criterion as *drive X → expect snapshot Y*.
  - **Negative / edge probes** — what to try that should fail gracefully, and the
    `textual_check_errors` expectation (no crashes/worker errors).
  - **Pass condition** — what the subagent's report must say for the feature to
    count as done.

### 6. Output the plan and hand off
Produce a concise plan: **Goal**, **Research notes** (with sources), **Decisions**
(+ rationale), **Design** (modules/seam touched, what's reused), **Test plan**
(from step 5), and **Out of scope**. Then offer next steps:
- For autonomous building: run `/ralph-tasks` to decompose it into a PRD (the test
  plan becomes the acceptance criteria on each task).
- For hands-on building: implement directly (autonomous by default, or `/professor`
  for step-by-step).
If a load-bearing decision would otherwise be re-litigated later, offer to record
it as an ADR in `docs/decisions/`.
