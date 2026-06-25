"""ctx-agent MCP server.

Extends ``textual-mcp-server``'s FastMCP server with one ctx-specific tool,
``ctx_snapshot``, returning a compact semantic view of the running app
(``ChatApp.describe_state`` + the agent renderer).

Registering on the library's shared ``mcp``/``_session_manager`` means its
generic driving/observation tools (``textual_launch``, ``textual_press``,
``textual_type_text``, ``textual_screenshot``, ``textual_check_errors``, …) and
this semantic tool all operate on the same live sessions in one process.

Typical flow for an agent:
    textual_launch("tools.agent.harness:HarnessApp")  -> session_id
    ctx_snapshot(session_id)                         # cheap semantic state
    textual_press(session_id, ["i"])                 # interact
    ctx_snapshot(session_id)                         # diff
    textual_check_errors(session_id)                 # catch crashes
"""

from __future__ import annotations

import contextlib

from textual_mcp.server import _session_manager, mcp

from tools.agent.snapshot import render

# --- Hardening: keep navigation keyboard-only --------------------------------
# ctx is a keyboard-driven TUI. Remove the library's mouse tools so an agent can
# only move via real keyboard input (textual_press / textual_type_text) plus
# read-only observation. This makes "navigate like a real user" a structural
# guarantee, not just a convention. Selector-based *observation* (textual_query)
# is unaffected — it only looks, never acts.
_DISABLED_TOOLS = ("textual_click", "textual_hover")
for _name in _DISABLED_TOOLS:
    # suppress: already absent (e.g. a future library version that drops them).
    with contextlib.suppress(Exception):
        mcp.remove_tool(_name)


@mcp.tool(
    name="ctx_snapshot",
    description=(
        "Return a compact, semantic snapshot of the running ctx app: mode, "
        "focus, model, streaming, selection, split viewer, and the message "
        "nodes (by stable index). Token-cheap and meaningful — prefer this "
        "over textual_snapshot for ctx, and use textual_screenshot only for "
        "genuine visual bugs."
    ),
)
async def ctx_snapshot(session_id: str) -> str:
    """Render ``describe_state()`` for the app in the given session."""
    try:
        session = _session_manager.get_session(session_id)
    except Exception as exc:
        return f"error: {exc}"
    app = session.app
    if not hasattr(app, "describe_state"):
        return "error: the active app is not a ctx ChatApp"
    return render(app.describe_state())


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
