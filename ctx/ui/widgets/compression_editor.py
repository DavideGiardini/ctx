"""Left-pane compression *draft editor* (ADR-0016 Q4).

A 2-split editor shown in place of the ``DetailInspector`` while the user drafts
a compression node ``K``:

* Top — an editable prompt ``TextArea``, prefilled with the default compression
  prompt (the instruction handed to the AI drafter).
* Bottom — an editable output ``TextArea``, empty on open, holding the summary
  that becomes ``K``'s content.

There is deliberately **no Center split** (Q4): the originals being compressed
stay highlighted on the *right* pane as the selected range, so the editor never
needs to re-show them. Drafting (``Ctrl+D``) streams an AI summary into the
Bottom split via :meth:`set_output`; committing (``Ctrl+S``) folds the range.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static, TextArea


class CompressionEditor(Container):
    DEFAULT_CSS = """
    CompressionEditor {
        display: none;
        width: 1fr;
        height: 1fr;
        border-right: solid $surface;
    }
    CompressionEditor #compress-prompt { height: 1fr; }
    CompressionEditor #compress-output { height: 2fr; }
    CompressionEditor .split-label {
        color: $text-muted;
        text-style: italic;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Prompt", classes="split-label")
        yield TextArea(id="compress-prompt")
        yield Static("Summary", id="compress-output-label", classes="split-label")
        yield TextArea(id="compress-output")

    # --- interface -------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """Whether the editor is currently shown (occupying the left pane)."""
        return self.display

    def open(self, prompt: str, output_label: str = "Summary") -> None:
        """Show the editor: prefill the prompt split, clear the output split.

        No auto-stream (Q4) — opening only seeds the default prompt and an empty
        output; drafting is an explicit later action. ``output_label`` names the
        bottom split for the current use: ``"Summary"`` for a compression draft,
        ``"Output"`` for an import extract (the editor is shared by both flows).
        """
        self.query_one("#compress-prompt", TextArea).text = prompt
        self.query_one("#compress-output", TextArea).text = ""
        self.query_one("#compress-output-label", Static).update(output_label)
        self.display = True

    def close(self) -> None:
        """Hide the editor. Cancelling is free — it mutates no conversation
        state (Q4); the caller restores the inspector and keeps the selection."""
        self.display = False

    @property
    def prompt(self) -> str:
        """The current (possibly user-edited) prompt text."""
        return self.query_one("#compress-prompt", TextArea).text

    @property
    def output(self) -> str:
        """The current (possibly user-edited) summary/output text."""
        return self.query_one("#compress-output", TextArea).text

    def set_output(self, text: str) -> None:
        """Replace the Bottom summary split's text.

        A draft (``Ctrl+D``) streams into here by re-setting the accumulated
        text; re-drafting overwrites rather than appends (Q4)."""
        self.query_one("#compress-output", TextArea).text = text

    def focus_next_split(self) -> None:
        """Cycle focus between the two editable splits (prompt ↔ summary).

        The 2-split editor has no Center, so ``Tab`` just toggles between the
        prompt and summary ``TextArea``s — giving a keyboard-only path to the
        summary the user commits (the app routes its ``Tab`` here while open)."""
        prompt = self.query_one("#compress-prompt", TextArea)
        output = self.query_one("#compress-output", TextArea)
        (prompt if output.has_focus else output).focus()
