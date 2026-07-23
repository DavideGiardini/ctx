"""Modal screens for choosing context files.

Two pickers, one per front door of the condense engine:

* :class:`IncludeScreen` — ``/include``'s **multi-select** picker (space toggles,
  Enter confirms the set); returns the list of chosen paths.
* :class:`ImportScreen` — ``/import``'s **single-select** picker (highlight a file
  and press Enter to choose it, no toggling); returns one path. Import condenses
  one file at a time, so the picker enforces that by construction rather than
  accepting many and warning.
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, SelectionList, Static
from textual.widgets.option_list import Option

from ctx.core.workspace import Workspace


class FilterInput(Input):
    """Input that redirects Down-arrow focus to the selection list."""

    def __init__(self, selection_list_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._selection_list_id = selection_list_id

    async def _on_key(self, event: Key) -> None:
        if event.key == "down":
            sl = self.screen.query_one(f"#{self._selection_list_id}", SelectionList)
            if sl.option_count:
                sl.focus()
                if sl.highlighted is None:
                    sl.highlighted = 0
            event.stop()
            return
        await super()._on_key(event)


class IncludeSelectionList(SelectionList):
    """SelectionList that returns focus to the input on Up-arrow at top."""

    async def _on_key(self, event: Key) -> None:
        if event.key == "up" and self.highlighted == 0:
            self.screen.query_one("#include-filter", Input).focus()
            event.stop()
            return
        await super()._on_key(event)


class IncludeScreen(ModalScreen[list[str] | None]):
    BINDINGS = [
        Binding("escape", "dismiss_none", "Cancel", show=False),
        Binding("enter", "confirm", "Confirm", show=False, priority=True),
    ]

    def __init__(self, workspace: Workspace) -> None:
        super().__init__()
        self._workspace = workspace
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
        self._all_files = sorted(self._workspace.list_files())
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


class ImportFilterInput(Input):
    """Filter input that redirects Down-arrow focus to the option list."""

    def __init__(self, option_list_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._option_list_id = option_list_id

    async def _on_key(self, event: Key) -> None:
        if event.key == "down":
            ol = self.screen.query_one(f"#{self._option_list_id}", OptionList)
            if ol.option_count:
                ol.focus()
                if ol.highlighted is None:
                    ol.highlighted = 0
            event.stop()
            return
        await super()._on_key(event)


class ImportOptionList(OptionList):
    """OptionList that returns focus to the filter on Up-arrow at the top."""

    async def _on_key(self, event: Key) -> None:
        if event.key == "up" and self.highlighted == 0:
            self.screen.query_one("#import-filter", Input).focus()
            event.stop()
            return
        await super()._on_key(event)


class ImportScreen(ModalScreen[str | None]):
    """Single-select context-file picker for ``/import``.

    Highlight a file (↑↓ or type in the filter) and press Enter to choose it —
    there is no space-toggle and no multi-select, because import takes exactly
    one file. Dismisses with the chosen path, or ``None`` on cancel / empty.
    """

    BINDINGS = [
        Binding("escape", "dismiss_none", "Cancel", show=False),
        Binding("enter", "confirm", "Confirm", show=False, priority=True),
    ]

    def __init__(self, workspace: Workspace) -> None:
        super().__init__()
        self._workspace = workspace
        self._all_files: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="import-container"):
            yield Static("Select a file to import:", id="import-title")
            yield ImportFilterInput(
                option_list_id="import-list",
                placeholder="Filter...",
                id="import-filter",
            )
            yield ImportOptionList(id="import-list")
            yield Static(
                "↑↓ navigate  Enter select  Escape cancel",
                id="import-hint",
            )

    def on_mount(self) -> None:
        self._all_files = sorted(self._workspace.list_files())
        ol = self.query_one("#import-list", ImportOptionList)
        if not self._all_files:
            self.query_one("#import-title", Static).update("No files in .ctx/context/")
            self.query_one("#import-hint", Static).update(
                "Add text files to .ctx/context/"
            )
            return
        for f in self._all_files:
            ol.add_option(Option(f, id=f))
        self.query_one("#import-filter", ImportFilterInput).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "import-filter":
            return
        query = event.value.lower()
        ol = self.query_one("#import-list", ImportOptionList)
        ol.clear_options()
        for f in self._all_files:
            if query in f.lower():
                ol.add_option(Option(f, id=f))
        if ol.option_count:
            ol.highlighted = 0

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        # A mouse click selects an option directly (keyboard Enter is handled by
        # the priority ``action_confirm`` binding, which consumes the key first).
        self.dismiss(event.option_id)

    def action_confirm(self) -> None:
        ol = self.query_one("#import-list", ImportOptionList)
        if ol.highlighted is None:
            self.dismiss(None)
            return
        self.dismiss(ol.get_option_at_index(ol.highlighted).id)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)
