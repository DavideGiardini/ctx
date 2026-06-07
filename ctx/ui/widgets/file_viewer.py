"""File viewer widget and screen for viewing context files."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static, TextArea

from ctx.core.workspace import get_context_dir


class ReadOnlyTextArea(TextArea, inherit_bindings=False):
    """TextArea that lets ctrl+v bubble up to the parent."""

    BINDINGS = [
        binding for binding in TextArea.BINDINGS if binding.key not in ("ctrl+v", "ctrl+c")  # type: ignore[union-attr]
    ]


class FileViewer(Vertical):
    """Widget that displays a text file in a read-only TextArea.

    Shows a bottom status bar with the file path and close hints.
    """

    DEFAULT_CSS = """
    FileViewer {
        width: 1fr;
        height: 1fr;
        border: solid $surface;
    }
    FileViewer:focus {
        border: solid $primary;
    }
    FileViewer TextArea {
        height: 1fr;
        width: 1fr;
    }
    FileViewer .status-bar {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(
        self, file_path: str | None = None,
        close_hint: str = "ctrl+v to close  —  tab to switch focus",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._file_path: str | None = file_path
        self._close_hint: str = close_hint
        self._text_area: TextArea | None = None

    def compose(self) -> ComposeResult:
        text_area = ReadOnlyTextArea(read_only=True, classes="content")
        self._text_area = text_area
        yield text_area
        yield Static("", classes="status-bar")

    def on_mount(self) -> None:
        if self._file_path:
            self.load_file(self._file_path)

    def load_file(self, file_path: str) -> None:
        """Load a context file into the viewer.

        If the file doesn't exist, display a placeholder.
        """
        self._file_path = file_path
        context_dir = get_context_dir()
        target = context_dir / file_path

        try:
            text = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = f"[File not found: {file_path}]"
        except OSError:
            text = f"[Could not read file: {file_path}]"

        if self._text_area is not None:
            self._text_area.text = text
            self._text_area.focus()

        status = self.query_one(".status-bar", Static)
        status.update(f"{file_path}  —  {self._close_hint}")

    def focus(self, scroll_visible: bool = True) -> "FileViewer":
        """Delegate focus to the TextArea."""
        if self._text_area is not None:
            self._text_area.focus(scroll_visible=scroll_visible)
        else:
            super().focus(scroll_visible=scroll_visible)
        return self

    def clear(self) -> None:
        """Clear the viewer and status bar."""
        self._file_path = None
        if self._text_area is not None:
            self._text_area.text = ""
        status = self.query_one(".status-bar", Static)
        status.update("")


class FileViewerScreen(Screen[None]):
    """Full-screen file viewer."""

    BINDINGS = [
        Binding("q", "pop_screen", "Close"),
        Binding("escape", "pop_screen", "Close"),
    ]

    def action_pop_screen(self) -> None:
        self.app.pop_screen()

    def __init__(self, file_path: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._file_path = file_path

    def compose(self) -> ComposeResult:
        yield FileViewer(file_path=self._file_path, close_hint="q to close")

    def on_mount(self) -> None:
        file_viewer = self.query_one(FileViewer)
        file_viewer.focus()
