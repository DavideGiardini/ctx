from textual.containers import Vertical, VerticalScroll
from textual.widgets import Markdown, Static

from ctx.models.nodes import Node


class DetailInspector(Vertical):
    """Left Pane widget that shows full content for the selected / locked node.

    * Standard nodes (user / assistant / system / application) → single Markdown.
    * Context nodes → 3-split vertical layout (Prompt / Content / Output).
    * Full-view mode (1/2/3 keys) → maximizes one split to fill the pane.
    """

    DEFAULT_CSS = ""

    def __init__(self, **kwargs) -> None:
        self._current_node_id: str | None = None
        self._current_node: Node | None = None
        self._view_mode: str = "split"  # "split" or "full"
        self._full_split: str | None = None  # "prompt", "content", or "output"
        super().__init__(**kwargs)

    def show_node(self, node: Node | None) -> None:
        """Render the given node, re-mounting only when the node changes."""
        if node is None:
            self._clear()
            return

        if node.id != self._current_node_id:
            # Node changed: always reset to split view
            self._current_node_id = node.id
            self._current_node = node
            self._view_mode = "split"
            self._full_split = None
            self._mount_for(node)
        else:
            self._update_for(node)

    def _clear(self) -> None:
        self._current_node_id = None
        self._current_node = None
        self._view_mode = "split"
        self._full_split = None
        for child in list(self.children):
            child.remove()

    def _mount_for(self, node: Node) -> None:
        """Fully rebuild children for *node*."""
        for child in list(self.children):
            child.remove()

        if node.node_type == "context":
            if self._view_mode == "full" and self._full_split:
                self._mount_full_view(node, self._full_split)
            else:
                self._mount_context_splits(node)
        else:
            self._mount_standard(node)

    def _update_for(self, node: Node) -> None:
        """Fast path: just refresh text content without remounting."""
        if node.node_type == "context":
            if self._view_mode == "full" and self._full_split:
                try:
                    scroll = self.query_one(".full-view-scroll", VerticalScroll)
                    static = scroll.query_one(".detail-content", Static)
                    static.update(self._get_split_text(node, self._full_split) or "")
                except Exception:
                    pass
            else:
                self._update_context_splits(node)
        else:
            try:
                md = self.query_one(".detail-content", Markdown)
                md.update(node.content or "")
            except Exception:
                pass

    # ── Standard view ──

    def _mount_standard(self, node: Node) -> None:
        scroll = VerticalScroll(Markdown(node.content or "", classes="detail-content"))
        self.mount(scroll)

    def _mount_standard_raw(self, node: Node) -> None:
        """Single-pane fallback for degenerate context nodes (no prompt / no distinct output)."""
        scroll = VerticalScroll(Static(node.raw_content or "", classes="detail-content"))
        self.mount(scroll)

    # ── 3-split context view ──

    def _mount_context_splits(self, node: Node) -> None:
        has_prompt = bool(node.prompt)
        has_raw = bool(node.raw_content)
        has_output = bool(node.output)

        # Only mount splits that have data
        if has_prompt:
            prompt_scroll = VerticalScroll(
                Static(node.prompt or "", classes="detail-content"),
                classes="split-prompt",
            )
            self.mount(prompt_scroll)

        if has_raw:
            content_scroll = VerticalScroll(
                Static(node.raw_content or "", classes="detail-content"),
                classes="split-content",
            )
            self.mount(content_scroll)

        if has_output:
            output_scroll = VerticalScroll(
                Static(node.output or "", classes="detail-content"),
                classes="split-output",
            )
            self.mount(output_scroll)

        # Edge case: nothing to show
        if not (has_prompt or has_raw or has_output):
            self.mount(Static("[empty context node]", classes="detail-content"))

    def _update_context_splits(self, node: Node) -> None:
        """Refresh text in existing 3-split children."""
        mapping = {
            "split-prompt": node.prompt,
            "split-content": node.raw_content,
            "split-output": node.output,
        }
        for split_class, text in mapping.items():
            try:
                scroll = self.query_one(f".{split_class}", VerticalScroll)
                static = scroll.query_one(".detail-content", Static)
                static.update(text or "")
            except Exception:
                pass

    # ── Full-view mode (1/2/3 keys) ──

    def _get_split_text(self, node: Node, split: str) -> str:
        if split == "prompt":
            return node.prompt
        if split == "content":
            return node.raw_content
        if split == "output":
            return node.output
        return ""

    def _get_split_label(self, split: str) -> str:
        labels = {
            "prompt": "[Prompt]",
            "content": "[Content]",
            "output": "[Output]",
        }
        return labels.get(split, "")

    def _mount_full_view(self, node: Node, split: str) -> None:
        """Mount a single maximized pane for the chosen split, with a header label."""
        text = self._get_split_text(node, split) or ""
        label = self._get_split_label(split)

        header = Static(label, classes="full-view-header")
        scroll = VerticalScroll(
            Static(text, classes="detail-content"),
            classes="full-view-scroll",
        )
        self.mount(header, scroll)

    def enter_full_view(self, index: int) -> None:
        """Switch to full-view mode for the Nth split (1=prompt, 2=content, 3=output)."""
        mapping = {1: "prompt", 2: "content", 3: "output"}
        if index not in mapping:
            return
        if self._current_node is None or self._current_node.node_type != "context":
            return

        split = mapping[index]
        # Only enter full view if this split actually has data
        text = self._get_split_text(self._current_node, split)
        if not text:
            return

        self._view_mode = "full"
        self._full_split = split
        self._mount_for(self._current_node)

    def return_to_split_view(self) -> None:
        """Return from full-view to the 3-split layout."""
        if self._view_mode != "full":
            return
        self._view_mode = "split"
        self._full_split = None
        if self._current_node:
            self._mount_for(self._current_node)

    def is_full_view(self) -> bool:
        return self._view_mode == "full"

    @property
    def view_state(self) -> dict[str, str | None]:
        """The inspector's current view: which node, split/full mode, and focused split."""
        return {
            "node_id": self._current_node_id,
            "view_mode": self._view_mode,
            "full_split": self._full_split,
        }
