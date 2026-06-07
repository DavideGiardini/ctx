from textual.binding import Binding
from textual.message import Message
from textual.widgets import Input

from ctx.core.log import logger


class InputBar(Input):
    DEFAULT_CSS = ""


    BINDINGS = [
        Binding("up", "prev_command", "Previous Command", show=False),
        Binding("down", "next_command", "Next Command", show=False),
    ]

    COMMANDS = [
        "/model",
        "/new",
        "/resume",
    ]

    COMMANDS_WITH_ARGS = {"/model"}

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class CommandNavigated(Message):
        def __init__(self, direction: int) -> None:
            super().__init__()
            self.direction = direction

    class CommandSelected(Message):
        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    def __init__(self) -> None:
        super().__init__()
        self._selected_command = 0

    async def action_submit(self) -> None:
        text = self.value
        logger.info("InputBar.action_submit called | text=%r", text)
        if text.startswith("/"):
            for cmd in self.COMMANDS:
                if cmd.startswith(text):
                    if cmd in self.COMMANDS_WITH_ARGS:
                        self.value = cmd + " "
                        self.cursor_position = len(self.value)
                        self.post_message(self.CommandSelected(cmd))
                        return
                    self.value = ""
                    self.post_message(self.Submitted(cmd))
                    return
        self.value = ""
        self.post_message(self.Submitted(text))

    def action_prev_command(self) -> None:
        self._cycle_command(-1)

    def action_next_command(self) -> None:
        self._cycle_command(1)

    def _cycle_command(self, direction: int) -> None:
        if not self.value.startswith("/"):
            return
        self._selected_command = (self._selected_command + direction) % len(self.COMMANDS)
        self.post_message(self.CommandNavigated(direction))