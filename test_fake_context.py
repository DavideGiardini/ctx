import asyncio
from pathlib import Path

from ctx.models.nodes import Node
from ctx.ui.app import ChatApp
from ctx.ui.widgets.detail_inspector import DetailInspector
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList

_CSS_ROOT = Path("ctx/ui")


class TestApp(ChatApp):
    CSS_PATH = [
        str(_CSS_ROOT / "app.css"),
        str(_CSS_ROOT / "widgets" / "message_list.css"),
        str(_CSS_ROOT / "widgets" / "input_bar.css"),
        str(_CSS_ROOT / "widgets" / "detail_inspector.css"),
    ]
    """ChatApp subclass that boots with pre-seeded fake nodes for UI testing."""

    def on_mount(self) -> None:
        # Normal setup
        self.core.setup()
        self.query_one(InputBar).focus()
        self._update_footer()
        self._update_header()

        # Inject fake nodes directly into the core conversation
        self.core.conversation_id = "test-conv-001"
        self.core.conversation_title = "Fake Context Test"

        # 1. Root system prompt
        self.core.nodes.append(
            Node(
                role="system",
                content="You are a helpful assistant.",
                node_type="system",
                conversation_id=self.core.conversation_id,
            )
        )

        # 2. User message
        self.core.nodes.append(
            Node(
                role="user",
                content="Please summarize these files for me.",
                conversation_id=self.core.conversation_id,
            )
        )

        # 3. DEGENERATE context node — no prompt, output == raw_content
        #    This should render as a SINGLE pane in the Detail Inspector.
        self.core.nodes.append(
            Node(
                role="context",
                content="Included: test_degenerate.py",
                node_type="context",
                conversation_id=self.core.conversation_id,
                meta={
                    "source_path": "test_degenerate.py",
                    "prompt": "",
                    "raw_content": "# This is the raw content of a degenerate context node.\n"
                                   "# It has no prompt and no distinct output.\n"
                                   "# The Detail Inspector should show a SINGLE pane.\n"
                                   "print('hello world')\n",
                    "output": "# This is the raw content of a degenerate context node.\n"
                              "# It has no prompt and no distinct output.\n"
                              "# The Detail Inspector should show a SINGLE pane.\n"
                              "print('hello world')\n",
                },
            )
        )

        # 4. RICH context node — has prompt, raw_content, and DISTINCT output
        #    This should render as the full 3-split view.
        self.core.nodes.append(
            Node(
                role="context",
                content="Included: test_rich.py",
                node_type="context",
                conversation_id=self.core.conversation_id,
                meta={
                    "source_path": "test_rich.py",
                    "prompt": "Summarize the following Python file in two sentences.",
                    "raw_content": "# A very long Python module\n"
                                   "import os\n"
                                   "import sys\n"
                                   "\n"
                                   "def main():\n"
                                   "    print('Starting application...')\n"
                                   "    sys.exit(0)\n",
                    "output": "This module imports os and sys, then defines a main() "
                              "function that prints a startup message and exits cleanly.",
                },
            )
        )

        # 5. Assistant response
        self.core.nodes.append(
            Node(
                role="assistant",
                content="Here are the summaries you requested!",
                conversation_id=self.core.conversation_id,
            )
        )

        # Mount widgets into the MessageList
        asyncio.create_task(self._mount_fake_nodes())

    async def _mount_fake_nodes(self) -> None:
        message_list = self.query_one(MessageList)
        for node in self.core.nodes:
            await message_list.add_node(node)
        message_list.update_weights(self.core.token_usage())
        self._update_header()
        # Lock detail inspector to the last node
        self.query_one("#detail-inspector", DetailInspector).show_node(self.core.nodes[-1])


if __name__ == "__main__":
    app = TestApp()
    app.run()
