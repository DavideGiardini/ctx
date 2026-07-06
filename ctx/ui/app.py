import asyncio
import contextlib
from pathlib import Path

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Input, Static, TextArea
from textual.worker import Worker, WorkerState

from ctx.core import reconstruction, tokens
from ctx.core.config import get_config
from ctx.core.context import build_context
from ctx.core.conversation import ConversationCore
from ctx.core.log import logger
from ctx.core.provider import LiteLLMProvider, Provider
from ctx.core.storage import ConversationRepository, StoragePort
from ctx.core.workspace import Workspace
from ctx.models.nodes import Node
from ctx.ui.widgets.app_footer import AppFooter
from ctx.ui.widgets.app_header import AppHeader
from ctx.ui.widgets.compression_editor import CompressionEditor
from ctx.ui.widgets.detail_inspector import (
    _SPLIT_VIEW_TYPES,
    DetailInspector,
    NodeView,
)
from ctx.ui.widgets.diff_view import DiffView
from ctx.ui.widgets.history_screen import HistoryScreen
from ctx.ui.widgets.include_screen import IncludeScreen
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList, MessageWidget

# Config key per node role for truncation lookups ("user" maps to "human").
_TRUNCATION_KEY = {
    "user": "human",
    "assistant": "assistant",
    "context": "context",
    "system": "system",
}


class ChatApp(App):
    CSS_PATH = [
        "app.css",
        "widgets/message_list.css",
        "widgets/input_bar.css",
    ]

    BINDINGS = [
        Binding("ctrl+c", "cancel_stream", "Cancel", show=False),
        Binding("escape", "escape", "Toggle mode", show=False),
        Binding("i", "enter_insert", "Insert Mode", show=False),
        Binding("v", "anchor_range", "Select range", show=False),
        Binding("c", "compress", "Compress", show=False),
        Binding("x", "expand", "Expand", show=False),
        # ``ctrl+d`` must be a priority binding: the focused prompt/summary
        # ``TextArea`` binds it to delete_right, so the app has to intercept it
        # first to drive the draft (the action is inert unless the editor is open).
        Binding("ctrl+d", "draft_compression", "Draft", show=False, priority=True),
        Binding("ctrl+s", "commit_compression", "Commit", show=False),
        Binding("ctrl+o", "pop_deep_dive", "Back out", show=False),
        Binding("up", "up", "Up", show=False),
        Binding("down", "down", "Down", show=False),
        Binding("enter", "detail_enter", "Select split", show=False),
        Binding("home", "jump_home", "Jump to top", show=False),
        Binding("1", "maximize_split('prompt')", "Prompt split", show=False),
        Binding("2", "maximize_split('content')", "Content split", show=False),
        Binding("3", "maximize_split('output')", "Output split", show=False),
        Binding("tab", "switch_focus", "Switch pane", show=False, priority=True),
    ]

    def __init__(
        self,
        *,
        provider: Provider | None = None,
        workspace: Workspace | None = None,
        storage: StoragePort | None = None,
    ) -> None:
        super().__init__()
        # Injectable seams: default to the real adapters so production
        # `ChatApp()` is unchanged, while tests/harness can pass a
        # TestProvider and a temp-dir Workspace.
        self._workspace = workspace or Workspace(Path.cwd())
        self._repo = storage or ConversationRepository(str(self._workspace.db_path))
        self.core = ConversationCore(
            self._repo, provider or LiteLLMProvider(), workspace=self._workspace
        )
        self._stream_worker: Worker | None = None
        # The in-flight draft worker (``Ctrl+D``) and the prompt of the last
        # draft that actually ran. ``""`` means no draft ran → a manual commit
        # (Q4); ``Ctrl+S`` records this prompt on the committed K.
        self._draft_worker: Worker | None = None
        self._last_drafted_prompt: str = ""
        self.mode = "insert"
        self._selected_node_id: str | None = None
        # Anchor of a vim-style range selection (Edit mode). ``None`` when no
        # range is active; while set, up/down extend the contiguous highlight
        # between it and the cursor (``_selected_node_id``). See ADR-0016 Q5.
        self._range_anchor_id: str | None = None
        # Node-set signature captured the last time a streamed turn produced a
        # fresh provider ``usage`` anchor. The header gauge is exact only while
        # the conversation still matches it; any later change makes it stale
        # (``~``). ``None`` until the first anchored turn.
        self._gauge_anchor: tuple | None = None
        # Memo for the per-refresh drift pass (task 32). ``_node_drift`` re-folds
        # the whole graph per assistant node (O(n²)) and runs on every
        # ``_refresh_token_ui`` *and* every ``describe_state()``; cache the
        # parallel result keyed on a cheap signature that changes exactly when
        # the drift inputs do (``_drift_signature``). ``None`` until first
        # computed. Auto-invalidating — no manual reset needed.
        self._drift_cache: tuple[tuple, list[bool]] | None = None
        # Deep-dive browse stack (Q7/Q8, task 12). Each frame is a folded K's
        # originals rendered in place of the live conversation. Empty = live
        # view. Built as a stack so it is nesting-ready (3a depth stays 1).
        # Ephemeral — never persisted.
        self._deep_dive_stack: list[dict] = []
        # One-key chord buffer: ``g`` arms it, the next key completes/cancels
        # (``g d`` opens a deep-dive or a context diff). ``None`` when disarmed.
        self._pending_chord: str | None = None
        # Context-diff view state (task 20), shared "navigation family" with the
        # deep-dive stack but mutually exclusive with it: a diff is opened by
        # ``g d`` on a *drifted assistant* turn (a K still deep-dives). ``None``
        # = no diff open. Ephemeral — never persisted.
        self._diff_view: dict | None = None
        # Most-recent transient UI hint (task 42). Surfaced as a toast via
        # ``notify`` and exposed on ``describe_state`` so headless QA can observe
        # it; unlike a durable breadcrumb it is NOT a graph node. ``None`` = none
        # shown yet; reset on a conversation switch.
        self._last_hint: str | None = None
        logger.info("app initialized | default_model=%s", self.core.model)

    def compose(self) -> ComposeResult:
        yield AppHeader(id="app-header")
        with Horizontal(id="body"):
            yield DetailInspector(id="detail")
            yield CompressionEditor(id="compression-editor")
            with Vertical(id="conversation"):
                yield MessageList(id="messages")
                yield DiffView(id="diff-view")
                # Suggestions + input share one docked container so they stack
                # in normal flow (docking both directly would overlap them).
                with Container(id="input-area"):
                    yield Static("", id="command-suggestions")
                    yield InputBar()
        yield AppFooter()

    def on_mount(self) -> None:
        self.core.setup()
        self.query_one(InputBar).focus()
        self.query_one(AppHeader).set_title(self.core.conversation_title)
        footer = self.query_one(AppFooter)
        footer.set_mode("insert")
        footer.set_model(self.core.model)
        self._lock_inspector_to_last()

    # --- command suggestions overlay ------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input is not self.query_one(InputBar):
            return
        suggestions = self.query_one("#command-suggestions", Static)
        if not event.value.startswith("/"):
            suggestions.display = False
            return
        if " " in event.value:
            suggestions.display = False
            return
        suggestions.display = True
        input_bar = self.query_one(InputBar)
        for i, cmd in enumerate(InputBar.COMMANDS):
            if cmd.startswith(event.value):
                input_bar._selected_command = i
                break
        else:
            if event.value == "/":
                input_bar._selected_command = 0
        self._update_suggestions()

    def _update_suggestions(self) -> None:
        input_bar = self.query_one(InputBar)
        suggestions = self.query_one("#command-suggestions", Static)
        selected = input_bar._selected_command
        lines = ["Available commands:"]
        for i, cmd in enumerate(InputBar.COMMANDS):
            prefix = "▸" if i == selected else " "
            lines.append(f"{prefix} [bold]{cmd}[/bold]")
        suggestions.update("\n".join(lines))

    def on_input_bar_command_navigated(self, event: InputBar.CommandNavigated) -> None:
        self._update_suggestions()

    def on_input_bar_command_selected(self, event: InputBar.CommandSelected) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#command-suggestions", Static).display = False

    # --- modes ----------------------------------------------------------

    async def action_escape(self) -> None:
        try:
            suggestions = self.query_one("#command-suggestions", Static)
            if suggestions.display:
                suggestions.display = False
                return
        except Exception:
            pass
        # The draft editor cancels for free: Esc closes it, restores the
        # inspector, and keeps the selection (Q4). No graph mutation. While a
        # draft is streaming the first Esc cancels the worker but keeps the
        # editor open; a second Esc then closes it (task 9).
        if self.query_one(CompressionEditor).is_open:
            if self._draft_worker is not None and not self._draft_worker.is_finished:
                self._draft_worker.cancel()
                return
            self._close_compression_editor()
            return
        # Inside the detail pane, Esc backs out one level (Maximized→Browse→right pane)
        # before it falls through to the Insert/Edit toggle.
        if self.mode == "edit" and self._focus_in_detail():
            inspector = self.query_one(DetailInspector)
            if inspector.pane_mode != "none":
                if inspector.back() == "exit":
                    self.query_one(MessageList).focus()
                self._sync_footer()
                return
        # An active range selection swallows the first Esc (clear the anchor but
        # stay in Edit); a second Esc then toggles the mode as usual (Q5).
        if self.mode == "edit" and self._range_anchor_id is not None:
            self._clear_range()
            return
        # While the diff view is open, Esc backs out of it one level (like
        # Ctrl+o: drill → overview → live) rather than toggling the mode
        # (task 20/21, same family as deep-dive).
        if self.mode == "edit" and self._diff_view is not None:
            await self.action_pop_deep_dive()
            return
        # While deep-diving, Esc backs out one level (like Ctrl+o) rather than
        # toggling the mode, keeping the view and mode consistent (task 12).
        if self.mode == "edit" and self._deep_dive_stack:
            await self.action_pop_deep_dive()
            return
        self._set_mode("edit" if self.mode == "insert" else "insert")

    async def action_enter_insert(self) -> None:
        # Vim-style: `i` returns to Insert mode from anywhere in Edit mode
        # (right pane or inside the detail pane). Switching to Insert re-locks
        # the inspector to the last node, resetting any detail sub-state. `i`
        # also exits the *whole* deep-dive stack (task 12): the live list is
        # restored before dropping into Insert (appends go to the active tip;
        # deep-dive never moved it).
        if self.mode == "edit":
            if self._diff_view is not None:
                await self._close_diff()
            if self._deep_dive_stack:
                self._deep_dive_stack.clear()
                await self._rebuild_message_list()
                self.query_one(AppFooter).set_deep_dive(False)
                self._refresh_token_ui()
            self._set_mode("insert")

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        # Any mode switch leaves the detail pane's navigation sub-state behind.
        # (Reset explicitly: re-showing the same node would be a no-op and skip
        # the reactive watcher that normally resets it.)
        self.query_one(DetailInspector).exit_pane()
        self.query_one(AppFooter).set_mode(mode)
        if mode == "insert":
            self._clear_selection()
            self.query_one(InputBar).focus()
            self._lock_inspector_to_last()
            logger.info("entered insert mode")
        else:
            self.query_one(InputBar).blur()
            self.query_one(MessageList).focus()
            target = self.core.nodes[-1].id if self.core.nodes else None
            self._select_message(target)
            logger.info("entered edit mode")

    # --- selection + inspector ------------------------------------------

    def _node_view(self, node: Node) -> NodeView:
        if node.node_type == "compression":
            # Committed-K 3-split (task 10): Prompt = the drafting instruction
            # (hidden when empty — a manual K), Originals = the folded children in
            # recorded order (they are off-view, reached via the core accessor),
            # Summary = K's own content.
            children = self.core.folded_children(node.id)
            originals = "\n\n".join(f"**{c.role}**\n\n{c.content}" for c in children)
            return NodeView(
                node_id=node.id,
                role=node.role,
                node_type=node.node_type,
                content=originals,
                content_nodes=tuple(children),
                prompt=node.meta.get("prompt", ""),
                output=node.content,
            )
        return NodeView(
            node_id=node.id,
            role=node.role,
            node_type=node.node_type,
            content=node.content,
            prompt=node.meta.get("prompt", ""),
            output=node.meta.get("output", ""),
            source_path=node.meta.get("source_path"),
        )

    def _lock_inspector_to_last(self) -> None:
        inspector = self.query_one(DetailInspector)
        last = self.core.nodes[-1] if self.core.nodes else None
        inspector.show(self._node_view(last) if last else None)

    def _select_message(self, node_id: str | None) -> None:
        message_list = self.query_one(MessageList)
        if self._selected_node_id:
            try:
                prev = message_list.query_one(f"#msg-{self._selected_node_id}", MessageWidget)
                prev.set_selected(False)
            except Exception:
                pass
        self._selected_node_id = node_id
        if node_id is None:
            self.query_one(DetailInspector).show(None)
            self._sync_footer()
            return
        try:
            widget = message_list.query_one(f"#msg-{node_id}", MessageWidget)
            widget.set_selected(True)
            widget.scroll_visible()
        except Exception:
            pass
        node = self._get_selected_node()
        self.query_one(DetailInspector).show(self._node_view(node) if node else None)
        self._sync_footer()

    def _clear_selection(self) -> None:
        if self._selected_node_id:
            try:
                prev = self.query_one(MessageList).query_one(
                    f"#msg-{self._selected_node_id}", MessageWidget
                )
                prev.set_selected(False)
            except Exception:
                pass
        self._selected_node_id = None
        self._clear_range()
        self._sync_footer()

    def _in_full_screen_inspection(self) -> bool:
        """True while a full-screen read-only inspection view is up — a deep-dive
        or the context-diff (task 27).

        Both replace the live message list with a hidden-list frame, so
        selection- and mutation-driving Edit-mode keys (``v``/``c``/``x``) must
        be inert: otherwise they'd anchor an invisible range on the hidden list
        or mutate the graph under the open view (the 13-series illegal-transition
        family, one layer up)."""
        return bool(self._deep_dive_stack) or self._diff_view is not None

    def action_anchor_range(self) -> None:
        """`v` in Edit mode: anchor a range selection at the current node.

        A fresh press re-anchors at the cursor (range-of-one). Up/Down then
        extend the contiguous highlight between the anchor and the cursor.
        """
        if self.mode != "edit" or self._focus_in_detail():
            return
        if self._in_full_screen_inspection():  # read-only (tasks 12, 27)
            return
        if self._selected_node_id is None:
            return
        self._range_anchor_id = self._selected_node_id
        self._apply_range_selection()

    def _range_ids(self) -> list[str]:
        """The ids of the currently selected range, in view order (empty when
        no anchor is set or the anchor has left the view)."""
        if self._range_anchor_id is None:
            return []
        ids = [n.id for n in self.core.nodes]
        try:
            anchor = ids.index(self._range_anchor_id)
        except ValueError:
            return []
        cursor_id = self._selected_node_id or self._range_anchor_id
        cursor = ids.index(cursor_id) if cursor_id in ids else anchor
        lo, hi = sorted((anchor, cursor))
        return ids[lo : hi + 1]

    def _apply_range_selection(self) -> None:
        self.query_one(MessageList).set_range(set(self._range_ids()))

    def _clear_range(self) -> None:
        if self._range_anchor_id is None:
            return
        self._range_anchor_id = None
        with contextlib.suppress(Exception):
            self.query_one(MessageList).set_range(set())

    # --- deep-dive (browse a compression's folded originals) ------------

    def _visible_nodes(self) -> list[Node]:
        """The node list currently rendered in the message pane.

        Live conversation (``core.nodes``) normally; while a deep-dive is
        active, the top frame's folded originals instead. The single seam every
        view-facing method (rendering, cursor navigation, snapshot) reads so the
        deep-dive replacement stays consistent across all of them (Q8)."""
        if self._deep_dive_stack:
            frame_nodes: list[Node] = self._deep_dive_stack[-1]["nodes"]
            return frame_nodes
        return self.core.nodes

    async def on_key(self, event: events.Key) -> None:
        """Minimal ``g``-prefixed key-chord buffer (task 12).

        Only active while the message list holds focus in Edit mode: ``g`` arms
        the chord, a following ``d`` drills into the selected node — a deep-dive
        on a compression ``K``, or the context-diff view on a *drifted assistant*
        turn (one navigation family, Q12) — and any other key cancels it (falling
        through to normal handling). Keys outside that context disarm the chord
        and are left untouched."""
        if self.mode != "edit" or self._focus_target() != "messages":
            self._pending_chord = None
            return
        if self._pending_chord == "g":
            self._pending_chord = None
            if event.key == "d":
                event.stop()
                await self._drill_selected()
            return
        if event.key == "g":
            self._pending_chord = "g"
            event.stop()

    async def _drill_selected(self) -> None:
        """``g d`` dispatch: deep-dive a K, else diff a drifted assistant turn.

        A compression node opens its folded originals (task 12); an assistant
        turn whose generation context has drifted from now opens the context
        diff (task 20). Any other selection is a no-op."""
        node = self._get_selected_node()
        if node is None:
            return
        if node.node_type == "compression":
            await self._enter_deep_dive()
        elif self._turn_has_drift(node, self.core.all_nodes()):
            # Diff and deep-dive are mutually exclusive (see _diff_view, task 30):
            # a folded *frame* assistant turn can drift, but opening its diff here
            # would nest a diff inside the dive. Inert, like the read-only v/c/x
            # gates (task 27) — exit the dive (Ctrl+o) to reach the diff.
            if self._deep_dive_stack:
                return
            await self._enter_diff(node)

    async def _enter_deep_dive(self) -> None:
        """Push a deep-dive frame for the selected K and render its originals.

        No-op unless a compression node with folded children is selected. The
        breadcrumb gains one entry ("Chat › K…"); the cursor lands on the first
        child."""
        node = self._get_selected_node()
        if node is None or node.node_type != "compression":
            return
        children = self.core.folded_children(node.id)
        if not children:
            return
        # A range selection can't survive the view swap: dive widgets render the
        # folded frame, never the range highlight (`_range_ids` reads core.nodes),
        # so a lingering anchor would silently swallow the first Esc (13h #1).
        self._clear_range()
        self._deep_dive_stack.append(
            {"k_id": node.id, "label": f"K…{node.id[-4:]}", "nodes": list(children)}
        )
        await self._refresh_deep_dive_view(children[0].id)

    async def action_pop_deep_dive(self) -> None:
        """``Ctrl+o``: pop one deep-dive level (top pop restores the live view).

        Inert when no deep-dive is active. The cursor lands back on the K that
        was dived into (or the last node if it is gone)."""
        # The diff view is the same navigation family (Q12): Ctrl+o pops it too,
        # one level at a time — a drilled region backs out to the overview first
        # (task 21), then the overview closes to the live view.
        if self._diff_view is not None:
            if self._diff_view.get("drill") is not None:
                self._close_drill()
                return
            await self._close_diff()
            return
        if not self._deep_dive_stack:
            return
        popped = self._deep_dive_stack.pop()
        visible = self._visible_nodes()
        target = popped["k_id"] if any(n.id == popped["k_id"] for n in visible) else (
            visible[-1].id if visible else None
        )
        await self._refresh_deep_dive_view(target)

    async def _refresh_deep_dive_view(self, select_id: str | None) -> None:
        """Rebuild the message list for the current view, restore the footer's
        deep-dive hint, land the cursor, and refresh the token surfaces."""
        await self._rebuild_message_list()
        self.query_one(AppFooter).set_deep_dive(bool(self._deep_dive_stack))
        self._select_message(select_id)
        self._refresh_token_ui()

    # --- context diff view (task 20) ------------------------------------

    async def _enter_diff(self, node: Node) -> None:
        """Open the full-pane context diff for assistant turn ``node``.

        Aligns the turn's generation-time context (left) against the now-view
        (right) by node id and swaps the message list for the ``DiffView``. The
        H4 tripwire runs on open: a stored-hash mismatch (or a pre-3b turn with
        no hash) shows the "reconstruction may be inexact" banner (A#3 §4). The
        region cursor lands on the first changed region."""
        all_nodes = self.core.all_nodes()
        regions = reconstruction.diff_regions(all_nodes, node.id)
        warning = reconstruction.reconstruction_warning(
            all_nodes, node.id, self.core.read_file
        )
        # A range selection can't survive the view swap (mirrors deep-dive, 13h #1).
        self._clear_range()
        self._diff_view = {
            "node_id": node.id,
            "label": f"Diff …{node.id[-4:]}",
            "regions": regions,
            "warning": warning,
            "drill": None,
        }
        self._toggle_diff_fullscreen(True)
        diff = self.query_one(DiffView)
        await diff.show(regions, warning)
        diff.focus()
        self.query_one(AppFooter).set_deep_dive(True)

    def _toggle_diff_fullscreen(self, on: bool) -> None:
        """Hide (``on``) or restore the body panes the full-screen diff replaces:
        the message list, the left detail inspector, and the docked input area.
        Hiding the inspector lets ``#conversation`` (and the ``DiffView`` inside
        it) expand to the full body width, so the two panes read as full-screen
        (task 37). ``MessageList.display`` still toggles so its cursor/visibility
        assertions hold."""
        self.query_one(MessageList).display = not on
        self.query_one(DetailInspector).display = not on
        self.query_one("#input-area").display = not on

    async def _close_diff(self) -> None:
        """Pop the diff view, restoring the live message list and its cursor."""
        target = self._diff_view["node_id"] if self._diff_view else None
        self._diff_view = None
        self.query_one(DiffView).close()
        self._toggle_diff_fullscreen(False)
        self.query_one(AppFooter).set_deep_dive(bool(self._deep_dive_stack))
        self.query_one(MessageList).focus()
        # Restore against the view actually rendered now (symmetric with
        # action_pop_deep_dive); with the diff/dive exclusivity gate this equals
        # core.nodes, but _visible_nodes() stays correct if that ever changes.
        self._select_message(
            target if any(n.id == target for n in self._visible_nodes()) else None
        )
        self._refresh_token_ui()

    def _move_region_cursor(self, step: int) -> None:
        """Move the diff view's changed-region cursor by ``step`` (clamped)."""
        self.query_one(DiffView).move_cursor(step)

    async def _drill_diff_region(self) -> None:
        """``Enter`` in the diff view: drill into the cursored changed region,
        rendering its left/right block sequences in full (H6 many-to-many;
        task 21). No-op with no changed regions or when already drilled."""
        diff = self._diff_view
        if diff is None or diff.get("drill") is not None:
            return
        changed = [r for r in diff["regions"] if r.changed]
        if not changed:
            return
        region = changed[self.query_one(DiffView).cursor]
        diff["drill"] = region
        await self.query_one(DiffView).show_drill(region)

    def _close_drill(self) -> None:
        """Return from a drilled region to the diff overview (task 21)."""
        if self._diff_view is not None:
            self._diff_view["drill"] = None
        self.query_one(DiffView).close_drill()

    # --- compression draft editor ---------------------------------------

    def _compression_range(self) -> list[str]:
        """Node ids the draft editor would compress: the active range, or a
        range-of-one on the selected node when no anchor is set (Q5). Empty when
        nothing is selected at all."""
        if self._range_anchor_id is not None:
            return self._range_ids()
        if self._selected_node_id is not None:
            return [self._selected_node_id]
        return []

    def action_compress(self) -> None:
        """`c` in Edit mode: open the draft editor on the active selection (Q4).

        No anchor → range-of-one on the selected node; no selection → no-op
        (select a range first with ``v`` in Edit mode). Compression is a
        selection-dependent action, so it is an Edit-mode key only — never a
        slash command (task 13b: entering Insert to type a command clears the
        selection, so a command can never act on it)."""
        if self.mode != "edit" or self._focus_in_detail():
            return
        if self._in_full_screen_inspection():  # read-only (tasks 12, 27)
            return
        if not self._compression_range():
            return
        self._open_compression_editor()

    async def action_expand(self) -> None:
        """`x` in Edit mode: restore the selected compression ``K``'s children.

        The non-destructive inverse of a commit (task 11 logic, now bound to a
        key rather than the removed ``/expand`` command — task 13b): calls
        ``core.expand_compression`` so the folded children return to the line in
        place, ``K`` is kept as an off-line orphan and an ``E`` expand event is
        recorded (ADR-0016 A#3). The message list is rebuilt from the restored
        view and the selection moves to the first restored child.

        Inert unless a node is selected in Edit mode (not while focus is in the
        detail pane, and not while deep-diving — the deep-dive is read-only, Q8).
        A non-compression selection is a **silent no-op** (task 43b): ``x`` is
        simply not a valid action there, and the footer already advertises it only
        when a K is selected — a hint would be noise. Refused while a turn is
        streaming (H2), and any core guard (``ValueError``) surfaces as a hint
        rather than propagating uncaught (mirrors ``action_commit_compression``)."""
        if self.mode != "edit" or self._focus_in_detail():
            return
        if self._in_full_screen_inspection():  # read-only (tasks 12, 27)
            return
        if self._stream_worker is not None and not self._stream_worker.is_finished:
            await self._hint("Cannot expand while a response is streaming.")
            return
        node = self._get_selected_node()
        if node is None or node.node_type != "compression":
            return
        children = self.core.folded_children(node.id)
        try:
            self.core.expand_compression(node.id)
        except ValueError as exc:
            await self._hint(str(exc))
            return
        await self._rebuild_message_list()
        if children:
            self._select_message(children[0].id)
        else:
            self._clear_selection()
        self._refresh_token_ui()

    def _open_compression_editor(self) -> None:
        editor = self.query_one(CompressionEditor)
        self.query_one(DetailInspector).display = False
        editor.open(get_config()["compression"]["default_prompt"])
        self.query_one(AppFooter).set_editor(True)
        # Fresh editor → no draft has run yet, so a commit now is manual (Q4).
        self._last_drafted_prompt = ""
        editor.query_one("#compress-prompt", TextArea).focus()

    def _close_compression_editor(self) -> None:
        self.query_one(CompressionEditor).close()
        self.query_one(AppFooter).set_editor(False)
        # Cancel before dropping the reference: an orphaned draft worker keeps
        # streaming into the now-hidden TextArea and would overwrite a re-opened
        # editor's Summary with the old range's draft (13d).
        if self._draft_worker is not None and not self._draft_worker.is_finished:
            self._draft_worker.cancel()
        self._draft_worker = None
        # Defensive: whatever prompt a draft recorded is scoped to that editor
        # session; clearing on close means the next editor's manual commit can't
        # inherit a stale prompt even if a path skips the worker handlers (task 35).
        self._last_drafted_prompt = ""
        self.query_one(DetailInspector).display = True
        self.query_one(MessageList).focus()

    def _reset_transient_ui(self) -> None:
        """Tear down all transient compression/navigation UI before a
        conversation switch (13f).

        `/new` and `/resume` (and any future switch path) can fire while a
        deep-dive, an open draft editor, or a running draft worker stands — a
        mouse click focuses the InputBar without entering Insert or clearing
        state. Left standing, a dead dive frame keeps feeding `_visible_nodes()`
        (resurrecting the old conversation's folded children), the editor sits
        open over dead range ids (→ 13a's ValueError site), and a live draft
        worker survives the switch. So pop the whole dive stack + reset the
        footer hint, close the editor without committing (cancels a live worker,
        13d), and clear the chord/last-draft/selection state."""
        if self._diff_view is not None:
            self._diff_view = None
            self.query_one(DiffView).close()
            self._toggle_diff_fullscreen(False)
            self.query_one(AppFooter).set_deep_dive(False)
        if self._deep_dive_stack:
            self._deep_dive_stack.clear()
            self.query_one(AppFooter).set_deep_dive(False)
        if self.query_one(CompressionEditor).is_open:
            self._close_compression_editor()
        elif self._draft_worker is not None and not self._draft_worker.is_finished:
            self._draft_worker.cancel()
        self._draft_worker = None
        self._last_drafted_prompt = ""
        self._pending_chord = None
        self._last_hint = None
        self._clear_selection()

    def action_draft_compression(self) -> None:
        """`Ctrl+D` in the draft editor: stream an AI summary into the Bottom
        split (Q4). Inert unless the editor owns the left pane. Re-drafting
        overwrites the previous output; a further `Ctrl+D` while a draft is
        already streaming is ignored. Records the prompt used so a subsequent
        commit stamps it on the K."""
        editor = self.query_one(CompressionEditor)
        if not editor.is_open:
            return
        if self._draft_worker is not None and not self._draft_worker.is_finished:
            return
        ids = self._compression_range()
        if not ids:
            return
        prompt = editor.prompt
        self._last_drafted_prompt = prompt
        self._draft_worker = self._draft_compression_worker(ids[0], ids[-1], prompt)

    @work(name="draft_compression")
    async def _draft_compression_worker(self, start_id: str, end_id: str, prompt: str) -> None:
        editor = self.query_one(CompressionEditor)
        editor.set_output("")  # clear first — re-draft overwrites (Q4)
        text = ""
        try:
            async for token in self.core.draft_compression(start_id, end_id, prompt=prompt):
                text += token
                editor.set_output(text)
        except asyncio.CancelledError:
            # A cancelled draft keeps whatever streamed so far; the editor stays
            # open (the caller cancelled via Esc) and mutates no graph state. Drop
            # the recorded prompt so a subsequent hand-written commit stamps ""
            # (a manual K) rather than the abandoned draft's prompt (task 35).
            self._last_drafted_prompt = ""
            raise
        except Exception as exc:
            editor.set_output(f"Draft failed: {exc}")
            logger.error("draft error | error=%s", exc)
            # Same as the cancel path: a failed draft must not leave its prompt
            # lingering to corrupt a later manual commit (task 35).
            self._last_drafted_prompt = ""

    async def action_commit_compression(self) -> None:
        """`Ctrl+S` in the draft editor: fold the selected range into a K.

        Commits the editor's summary (Bottom split) as a compression via
        ``core.commit_compression``, stamping the last-drafted prompt on the K
        (``""`` when no draft ran → a manual commit, Q4), then closes the
        editor, clears the selection, rebuilds the list (children out, one K
        in), and refreshes the token UI. An empty summary breadcrumbs instead
        of committing. Gated on the editor being open so the binding is inert in
        normal Edit mode.
        """
        editor = self.query_one(CompressionEditor)
        if not editor.is_open:
            return
        if self._draft_worker is not None and not self._draft_worker.is_finished:
            # A live draft is still overwriting the Bottom split — committing now
            # would fold a half-streamed summary. Refuse; Esc cancels it (13d).
            await self._hint("Draft in progress — Esc cancels it first.")
            return
        if self._stream_worker is not None and not self._stream_worker.is_finished:
            # H2: a live turn is in flight (its ctx_hash isn't stamped until the
            # first tick). Refuse at the UI layer — mirrors action_expand — rather
            # than relying on the core ValueError catch below (task 28).
            await self._hint("Cannot commit while a response is streaming.")
            return
        if not editor.output.strip():
            await self._hint("Write a summary before committing (Ctrl+S).")
            return
        ids = self._compression_range()
        if not ids:
            return
        try:
            self.core.commit_compression(
                ids[0], ids[-1], summary=editor.output, prompt=self._last_drafted_prompt
            )
        except ValueError as exc:
            # A guard rejected the range (non-tip in 3a, K-in-range, mid-stream,
            # or stale ids after the view changed). Surface it and keep the
            # editor open so the user can adjust the range or Esc out — never let
            # it propagate uncaught (that soft-locks the app, task 13a). Mirrors
            # the graceful failure path in _draft_compression_worker.
            logger.error("commit error | error=%s", exc)
            await self._hint(str(exc))
            return
        self._close_compression_editor()
        # Route the clear through _select_message(None) so the inspector resets to
        # its placeholder — the folded node it was showing is gone (13h #3);
        # _clear_range drops the now-stale anchor (its ids just left the view).
        self._clear_range()
        self._select_message(None)
        await self._rebuild_message_list()
        self._refresh_token_ui()

    async def _rebuild_message_list(self) -> None:
        """Reconcile the message list against the current view
        (``_visible_nodes()``). Used after a structural change — a compression
        commit folds a range into a single K widget, expand unfolds it, deep-dive
        nav swaps frames. Delegates to ``MessageList.reconcile``, which mutates
        only the difference so surviving rows keep their widget instances and the
        pane no longer blanks-and-repopulates on every change (task 44)."""
        await self.query_one(MessageList).reconcile(self._visible_nodes())

    async def _mount_node(self, node: Node) -> None:
        """Mount a freshly-appended core node into the message list — but only
        while the live view is showing.

        During a deep-dive the pane renders a K's folded originals (read-only), so
        a node mounted now would land *inside* that frame, unreachable by the
        cursor. The core still holds it (append happened at the call site) and
        exit-dive rebuilds from ``_visible_nodes()``, so the node surfaces the
        moment the live view returns (13h #2)."""
        if self._deep_dive_stack:
            return
        await self.query_one(MessageList).add_node(node)

    async def _hint(self, text: str) -> None:
        """Surface a transient UI hint — a toast, never a graph node (task 42).

        Hints ("Write a summary before committing", "No files to include", …) are
        ephemeral guidance; routing them through
        ``core.add_system_message`` made them accumulate as permanent nodes that
        survive ``/new``/``/resume``. They go through ``notify`` instead.
        Durable breadcrumbs (``/model`` changes, connectivity notices) stay
        persistent nodes (ADR 0006 #6) — they do NOT come here."""
        self._last_hint = text
        self.notify(text)

    def _focus_in_detail(self) -> bool:
        return self._is_focused_in(self.query_one(DetailInspector))

    def action_up(self) -> None:
        if self.mode != "edit":
            return
        if self._diff_view is not None:
            self._move_region_cursor(-1)
            return
        if self._focus_in_detail():
            inspector = self.query_one(DetailInspector)
            if inspector.pane_mode == "browse":
                inspector.highlight_prev()
            elif inspector.pane_mode == "maximized":
                inspector.scroll_lines(-1)
            return
        self._move_cursor(-1)

    def action_down(self) -> None:
        if self.mode != "edit":
            return
        if self._diff_view is not None:
            self._move_region_cursor(1)
            return
        if self._focus_in_detail():
            inspector = self.query_one(DetailInspector)
            if inspector.pane_mode == "browse":
                inspector.highlight_next()
            elif inspector.pane_mode == "maximized":
                inspector.scroll_lines(1)
            return
        self._move_cursor(1)

    def _move_cursor(self, step: int) -> None:
        # While extending a range the cursor clamps at the list edges (no wrap):
        # entering Edit parks the cursor on the last node, so a wrapping `v`,`down`
        # would land on index 0 and range-select the whole conversation (task 13e).
        # _select_relative keeps wrapping for its non-range callers.
        if self._range_anchor_id is not None:
            self._extend_range(step)
        else:
            self._select_relative(step)

    def _extend_range(self, step: int) -> None:
        nodes = self._visible_nodes()
        if not nodes:
            return
        start = next(
            (i for i, n in enumerate(nodes) if n.id == self._selected_node_id), 0
        )
        idx = max(0, min(len(nodes) - 1, start + step))
        self._select_message(nodes[idx].id)
        self._apply_range_selection()

    def _select_relative(self, step: int) -> None:
        nodes = self._visible_nodes()
        if not nodes:
            return
        default = len(nodes) if step < 0 else -1
        if self._selected_node_id is None:
            start = default
        else:
            start = next(
                (i for i, n in enumerate(nodes) if n.id == self._selected_node_id),
                default,
            )
        idx = (start + step) % len(nodes)
        self._select_message(nodes[idx].id)

    async def action_detail_enter(self) -> None:
        if self.mode != "edit":
            return
        # In the diff view, Enter drills into the cursored changed region (task 21).
        if self._diff_view is not None:
            await self._drill_diff_region()
            return
        if not self._focus_in_detail():
            return
        inspector = self.query_one(DetailInspector)
        if inspector.pane_mode == "browse":
            inspector.maximize()
            self._sync_footer()

    def action_jump_home(self) -> None:
        if not self._visible_nodes():
            return
        if self.mode != "edit":
            self._set_mode("edit")
        self._select_message(self._visible_nodes()[0].id)

    def action_maximize_split(self, which: str) -> None:
        if self.mode != "edit":
            return
        node = self._get_selected_node()
        if not node or node.node_type not in _SPLIT_VIEW_TYPES:
            return
        if self.query_one(DetailInspector).maximize_named(which):
            self._sync_footer()

    def action_switch_focus(self) -> None:
        if self.mode != "edit":
            return
        # While the draft editor owns the left pane, Tab cycles its two splits
        # (the inspector behind it is hidden) so the summary is keyboard-reachable.
        editor = self.query_one(CompressionEditor)
        if editor.is_open:
            editor.focus_next_split()
            return
        inspector = self.query_one(DetailInspector)
        message_list = self.query_one(MessageList)
        if self._focus_in_detail():
            inspector.exit_pane()
            message_list.focus()
        else:
            mode = inspector.enter_pane()
            if mode == "browse":
                inspector.focus()
            # "maximized" already focused the split; "none" → stay on messages
        self._sync_footer()

    def _sync_footer(self) -> None:
        footer = self.query_one(AppFooter)
        footer.set_detail(self.query_one(DetailInspector).pane_mode)
        node = self._get_selected_node()
        node_type = node.node_type if node else None
        drifted = node is not None and self._turn_has_drift(node, self.core.all_nodes())
        footer.set_selection(node_type, drifted)

    def _get_selected_node(self) -> Node | None:
        if self._selected_node_id is None:
            return None
        for node in self._visible_nodes():
            if node.id == self._selected_node_id:
                return node
        return None

    def _is_focused_in(self, widget) -> bool:
        focused = self.focused
        if focused is None:
            return False
        if focused == widget:
            return True
        return focused in widget.walk_children()

    def _focus_target(self) -> str | None:
        """Report which pane currently holds focus, semantically."""
        if self.focused is None:
            return None
        if self._is_focused_in(self.query_one(InputBar)):
            return "input"
        if self._is_focused_in(self.query_one(DetailInspector)):
            return "detail"
        if self._is_focused_in(self.query_one(MessageList)):
            return "messages"
        return "other"

    # --- token weights --------------------------------------------------

    def _node_weights(self) -> list[int | None]:
        """Per-node weight percentages parallel to ``self.core.nodes``.

        The single computation both ``describe_state`` and ``_refresh_token_ui``
        read, so the snapshot and the rendered ``--%`` slots cannot drift. Basis
        comes from config; the window denominator (only used by ``"window"``
        basis) from the active model, ``None`` when unknown.
        """
        return tokens.weight_pct(
            self.core.nodes,
            self.core.model,
            self.core.read_file,
            get_config()["ui"]["weight_basis"],
            tokens.model_window(self.core.model),
        )

    def _turn_has_drift(self, node: Node, all_nodes: list[Node]) -> bool:
        """Whether the UI should surface ``node`` as a drifted assistant turn.

        The single drift predicate behind both the passive ``Δ`` marker
        (``_node_drift``) and the active ``g d`` diff drill (``_drill_selected``),
        so the two cannot disagree: ``ui.show_context_drift`` gates *all* drift
        UI, not just the marker — with the flag off there is no marker to signal
        drift, so the diff drill must not open either (task 24). ``False`` for
        every non-assistant role, for an undrifted turn, and for every node when
        the flag is off. ``all_nodes`` is passed in so a per-node caller fetches
        the graph once.
        """
        if not get_config()["ui"]["show_context_drift"]:
            return False
        return node.role == "assistant" and reconstruction.has_drift(
            all_nodes, node.id
        )

    def _drift_signature(self) -> tuple:
        """A cheap fingerprint of everything ``_node_drift`` depends on.

        Drift is structural, not content-based, so it changes only when a node
        (incl. an off-line ``K``/``E``) enters the graph, the visible line moves
        (a rewind), the conversation is swapped (``/new``/``/resume``), or the
        ``ui.show_context_drift`` flag flips. The graph is append-only, so any
        structural change bumps ``len(all_nodes)``/``max created_seq``; a rewind
        shortens ``self.core.nodes``; a conversation swap changes its id. None of
        these components re-folds the graph, so building the signature is cheap.
        """
        all_nodes = self.core.all_nodes()
        return (
            self.core.conversation_id,
            len(all_nodes),
            max((n.created_seq for n in all_nodes), default=0),
            len(self.core.nodes),
            get_config()["ui"]["show_context_drift"],
        )

    def _node_drift(self) -> list[bool]:
        """Per-node context-drift flags parallel to ``self.core.nodes``.

        ``True`` for an **assistant** turn whose generation context has since
        drifted from the now-view (``reconstruction.has_drift`` over the whole
        graph); ``False`` for every other role and for all nodes when
        ``ui.show_context_drift`` is off. Both ``describe_state`` and
        ``_refresh_token_ui`` read this so the snapshot and the rendered marker
        cannot disagree (ADR-0016 concern "b", task 19).

        Memoized on ``_drift_signature`` (task 32): the O(n²) per-node fold runs
        only when a drift input actually changes, so back-to-back refreshes /
        snapshots on an unchanged graph reuse the cached result.
        """
        signature = self._drift_signature()
        if self._drift_cache is not None and self._drift_cache[0] == signature:
            return self._drift_cache[1]
        if not get_config()["ui"]["show_context_drift"]:
            result = [False] * len(self.core.nodes)
        else:
            all_nodes = self.core.all_nodes()
            result = [self._turn_has_drift(n, all_nodes) for n in self.core.nodes]
        self._drift_cache = (signature, result)
        return result

    def _node_signature(self) -> tuple:
        """A cheap fingerprint of the current node set's content.

        Pairs each node's stable id with its content length, so the tuple
        differs whenever a node is added, removed, reordered, or grows (a
        streamed reply). The gauge compares it against ``_gauge_anchor`` to tell
        a provider-exact figure from a now-stale one.
        """
        return tuple((n.id, len(n.content)) for n in self.core.nodes)

    def _gauge_state(self) -> tuple[int | None, bool]:
        """Header gauge ``(pct, approximate)`` for the current context.

        ``pct`` is used ÷ model window (``None`` → ``--%`` when the window is
        unknown), with the local estimate scaled by any provider calibration.
        ``approximate`` is ``True`` when there is no calibration yet *or* the
        node set has drifted from the last anchored turn — either way the
        absolute figure is only an estimate and the UI marks it ``~``.
        """
        messages = build_context(self.core.nodes, self.core.read_file)
        local_total = tokens.count_messages(messages, self.core.model)
        pct, approximate = tokens.gauge(
            local_total,
            tokens.model_window(self.core.model),
            self.core.calibration,
        )
        stale = self._node_signature() != self._gauge_anchor
        return pct, approximate or stale

    def _refresh_token_ui(self) -> None:
        """Refresh both token-budget surfaces after a node-list/content change.

        Called after any change to the node list or to node content (a new turn,
        a finished stream, ``/include``, ``/resume``, ``/new``): pushes each
        node's per-node weight ``--%`` onto its message widget and the
        used-÷-window gauge (with its ``~`` marker) onto the header."""
        message_list = self.query_one(MessageList)
        if self._deep_dive_stack:
            # Folded originals are off the live context (Q9): no % applies.
            for node in self._visible_nodes():
                try:
                    widget = message_list.query_one(f"#msg-{node.id}", MessageWidget)
                except Exception:
                    continue
                widget.set_weight_not_in_context()
                widget.set_drift(False)
        else:
            for node, pct, drifted in zip(
                self.core.nodes, self._node_weights(), self._node_drift(), strict=True
            ):
                try:
                    widget = message_list.query_one(f"#msg-{node.id}", MessageWidget)
                except Exception:
                    continue
                widget.set_weight_pct(pct)
                widget.set_drift(drifted)
        # The header gauge always reflects the live context window, never the
        # browsed originals — deep-dive does not change what the model will see.
        gauge_pct, approximate = self._gauge_state()
        self.query_one(AppHeader).set_context_pct(gauge_pct, approximate)

    # --- state snapshot -------------------------------------------------

    def describe_state(self) -> dict:
        """Return a structured snapshot of the app's observable state.

        Raw data only (full node content, no truncation) — token-budget
        formatting lives in ``tools/agent/snapshot.py``. Useful for the agent
        MCP layer and for debugging/logging this otherwise-opaque TUI.

        Nodes are reported by stable *index* + role (the random ``Node.id``
        uuids are an implementation detail agents should not depend on).
        """
        in_deep_dive = bool(self._deep_dive_stack)
        nodes = self._visible_nodes()
        truncation = get_config()["ui"]["truncation_lines"]
        # Deep-dive originals are off-context, so no per-node % applies (Q9).
        weights = [None] * len(nodes) if in_deep_dive else self._node_weights()
        drift = [False] * len(nodes) if in_deep_dive else self._node_drift()
        gauge_pct, gauge_approximate = self._gauge_state()
        selected_index: int | None = None
        selected_role: str | None = None
        node_states: list[dict] = []
        for i, node in enumerate(nodes):
            is_selected = node.id == self._selected_node_id
            if is_selected:
                selected_index = i
                selected_role = node.role
            entry: dict = {
                "index": i,
                "role": node.role,
                "node_type": node.node_type,
                "content": node.content,
                "selected": is_selected,
                "weight_pct": weights[i],
                "drift": drift[i],
                "truncated": self._is_truncated(node, truncation),
            }
            source_path = node.meta.get("source_path")
            if source_path:
                entry["source_path"] = source_path
            node_states.append(entry)

        streaming = self._stream_worker is not None and not self._stream_worker.is_finished

        input_bar = self.query_one(InputBar)
        suggestions = self.query_one("#command-suggestions", Static)
        command_menu: dict | None = None
        if suggestions.display:
            command_menu = {
                "visible": True,
                "selected": InputBar.COMMANDS[input_bar._selected_command],
                "items": list(InputBar.COMMANDS),
                "count": len(InputBar.COMMANDS),
                # True when the menu's region is covered by the input bar — a
                # rendering regression that is invisible to widget content but
                # hides menu items from the user (see the docked-overlap bug).
                "occluded": self._regions_overlap(suggestions, input_bar),
            }

        inspector = self.query_one(DetailInspector)
        detail_view = inspector.view_kind
        detail_node_index: int | None = None
        detail_node_role: str | None = None
        if inspector.node_state is not None:
            detail_id = inspector.node_state.node_id
            detail_node_index = next(
                (i for i, n in enumerate(nodes) if n.id == detail_id), None
            )
            detail_node_role = inspector.node_state.role

        return {
            "mode": self.mode,
            "model": self.core.model,
            "title": self.core.conversation_title,
            "streaming": streaming,
            "focus": self._focus_target(),
            "selected_index": selected_index,
            "selected_role": selected_role,
            # Indices into the reported ``nodes`` array (never raw uuids), per this
            # method's own stable-index convention (13i).
            "range_selection": [
                i for i, node in enumerate(nodes) if node.id in set(self._range_ids())
            ],
            "compression_editor": self._compression_editor_state(),
            "layout": {"header": True, "footer": True, "panes": ["detail", "conversation"]},
            "footer": self.query_one(AppFooter).current_hint(),
            "last_hint": self._last_hint,
            "detail": {
                "node_index": detail_node_index,
                "node_role": detail_node_role,
                "view": detail_view,
                "splits_visible": inspector.splits_visible() if detail_view == "context" else [],
                "pane_mode": inspector.pane_mode,
                "highlighted_split": inspector.highlighted_split(),
                "maximized_split": inspector.maximized_split(),
                "locked": self.mode == "insert",
            },
            "context_gauge": {"pct": gauge_pct, "approximate": gauge_approximate},
            "deep_dive": {
                "active": in_deep_dive,
                "breadcrumb": [
                    "Chat",
                    *(f["label"] for f in self._deep_dive_stack),
                    *([self._diff_view["label"]] if self._diff_view else []),
                    *(
                        ["Region"]
                        if self._diff_view and self._diff_view.get("drill") is not None
                        else []
                    ),
                ],
            },
            "diff_view": self._diff_view_state(),
            "truncation": truncation,
            "input": input_bar.value,
            "command_menu": command_menu,
            "colors": get_config()["colors"],
            "nodes": node_states,
        }

    def _compression_editor_state(self) -> dict:
        """Snapshot of the draft editor for ``describe_state`` (the Pilot floor):
        whether it is open plus its current prompt/output text."""
        editor = self.query_one(CompressionEditor)
        return {"open": editor.is_open, "prompt": editor.prompt, "output": editor.output}

    def _diff_view_state(self) -> dict:
        """Snapshot of the context-diff view for ``describe_state`` (task 20/21):
        whether it is open, its **changed** regions (each ``{"left": [ids],
        "right": [ids]}``, aligned by node id), the H4 warning flag, and the
        drilled region (``{"left": [ids], "right": [ids]}`` or ``None``)."""
        diff = self._diff_view
        if diff is None:
            return {"open": False, "regions": [], "warning": False, "drill": None}
        drill = diff.get("drill")
        return {
            "open": True,
            "regions": [
                {"left": [n.id for n in r.left], "right": [n.id for n in r.right]}
                for r in diff["regions"]
                if r.changed
            ],
            "warning": diff["warning"],
            "drill": (
                {"left": [n.id for n in drill.left], "right": [n.id for n in drill.right]}
                if drill is not None
                else None
            ),
        }

    @staticmethod
    def _regions_overlap(a, b) -> bool:
        """Whether two widgets' laid-out regions intersect on screen. Used to
        detect rendering overlaps that widget content/state cannot reveal."""
        try:
            ra, rb = a.region, b.region
        except Exception:
            return False
        if not ra.area or not rb.area:
            return False
        return not (
            ra.right <= rb.x
            or rb.right <= ra.x
            or ra.bottom <= rb.y
            or rb.bottom <= ra.y
        )

    @staticmethod
    def _is_truncated(node: Node, truncation: dict) -> bool:
        limit = truncation.get(_TRUNCATION_KEY.get(node.role, "system"))
        if limit == "auto" or not isinstance(limit, int):
            return False
        return node.content.count("\n") + 1 > limit

    # --- input + commands -----------------------------------------------

    async def on_input_bar_submitted(self, event: InputBar.Submitted) -> None:
        text = event.text.strip()
        logger.info("on_input_bar_submitted | text=%r | len=%d", text, len(text))
        with contextlib.suppress(Exception):
            self.query_one("#command-suggestions", Static).display = False
        if not text:
            return

        logger.info("input submitted | text=%r", text)

        if text.startswith("/model"):
            logger.info("matched /model")
            await self._handle_model_command(text)
            return

        if text == "/new":
            logger.info("matched /new")
            await self._handle_new_command()
            return

        if text == "/resume":
            logger.info("matched /resume")
            self._handle_resume_command()
            return

        if text == "/include":
            logger.info("matched /include")
            self._handle_include_command()
            return

        logger.info("no command matched, sending to model")

        user_node, assistant_node = self.core.submit(text)
        await self._mount_node(user_node)
        await self._mount_node(assistant_node)
        self.query_one(AppHeader).set_title(self.core.conversation_title)
        self._refresh_token_ui()
        if self.mode == "insert":
            self._lock_inspector_to_last()
        self._stream_worker = self._stream_response(assistant_node)

    def _update_model_label(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one(AppFooter).set_model(self.core.model)

    async def _handle_model_command(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            logger.info("model queried | current=%s", self.core.model)
            node = self.core.add_system_message(f"Current model: {self.core.model}")
        else:
            new_model = parts[1]
            node = self.core.set_model(new_model)
            self._update_model_label()
            logger.info("model switched | new_model=%s", new_model)
            self._check_connectivity(new_model)
        await self._mount_node(node)
        if self.mode == "insert":
            self._lock_inspector_to_last()

    @work(name="check_connectivity")
    async def _check_connectivity(self, model: str) -> None:
        node = await self.core.check_connectivity(model)
        await self._mount_node(node)
        if self.mode == "insert":
            self._lock_inspector_to_last()

    async def _handle_new_command(self) -> None:
        old_id = self.core.conversation_id
        node = self.core.new_conversation()
        logger.info("new conversation | old_id=%s", old_id)
        self._reset_transient_ui()
        message_list = self.query_one(MessageList)
        for child in list(message_list.children):
            await child.remove()
        await message_list.add_node(node)
        self.query_one(AppHeader).set_title(self.core.conversation_title)
        self._update_model_label()
        self._refresh_token_ui()
        if self.mode == "insert":
            self._lock_inspector_to_last()

    @work(name="handle_resume")
    async def _handle_resume_command(self) -> None:
        conversations = self._repo.list()
        if not conversations:
            await self._hint("No past conversations found.")
            return
        result = await self.push_screen_wait(HistoryScreen(self._repo))
        if result is None:
            return
        nodes = self.core.resume_conversation(result)
        self._reset_transient_ui()
        message_list = self.query_one(MessageList)
        for child in list(message_list.children):
            await child.remove()
        for node in nodes:
            await message_list.add_node(node)
        self.query_one(AppHeader).set_title(self.core.conversation_title)
        self._update_model_label()
        self._refresh_token_ui()
        if self.mode == "insert":
            self._lock_inspector_to_last()
        logger.info("loaded conversation | id=%s | nodes=%d", result, len(nodes))

    @work(name="handle_include")
    async def _handle_include_command(self) -> None:
        files = self._workspace.list_files()
        if not files:
            await self._hint("No files in .ctx/context/ to include.")
            return
        result = await self.push_screen_wait(IncludeScreen(self._workspace))
        if not result:
            return
        nodes = self.core.include_files(result)
        for node in nodes:
            await self._mount_node(node)
            logger.info("context included | path=%s", node.meta.get("source_path", ""))
        self._refresh_token_ui()
        if self.mode == "insert":
            self._lock_inspector_to_last()

    # --- streaming ------------------------------------------------------

    @work(name="stream_response")
    async def _stream_response(self, assistant_node: Node) -> None:
        message_list = self.query_one(MessageList)
        inspector = self.query_one(DetailInspector)
        usage_gen_before = self.core.usage_generation
        try:
            async for _token in self.core.stream(assistant_node):
                message_list.update_content(assistant_node.id, assistant_node.content)
                self._stream_to_inspector(inspector, assistant_node)
            logger.info("response finalized | length=%d", len(assistant_node.content))
            if self.core.usage_generation != usage_gen_before:
                # This turn produced a fresh provider anchor: the gauge is now
                # exact for the current node set. Remember it so a later change
                # (a /include before the next turn) re-marks the gauge stale.
                self._gauge_anchor = self._node_signature()
        except asyncio.CancelledError:
            assistant_node.meta["interrupted"] = True
            message_list.update_content(assistant_node.id, assistant_node.content or "▌")
            raise
        except Exception as exc:
            assistant_node.meta["error"] = str(exc)
            message_list.update_content(assistant_node.id, f"**Error:** {exc}")
            logger.error("stream error | error=%s", exc)

    def _stream_to_inspector(self, inspector: DetailInspector, node: Node) -> None:
        """Render the live stream into the left pane only when it is locked to
        this streaming node (so navigating away in Edit mode is not hijacked)."""
        state = inspector.node_state
        if state is not None and state.node_id == node.id:
            inspector.append_stream(node.content)

    def action_cancel_stream(self) -> None:
        if self._stream_worker and not self._stream_worker.is_finished:
            self._stream_worker.cancel()
        else:
            self.exit()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name == "stream_response" and event.state in (
            WorkerState.SUCCESS,
            WorkerState.CANCELLED,
            WorkerState.ERROR,
        ):
            self._stream_worker = None
            # The assistant node now carries its full text — its weight (and the
            # context-basis share of every other node) only just became real.
            self._refresh_token_ui()
