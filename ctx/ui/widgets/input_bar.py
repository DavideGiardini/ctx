"""The prompt line — a borderless, soft-wrapping box that grows with the message.

A ``TextArea`` rather than an ``Input`` because ``Input`` is single-line by
construction: it scrolls horizontally, so anything past the pane width slides out
of sight as you type it. ``TextArea`` wraps instead, and with ``height: auto`` (see
``app.css``) the box grows downward line by line until it hits its cap.

Enter keeps meaning *submit*, which means the newline ``TextArea`` natively binds
it to has to move somewhere else: ``shift+enter`` where the terminal reports it
(terminals speaking the Kitty keyboard protocol) and ``alt+enter``, which every
terminal sends.
"""

from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widgets import TextArea

from ctx.core.log import logger


class InputBar(TextArea):
    BINDINGS = [
        Binding("up", "prev_command", "Previous Command", show=False),
        Binding("down", "next_command", "Next Command", show=False),
    ]

    COMMANDS = [
        "/model",
        "/new",
        "/resume",
        "/include",
        "/import",
    ]

    COMMANDS_WITH_ARGS = {"/model"}

    NEWLINE_KEYS = frozenset({"shift+enter", "alt+enter"})

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

    @property
    def menu_active(self) -> bool:
        """Whether the typed text is steering the command menu: a bare
        ``/``-prefixed word, no argument and no line break yet.

        The single definition of "the menu is live" — it decides both whether the
        popup shows (the app reads this) and whether Up/Down steer the menu or
        just move the cursor through the message being written.
        """
        text = self.text
        return text.startswith("/") and " " not in text and "\n" not in text

    # AIDEV-NOTE: Enter must be intercepted here, not by a Binding —
    # TextArea._on_key swallows it into the document before bindings resolve.
    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            await self.action_submit()
            return
        if event.key in self.NEWLINE_KEYS:
            event.stop()
            event.prevent_default()
            self.insert("\n", maintain_selection_offset=False)
            return
        await super()._on_key(event)

    async def action_submit(self) -> None:
        text = self.text
        logger.info("InputBar.action_submit called | text=%r", text)
        if self.menu_active and any(c.startswith(text) for c in self.COMMANDS):
            # The suggestions popup is an active command selector whenever the
            # typed text is a prefix of some command. The highlighted entry —
            # which the user steers with the arrow keys and sees marked in the
            # popup — is authoritative, not the typed prefix.
            cmd = self.COMMANDS[self._selected_command]
            if cmd in self.COMMANDS_WITH_ARGS:
                self.text = cmd + " "
                self.move_cursor(self.document.end)
                self.post_message(self.CommandSelected(cmd))
                return
            self.text = ""
            self.post_message(self.Submitted(cmd))
            return
        # Deliberately no self.text = "" here: clearing is a consequence of the
        # app ACCEPTING the submission (review §Turn lifecycle). A submit refused
        # mid-stream keeps the typed text in place.
        self.post_message(self.Submitted(text))

    def action_prev_command(self) -> None:
        if not self._cycle_command(-1):
            self.action_cursor_up()

    def action_next_command(self) -> None:
        if not self._cycle_command(1):
            self.action_cursor_down()

    def _cycle_command(self, direction: int) -> bool:
        """Move the command menu's highlight; ``False`` when there is no live menu
        to steer, which is the caller's cue to let Up/Down do what they do in any
        text box — walk the wrapped lines of the message being typed."""
        if not self.menu_active:
            return False
        self._selected_command = (self._selected_command + direction) % len(self.COMMANDS)
        self.post_message(self.CommandNavigated(direction))
        return True
