# Step 1: Minimal TUI Chatbot — Implementation Brief

## Overview

Build a minimal but well-structured terminal chat application using Python and the Textual framework. The goal is a clean, working chat loop with streaming, a model switcher, and an architecture explicitly designed to grow. No features beyond what is listed here should be implemented.

---

## Tech Stack

- **Python 3.11+**
- **Textual** — TUI framework
- **LiteLLM** — unified LLM provider abstraction
- **uv** — package manager

---

## Application Structure

```
appname/
├── main.py
├── ui/
│   ├── __init__.py
│   ├── app.py
│   └── widgets/
│       ├── __init__.py
│       ├── message_list.py
│       └── input_bar.py
├── core/
│   ├── __init__.py
│   ├── provider.py
│   └── context.py
└── models/
    ├── __init__.py
    └── nodes.py
```

---

## Data Model

A single `Node` dataclass in `models/nodes.py`. Every message is a node.

```python
@dataclass
class Node:
    id: str        # uuid
    role: str      # "user" | "assistant"
    content: str
    node_type: str # always "message" in Step 1
    meta: dict     # empty for now, reserved for future use
```

The active conversation is an in-memory list of `Node` objects. No persistence in this step.

---

## Modules

### `core/provider.py`
Wraps LiteLLM. Exposes a single async function:

```python
async def stream_response(
    messages: list[dict],
    model: str,
    on_token: Callable[[str], None],
    on_done: Callable[[str], None],
    on_error: Callable[[Exception], None],
) -> None
```

Knows nothing about `Node` objects. Handles LiteLLM exceptions internally via `on_error`.

### `core/context.py`
A single pure function:

```python
def build_context(nodes: list[Node]) -> list[dict]:
```

Takes the node list, returns `[{role, content}]` for the provider. This is the only place that decides what the model sees. In Step 1 it maps every node directly — but this is where all future context transformations will live.

### `models/nodes.py`
The `Node` dataclass. No logic, just the data structure.

---

## UI

### Layout

```
┌─────────────────────────────┐
│                             │
│     message history         │
│     (scrollable)            │
│                             │
├─────────────────────────────┤
│ > input                     │
└─────────────────────────────┘
```

Two areas, nothing else.

### `ui/widgets/message_list.py`
Scrollable widget. Renders `Node` objects — never raw strings. Each node rendered as a block with a role label (`You` / `Assistant`) and Markdown content via Textual's built-in `Markdown` widget. Auto-scrolls to latest message.

### `ui/widgets/input_bar.py`
Single-line text input at the bottom. `Enter` submits.

### `ui/app.py`
The main Textual `App` class. Owns the in-memory node list, orchestrates widgets and core modules. Handles the streaming lifecycle: creates a placeholder assistant node on submit, updates it token by token, finalizes on done.

---

## Interaction

The input box is always focused and ready to type. `Enter` submits the message. The only special input is the `/model` command:

- `/model <model_string>` — switches the active model for all subsequent messages. The model string is passed directly to LiteLLM (e.g. `anthropic/claude-sonnet-4-5`, `openai/gpt-4o`). If the user types `/model` with no argument, the current model is displayed as a system message in the chat.

No other slash commands. No modes.

---

## Streaming and Interrupt

1. User hits `Enter` — user node appended and rendered.
2. `build_context` produces the API payload.
3. Empty assistant node appended (shows a spinner/cursor).
4. `stream_response` called; each token updates the assistant node in place and re-renders.
5. On done, node finalized.
6. `Ctrl+C` cancels the stream. Partial response kept, `meta: {"interrupted": True}` set, `[interrupted]` label shown.

---

## Configuration

`DEFAULT_MODEL = "anthropic/claude-sonnet-4-5"` in `ui/app.py`. API keys read from environment variables by LiteLLM. No config file in this step.

---

## Out of Scope for Step 1

Everything not listed above.