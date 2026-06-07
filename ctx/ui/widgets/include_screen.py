"""Modal screen for selecting context files to include."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, SelectionList, Static
from textual.containers import Vertical

from ctx.core.workspace import list_context_files


class FilterInput(Input):
    """Input that redirects Down-arrow focus to the selection list."""

    def __init__(self, selection_list_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._selection_list_id = selection_list_id

    def _on_key(self, event: Key) -> None:
        if event.key == "down":
            sl = self.screen.query_one(f"#{self._selection_list_id}", SelectionList)
            if sl.option_count:
                sl.focus()
                if sl.highlighted is None:
                    sl.highlighted = 0
            event.stop()
            return
        super()._on_key(event)


class IncludeSelectionList(SelectionList):
    """SelectionList that returns focus to the input on Up-arrow at top."""

    def _on_key(self, event: Key) -> None:
        if event.key == "up" and self.highlighted == 0:
            self.screen.query_one("#include-filter", Input).focus()
            event.stop()
            return
        super()._on_key(event)


class IncludeScreen(ModalScreen[list[str] | None]):
    BINDINGS = [
        Binding("escape", "dismiss_none", "Cancel", show=False),
        Binding("enter", "confirm", "Confirm", show=False, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._all_files: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="include-container"):
            yield Static("Select files to include:", id="include-title")
            yield FilterInput(
                selection_list_id="include-list",
                placeholder="Filter...",
                id="include-filter",
            )
            yield IncludeSelectionList(id="include-list")
            yield Static(
                "↑↓ navigate  Space toggle  Enter confirm  Escape cancel",
                id="include-hint",
            )

    def on_mount(self) -> None:
        self._all_files = sorted(list_context_files())
        sl = self.query_one("#include-list", IncludeSelectionList)
        if not self._all_files:
            self.query_one("#include-title", Static).update("No files in .ctx/context/")
            self.query_one("#include-hint", Static).update(
                "Add text files to .ctx/context/"
            )
            return
        for f in self._all_files:
            sl.add_option((f, f))
        self.query_one("#include-filter", FilterInput).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "include-filter":
            return
        query = event.value.lower()
        sl = self.query_one("#include-list", IncludeSelectionList)
        sl.clear_options()
        for f in self._all_files:
            if query in f.lower():
                sl.add_option((f, f))
        if sl.option_count:
            sl.highlighted = 0

    def action_confirm(self) -> None:
        selected = list(self.query_one("#include-list", IncludeSelectionList).selected)
        self.dismiss(selected if selected else None)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)
