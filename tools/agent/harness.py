"""Deterministic, no-arg ChatApp for headless agent driving.

Wires ``ChatApp`` with a ``TestProvider`` (canned tokens, no network) and a
``Workspace`` rooted in a fresh temp directory, so agent runs are reproducible
and never touch the network or pollute the repo's ``.ctx/``.

No-arg constructible so ``textual-mcp-server``'s loader can instantiate it as
``tools.agent.harness:HarnessApp``. The temp directory is ephemeral (left to the
OS temp cleaner); each instantiation gets its own.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ctx.core.provider import TestProvider, Usage
from ctx.core.workspace import Workspace
from ctx.ui import app as ctx_app

CANNED_RESPONSE = ["This ", "is ", "a ", "canned ", "test ", "response."]

# A canned provider usage so the header-gauge calibration path is exercised in
# headless runs. ``prompt_tokens`` is small enough to stay within the core's
# ``CALIBRATION_TOLERANCE`` (10×) of any short typed message's local estimate,
# so the gauge sheds its ``~`` after a turn instead of staying perpetually
# approximate.
CANNED_USAGE = Usage(prompt_tokens=20, completion_tokens=6, total_tokens=26)

SAMPLE_FILE_NAME = "sample.txt"
SAMPLE_FILE_BODY = "Sample context file for agent testing.\nLine two.\n"

_UI_DIR = Path(ctx_app.__file__).parent


class HarnessApp(ctx_app.ChatApp):
    """ChatApp pre-wired for deterministic, network-free agent runs."""

    # ChatApp.CSS_PATH is relative to ctx/ui/. As a subclass defined in
    # tools/agent/, Textual would resolve those paths against tools/agent/, so we
    # re-anchor them to the real UI directory (reusing the base list).
    CSS_PATH = [str(_UI_DIR / path) for path in ctx_app.ChatApp.CSS_PATH]

    def __init__(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="ctx-harness-"))
        workspace = Workspace(root)
        # Seed one context file so /include and the file-viewer split are
        # exercisable out of the box.
        workspace.ensure()
        (workspace.context_dir / SAMPLE_FILE_NAME).write_text(
            SAMPLE_FILE_BODY, encoding="utf-8"
        )
        super().__init__(
            provider=TestProvider(CANNED_RESPONSE, usage=CANNED_USAGE),
            workspace=workspace,
        )
