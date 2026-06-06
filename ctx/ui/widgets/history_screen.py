from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import SelectionList
from textual.containers import Vertical

from ctx.core.storage import list_conversations


class HistoryScreen(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "dismiss_none", "Cancel", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._conversations = list_conversations()

    def compose(self) -> ComposeResult:
        with Vertical(id="history-container"):
            yield SelectionList(
                *[
                    (f"{c['title']}  ({c['updated_at'][:19]})", c['id'])
                    for c in self._conversations
                ],
                id="history-list",
            )

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        if event.selection_list.selected:
            conv_id = event.selection_list.selected[0]
            self.dismiss(conv_id)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)