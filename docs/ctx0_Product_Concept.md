# Product Concept Document: ctx0

## 0. Purpose of This Document

This is the concept for **ctx0** — the first shippable version of ctx. It is *not* a demo of the north star described in the full ctx Product Concept; it is a product that stands on its own from moment zero.

Every decision here was made against three tests:

1. **Essential** — if it isn't necessary for a working v0, it isn't here.
2. **Useful at moment zero** — someone would choose ctx0 over the ChatGPT/Claude web app on day one, not because of what it might become.
3. **Has a soul** — it is recognizably ctx, not a clone of an already-existing product.

The full ctx concept remains the north star. Nothing here contradicts it; ctx0 is a strict subset chosen so that the pieces present are already whole.

## 1. What ctx0 Is

ctx0 is a **modal terminal chat client that you would use instead of the ChatGPT or Claude web app**. It does the two things that make a web chat app actually useful — talk to your files and search the web — and it wraps every one of those interactions in the ctx idiom: giving the user full control over the context of the conversation. It does that by implementing a dual-pane high-ground view of the conversation, and the ability to condense any part of the context into an editable node that is the only thing the model sees.

A web chat app with no file input and no web search is a toy. Those two capabilities are therefore not features ctx0 adds on top; they are the floor of usefulness. ctx0's contribution is that it builds that floor *inside* the ctx shell, so the baseline interactions carry the soul from the first message.

## 2. The Soul, Stated Plainly

The soul of ctx0 is the **high-ground view over the context, plus the ability to act on it**.

- **High ground:** the conversation is a dual-pane view. The right pane is a scannable list of truncated nodes — you see the whole shape of the conversation at a glance. The left pane shows the full, untruncated content of whatever node you are on. You get overview and fidelity at the same time, without losing your place.
- **Acting on it:** seeing bloat is only half a product. ctx0 lets you *remove* it. You can condense a span of turns into a single editable node, and from that point the model sees only that node — not the originals. The context window shrinks; you control exactly what the model knows.

Diagnosis (the view) without treatment (compaction) would be half a product. Treatment is what makes ctx0 ctx and not a nicer web app.

## 3. The One Engine

There is **one operation** in ctx0, exposed through two front doors:

> **Condense a source into an editable node whose output is the only thing the model sees.**

- The **source** is either a file (this is *import*) or a span of conversation turns (this is *compact*).
- In both cases the user supplies a **prompt/instruction** describing what to pull out or how to condense.
- The result is an **AI-drafted node**, always **user-editable before it is committed**.
- Only the node's **output** enters the request sent to the model. The raw source (the full file, or the original turns) does **not** enter the token stream. It still exists and is viewable in the left pane; it is simply not sent.

Import and compact are not two features. They are two entry points into the same engine. Building one builds most of the other.

### 3.1 Ground Truth

When you condense turns 3–7 into a summary node, two versions of that content now exist: the five original turns, and the one summary. The guarantee is simply: **the model receives the summary, not the five originals.** The originals remain on disk and viewable in the left pane, but they are no longer in the payload sent to the API. This is the entire mechanism — condensing physically removes the originals from the request and substitutes the node's output. When you compact, the context-window percentage drops, and what the model "knows" becomes the node's wording.

## 4. The Four Verbs

ctx0's engine is exactly this:

### 4.1 chat
A normal conversation with one LLM. Model and provider are configurable via a provider interface (the same seam used for search — see §7). Default behavior is an ordinary streaming chat turn.

### 4.2 import(file, prompt)
Point at a file, give an instruction (e.g., "pull out just the API signatures"). The file is processed by the AI according to the instruction; the resulting extract enters the conversation as a **context node**. The raw file never reaches the model — only the extract does. The node is editable before commit.

### 4.3 compact(range, prompt)
Select a span of turns, give an instruction (or use a default). The AI drafts a condensed node; you edit it; on commit it replaces those turns in what the model sees. The context percentage drops accordingly. **Reversible** via `:expand` (see §4.5).

### 4.4 search(query)
A **built-in** web search. The model can call it; results come back into the conversation as nodes, rendered in the same high-ground view as everything else. Search is hardwired, not a plugin — but the backend is swappable (see §7).

### 4.5 :expand (reversibility)
Any compaction can be reversed. `:expand` on a compacted node restores the original turns and removes the condensed node from the context. Reversibility is what makes users brave enough to compact aggressively — without it, the one distinctive action is a one-way door and people hesitate to use it.

## 5. The Dual-Pane View

ctx0 keeps the dual-pane layout because the view *is* the soul (§2).

- **Right pane — Conversation Graph:** a scrollable list of truncated nodes plus the input bar. Human, Assistant, and Context nodes are clamped to 2 lines; app/system messages to 1 line. Truncation acts as a maximum: shorter messages take proportionally fewer lines. Each node shows a role-colored left border and its context-weight percentage aligned to the right edge.
- **Left pane — Detail Inspector:** reactively shows the full, untruncated content of the node currently selected in the right pane.
  - For **Human / Assistant** nodes: the full message, rich-rendered and scrollable.
  - For **Context** nodes (import or compact output): the source is already shown here on selection, so the user can verify what was condensed without any separate "deep dive" step.
- **Header:** active conversation title, and total context-window percentage with a small progress bar — so the user sees compaction working.
- **Footer:** dynamic keybinding hints for the current mode.

### 5.1 Why no deep-dive
The full ctx concept has a `gd` "go to definition" that swaps the whole screen to show a node's origin blocks. ctx0 does **not** include it. Selecting a context node already shows its originals in the left pane, so deep-dive would be a redundant second mechanism for the same need. Cut.

## 6. Modes

ctx0 keeps the two-mode modal model:

- **Insert Mode:** the input bar is focused; the left pane locks to the last node. Incoming assistant responses stream in full in the left pane while the right-pane node stays truncated.
- **Edit Mode:** the right-pane node list is focused; Up/Down move the selection through every node and the left pane updates to match. `Esc` toggles between the two modes.

## 7. Providers (Chat and Search)

ctx0 uses a **provider interface, not a plugin system.**

The concern that motivates this: "web search" can mean many backends (Brave, Tavily, Exa, …), and locking users to one would undermine usefulness. But arbitrary extensibility (MCP servers, a registry, credential tiers, per-assistant tool activation) is a different and much larger thing that ctx0 deliberately does **not** buy.

The resolution: one internal abstraction — `search(query) -> results` — with two or three concrete backends behind it, selected by a single config line plus an API key. No registry, no server URLs, no activation tiers, no `/`-invocation framework.

This is the **same shape ctx0 already uses for the LLM side** (model + provider configurable). Two seams of the same kind, zero subsystems. If ctx ever wants general tool extensibility, MCP is how the north-star version earns it later; skipping it now does not make adding it later any harder.

## 8. What Was Deliberately Cut

Everything below is in the north-star ctx concept and is **intentionally absent** from ctx0. Each was cut because it failed test 1 (not essential) or test 2 (not needed for moment-zero usefulness), and none of the cuts damage test 3.

- **Knowledge Base / Project / venv model and the `.ctx/` structure.** Replaced by a single flat conversation store. No directory-as-KB, no multi-project selection.
- **RAG pull, search-over-KB, and push imports.** ctx0's import is a direct, instructed file condense (§4.2). KB-wide retrieval is a separate product.
- **Staleness indicators, snapshot-vs-live (`gD`), re-import.** Imports are static snapshots; that is enough at moment zero. (This apparatus depended on deep-dive, which is already cut.)
- **Assistants** (project-level behavior presets). One system prompt.
- **Tools / MCP subsystem** (global registry, project activation, assistant invocation, `/`-invocation). Replaced by one built-in, backend-swappable search (§7).
- **Branching, sub-chats, indexing.** A single linear conversation.
- ~~**The 3-split context inspector.**~~ **Kept — corrected 2026-07-11.** The original cut rationale ("no RAG prompt/output triads to display") was wrong: ctx0's own condensed nodes (import and compact output) carry exactly a prompt/source/output triad, and the 3-split is how the left pane "shows what was condensed" (§5) — it is the thing that makes cutting deep-dive safe. See ADR-0017.
- **The context-transparency surface** (drift `Δ` marker, the full-screen diff view, per-turn context reconstruction). Built for full ctx in Sprint 3b; ctx0 deletes the reading surface but **keeps stamping the underlying data** (`created_seq`, `ctx_hash`) so the feature can return later without a migration seam and with honest history. Middle compaction stays available without it. See ADR-0017.
- **Inline folding (`zo/zc/zR/zM`).** Redundant with left-pane inspection.
- **`:history` log / selective global reversal.** Per-node `:expand` is enough for v0.
- **The `~/.config` first-run wizard.** A single API key via env var or flat config file.
- **Config-driven truncation heights and `"auto"` values.** Hardcoded (2 lines / 1 line).
- **The "Big S" system-prompt-as-selectable-node and the Home-key jump.** The system prompt is simply the system prompt.
