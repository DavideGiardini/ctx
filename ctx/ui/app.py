import asyncio
import contextlib
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.timer import Timer
from textual.widgets import Static, TextArea
from textual.worker import Worker, WorkerState

from ctx.core import tokens
from ctx.core.config import get_config
from ctx.core.context import build_context
from ctx.core.conversation import ConversationCore
from ctx.core.log import logger
from ctx.core.provider import LiteLLMProvider, Provider
from ctx.core.search import SearchBackend
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
from ctx.ui.widgets.history_screen import HistoryScreen
from ctx.ui.widgets.include_screen import ImportScreen, IncludeScreen
from ctx.ui.widgets.input_bar import InputBar
from ctx.ui.widgets.message_list import MessageList, MessageWidget
from ctx.ui.widgets.message_row import truncation_key
from ctx.ui.widgets.pane_seam import RULE_CLASS, PaneSeam

# How long the Detail Inspector render waits after the last cursor move before
# it re-parses the selected node's Markdown. Every move just restarts this
# settle timer, so the expensive parse runs once movement stops rather than
# once per keystroke (edit-mode scroll-lag fix). Selection state (row
# highlight, footer, scroll) stays immediate — only the render debounces.
# AIDEV-NOTE: must exceed the fast-tapping cadence (~100-200ms between presses)
# or taps escape the window and each one pays a full render.
_INSPECTOR_DEBOUNCE = 0.10


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
        search: SearchBackend | None = None,
    ) -> None:
        super().__init__()
        # Injectable seams: default to the real adapters so production
        # `ChatApp()` is unchanged, while tests/harness can pass a
        # TestProvider, a canned search backend and a temp-dir Workspace.
        self._workspace = workspace or Workspace(Path.cwd())
        self._repo = storage or ConversationRepository(str(self._workspace.db_path))
        self.core = ConversationCore(
            self._repo,
            provider or LiteLLMProvider(),
            workspace=self._workspace,
            search=search,
        )
        self._stream_worker: Worker | None = None
        # The assistant node the live turn-stream writes into, tracked so a
        # zero-token cancel can drop the phantom empty node (task 48).
        self._streaming_node: Node | None = None
        # The in-flight draft worker (``Ctrl+D``) and the prompt of the last
        # draft that actually ran. ``""`` means no draft ran → a manual commit
        # (Q4); ``Ctrl+S`` records this prompt on the committed K.
        self._draft_worker: Worker | None = None
        self._last_drafted_prompt: str = ""
        # When the draft editor is open for an ``/import`` (not a compression),
        # this holds the picked ``(source_path, source_content)`` snapshot; the
        # shared ``Ctrl+D``/``Ctrl+S`` actions dispatch on it. ``None`` = the
        # editor, if open, is a compression editor.
        self._import_source: tuple[str, str] | None = None
        self.mode = "insert"
        self._selected_node_id: str | None = None
        # Detail Inspector render debounce (see ``_schedule_inspector_render``).
        # The pending settle timer; ``None`` when idle. Invariant: timer running
        # ⇔ a render is owed for the current selection.
        self._inspector_timer: Timer | None = None
        # Anchor of a vim-style range selection (Edit mode). ``None`` when no
        # range is active; while set, up/down extend the contiguous highlight
        # between it and the cursor (``_selected_node_id``). See ADR-0016 Q5.
        self._range_anchor_id: str | None = None
        # Node-set signature captured the last time a streamed turn produced a
        # fresh provider ``usage`` anchor. The header gauge is exact only while
        # the conversation still matches it; any later change makes it stale
        # (``~``). ``None`` until the first anchored turn.
        self._gauge_anchor: tuple | None = None
        # Most-recent transient UI hint (task 42). Surfaced as a toast via
        # ``notify`` and exposed on ``describe_state`` so headless QA can observe
        # it; unlike a durable breadcrumb it is NOT a graph node. ``None`` = none
        # shown yet; reset on a conversation switch.
        self._last_hint: str | None = None
        # Seam and header, held from on_mount so the idle tick that keeps the
        # chrome tracking the layout costs nothing (see ``on_idle``).
        self._seam: PaneSeam | None = None
        self._header: AppHeader | None = None
        logger.info("app initialized | default_model=%s", self.core.model)

    def get_css_variables(self) -> dict[str, str]:
        """Expose the config chrome palette to the CSS as ``$ctx-*`` variables.

        The single seam between ``config.py``'s ``colors`` and the stylesheet:
        every UI color the CSS draws (selection highlight, pane seams, muted
        header text) is read from config here rather than hardcoded across the
        ``.css``/``DEFAULT_CSS`` files, so retheming is a one-place edit — and the
        same hook that lets a future ``config.json`` recolor the whole UI. Merged
        over the theme's own variables so ``$primary``/``$text-muted`` still work.
        """
        variables = super().get_css_variables()
        colors = get_config()["colors"]
        variables["ctx-selection"] = colors["selection"]
        variables["ctx-seam"] = colors["seam"]
        variables["ctx-muted"] = colors["muted"]
        return variables

    def compose(self) -> ComposeResult:
        yield AppHeader(id="app-header")
        with Horizontal(id="body"):
            yield DetailInspector(id="detail")
            yield CompressionEditor(id="compression-editor")
            yield PaneSeam(id="pane-seam")
            with Vertical(id="conversation"):
                yield MessageList(id="messages")
                # Suggestions + input share one docked container so they stack
                # in normal flow (docking both directly would overlap them).
                with Container(id="input-area", classes=RULE_CLASS):
                    yield Static("", id="command-suggestions")
                    # Terminal-native prompt line: a "> " marker beside a
                    # borderless input, not a bordered GUI text box.
                    with Horizontal(id="input-line"):
                        yield Static(">", id="prompt-marker")
                        yield InputBar()
        yield AppFooter()

    def on_mount(self) -> None:
        # Terminal-native look: resolve all theme colors to the terminal's own
        # 16 ANSI colors and the screen background to ansi_default, so the app
        # inherits the user's terminal theme and window transparency. Note that
        # under this theme $surface/$panel/$boost resolve to *transparent* —
        # seams and highlights need explicit ansi_* colors.
        self.theme = "ansi-dark"
        self._seam = self.query_one(PaneSeam)
        self._header = self.query_one(AppHeader)
        self.core.setup()
        self.query_one(InputBar).focus()
        self.query_one(AppHeader).set_model(self.core.model)
        self.query_one(AppFooter).set_mode("insert")
        self._lock_inspector_to_last()

    def on_idle(self) -> None:
        # The chrome that has to track the layout re-checks here, because nothing
        # notifies it: a grown input or a hidden split changes no geometry of the
        # seam's own, and the header cannot see where the body ended up splitting.
        # Both calls are no-ops unless something actually moved. Idle fires hard
        # during a stream, hence the held references rather than queries.
        if self._seam is None or self._header is None:
            return
        self._seam.sync()
        self._header.align_logo(self._seam.region.x)

    # --- command suggestions overlay ------------------------------------

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        # The draft editor's two splits are TextAreas as well and their changes
        # bubble through here; only the prompt line drives the command menu.
        input_bar = self.query_one(InputBar)
        if event.text_area is not input_bar:
            return
        suggestions = self.query_one("#command-suggestions", Static)
        suggestions.display = input_bar.menu_active
        if not input_bar.menu_active:
            return
        for i, cmd in enumerate(InputBar.COMMANDS):
            if cmd.startswith(input_bar.text):
                input_bar._selected_command = i
                break
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
        # Inside the detail pane, Esc leaves the pane in one step — from Browse or
        # from a maximized split alike — and lands back in Edit mode on the
        # conversation, selection still on the node that was open. (No
        # Maximized→Browse rung: stepping down into Browse left the split that had
        # been maximized wearing focus, so the pane read as half-selected.)
        if self.mode == "edit" and self._focus_in_detail():
            inspector = self.query_one(DetailInspector)
            if inspector.pane_mode != "none":
                inspector.exit_pane()
                self.query_one(MessageList).focus()
                self._sync_footer()
                return
        # An active range selection swallows the first Esc (clear the anchor but
        # stay in Edit); a second Esc then toggles the mode as usual (Q5).
        if self.mode == "edit" and self._range_anchor_id is not None:
            self._clear_range()
            return
        self._set_mode("edit" if self.mode == "insert" else "insert")

    async def action_enter_insert(self) -> None:
        # Vim-style: `i` returns to Insert mode from anywhere in Edit mode
        # (right pane or inside the detail pane). Switching to Insert re-locks
        # the inspector to the last node, resetting any detail sub-state.
        if self.mode == "edit":
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
        if node.node_type == "context":
            # Import 3-split (ctx0 §5): Prompt = the instruction (hidden when
            # empty — a verbatim include), Source = the raw file, Output = the
            # edited extract. A verbatim include has no separate extract, so the
            # file lands in the Source split and Output stays empty (hidden) —
            # the pane collapses to the single file view.
            raw_source = node.meta.get("source_content", "")
            if raw_source:
                source, output = raw_source, node.content
            else:
                source, output = node.content, ""
            return NodeView(
                node_id=node.id,
                role=node.role,
                node_type=node.node_type,
                content=source,
                prompt=node.meta.get("prompt", ""),
                output=output,
                source_path=node.meta.get("source_path"),
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
        # Drop any queued debounced render so it can't fire after this direct
        # show() and clobber the locked-to-last view.
        self._cancel_inspector_timer()
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
            self._schedule_inspector_render()
            self._sync_footer()
            return
        try:
            widget = message_list.query_one(f"#msg-{node_id}", MessageWidget)
            widget.set_selected(True)
            widget.scroll_visible(animate=False)
        except Exception:
            pass
        self._schedule_inspector_render()
        self._sync_footer()

    def _schedule_inspector_render(self) -> None:
        """Trailing-edge debounce for the Detail Inspector render.

        A cursor move does **zero** inspector work — it only restarts the settle
        timer, keeping the keypress path cheap no matter how fast the cursor
        moves (held auto-repeat or rapid tapping). The expensive Markdown parse
        runs once, ``_INSPECTOR_DEBOUNCE`` after the *last* move, and reads the
        *current* selection — never a stale captured one. Until then the pane
        shows the previously settled node, editor-preview style."""
        self._cancel_inspector_timer()
        self._inspector_timer = self.set_timer(
            _INSPECTOR_DEBOUNCE, self._inspector_settled
        )

    def _inspector_settled(self) -> None:
        self._inspector_timer = None
        self._render_inspector_now()

    def _render_inspector_now(self) -> None:
        try:
            inspector = self.query_one(DetailInspector)
        except NoMatches:
            # The settle timer can land after shutdown tore the widgets down.
            return
        node = self._get_selected_node()
        inspector.show(self._node_view(node) if node else None)

    def _cancel_inspector_timer(self) -> None:
        if self._inspector_timer is not None:
            self._inspector_timer.stop()
            self._inspector_timer = None

    def _flush_inspector_render(self) -> None:
        """Land any owed debounced render synchronously — called before anything
        reads the inspector's ``node_state`` (entering the pane, the 1/2/3
        maximize shortcuts, Enter) so those never act on a stale node. With the
        trailing-edge debounce, a running timer ⇔ a render is owed; no timer
        means the pane already shows the settled selection and this is a no-op."""
        if self._inspector_timer is not None:
            self._cancel_inspector_timer()
            self._render_inspector_now()

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

    def action_anchor_range(self) -> None:
        """`v` in Edit mode: anchor a range selection at the current node.

        A fresh press re-anchors at the cursor (range-of-one). Up/Down then
        extend the contiguous highlight between the anchor and the cursor.
        """
        if self.mode != "edit" or self._focus_in_detail():
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

    def _visible_nodes(self) -> list[Node]:
        """The node list currently rendered in the message pane (the live
        conversation). Kept as the single seam every view-facing method
        (rendering, cursor navigation, snapshot) reads."""
        return self.core.nodes

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
        detail pane). A non-compression selection is a **silent no-op** (task 43b): ``x`` is
        simply not a valid action there, and the footer already advertises it only
        when a K is selected — a hint would be noise. Refused while a turn is
        streaming (H2), and any core guard (``ValueError``) surfaces as a hint
        rather than propagating uncaught (mirrors ``action_commit_compression``)."""
        if self.mode != "edit" or self._focus_in_detail():
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
        self._import_source = None
        editor.query_one("#compress-prompt", TextArea).focus()

    def _open_import_editor(self, source_path: str, source_content: str) -> None:
        """Open the draft editor for an ``/import`` (ctx0 §4.2).

        Reuses the compression editor widget — same prompt+output splits, same
        ``Ctrl+D``/``Ctrl+S`` flow — prefilled with the import default prompt and
        tagged with the picked file snapshot so the shared draft/commit actions
        dispatch to ``draft_import``/``commit_import`` rather than compression."""
        editor = self.query_one(CompressionEditor)
        self.query_one(DetailInspector).display = False
        editor.open(get_config()["import"]["default_prompt"], output_label="Output")
        self.query_one(AppFooter).set_editor(True)
        self._last_drafted_prompt = ""
        self._import_source = (source_path, source_content)
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
        self._import_source = None
        self.query_one(DetailInspector).display = True
        # Return focus by mode: an Insert-mode entry (e.g. /import) goes back to
        # the input bar; Edit-mode (compression) returns to the node list.
        if self.mode == "insert":
            self.query_one(InputBar).focus()
        else:
            self.query_one(MessageList).focus()

    def _reset_transient_ui(self) -> None:
        """Tear down all transient compression UI before a conversation switch
        (13f).

        `/new` and `/resume` (and any future switch path) can fire while an open
        draft editor or a running draft worker stands — a mouse click focuses the
        InputBar without entering Insert or clearing state. Left standing, the
        editor sits open over dead range ids (→ 13a's ValueError site) and a live
        draft worker survives the switch. So close the editor without committing
        (cancels a live worker, 13d) and clear the last-draft/selection state."""
        if self.query_one(CompressionEditor).is_open:
            self._close_compression_editor()
        elif self._draft_worker is not None and not self._draft_worker.is_finished:
            self._draft_worker.cancel()
        self._draft_worker = None
        self._last_drafted_prompt = ""
        self._import_source = None
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
        prompt = editor.prompt
        self._last_drafted_prompt = prompt
        if self._import_source is not None:
            _, source_content = self._import_source
            self._draft_worker = self._draft_import_worker(source_content, prompt)
            return
        ids = self._compression_range()
        if not ids:
            return
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

    @work(name="draft_import")
    async def _draft_import_worker(self, source: str, prompt: str) -> None:
        editor = self.query_one(CompressionEditor)
        editor.set_output("")  # clear first — re-draft overwrites
        text = ""
        try:
            async for token in self.core.draft_import(source, prompt=prompt):
                text += token
                editor.set_output(text)
        except asyncio.CancelledError:
            # Mirror the compression worker: drop the recorded prompt so a later
            # hand-written commit stamps "" (a manual import), not the abandoned
            # draft's prompt.
            self._last_drafted_prompt = ""
            raise
        except Exception as exc:
            editor.set_output(f"Draft failed: {exc}")
            logger.error("import draft error | error=%s", exc)
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
        if self._import_source is not None:
            if not editor.output.strip():
                await self._hint("Write an extract before committing (Ctrl+S).")
                return
            source_path, source_content = self._import_source
            # Stamp the prompt that actually drafted the extract ("" if the
            # extract was hand-written without a draft) — mirrors compression.
            node = self.core.commit_import(
                source_path,
                source_content,
                extract=editor.output,
                prompt=self._last_drafted_prompt,
            )
            # _close_compression_editor returns focus by mode (Insert → input
            # bar for /import); lock the inspector to the freshly-appended node.
            self._close_compression_editor()
            await self._mount_node(node)
            self._refresh_token_ui()
            if self.mode == "insert":
                self._lock_inspector_to_last()
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
        """Mount a freshly-appended core node into the message list."""
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
        if not self._focus_in_detail():
            return
        self._flush_inspector_render()
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
        self._flush_inspector_render()
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
            # Entering the pane reads node_state; make sure a pending debounced
            # render has landed so we enter on the current selection.
            self._flush_inspector_render()
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
        footer.set_selection(node_type)

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
        node set has changed since the last anchored turn — either way the
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
        for node, pct in zip(self.core.nodes, self._node_weights(), strict=True):
            try:
                widget = message_list.query_one(f"#msg-{node.id}", MessageWidget)
            except Exception:
                continue
            widget.set_weight_pct(pct)
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
        nodes = self._visible_nodes()
        truncation = get_config()["ui"]["truncation_lines"]
        weights = self._node_weights()
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
            "truncation": truncation,
            "input": input_bar.text,
            "command_menu": command_menu,
            "colors": get_config()["colors"],
            "nodes": node_states,
        }

    def _compression_editor_state(self) -> dict:
        """Snapshot of the draft editor for ``describe_state`` (the Pilot floor):
        whether it is open plus its current prompt/output text."""
        editor = self.query_one(CompressionEditor)
        return {"open": editor.is_open, "prompt": editor.prompt, "output": editor.output}

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
        limit = truncation.get(truncation_key(node.role))
        if limit == "auto" or not isinstance(limit, int):
            return False
        return node.content.count("\n") + 1 > limit

    # --- input + commands -----------------------------------------------

    async def on_input_bar_submitted(self, event: InputBar.Submitted) -> None:
        # InputBar no longer clears itself on submit: acceptance clears, refusal
        # keeps the typed text (review §Turn lifecycle). Every early return below
        # must decide which it is — _accept_input() clears the bar.
        text = event.text.strip()
        logger.info("on_input_bar_submitted | text=%r | len=%d", text, len(text))
        with contextlib.suppress(Exception):
            self.query_one("#command-suggestions", Static).display = False
        if not text:
            self._accept_input()
            return

        logger.info("input submitted | text=%r", text)

        if text.startswith("/model"):
            logger.info("matched /model")
            self._accept_input()
            await self._handle_model_command(text)
            return

        if text == "/new":
            logger.info("matched /new")
            self._accept_input()
            await self._handle_new_command()
            return

        if text == "/resume":
            logger.info("matched /resume")
            self._accept_input()
            self._handle_resume_command()
            return

        if text == "/include":
            logger.info("matched /include")
            self._accept_input()
            self._handle_include_command()
            return

        if text == "/import":
            logger.info("matched /import")
            self._accept_input()
            self._handle_import_command()
            return

        logger.info("no command matched, sending to model")

        if self.core.streaming:
            # Refuse, don't queue — and don't clear: the typed text survives for
            # a resubmit once the turn ends. The core's submit() guard is the
            # backstop; this check is the courtesy path that keeps the input.
            await self._hint("A response is still streaming — Esc cancels it. Your text is kept.")
            return

        self._accept_input()
        user_node, assistant_node = self.core.submit(text)
        await self._mount_node(user_node)
        await self._mount_node(assistant_node)
        self._refresh_token_ui()
        if self.mode == "insert":
            self._lock_inspector_to_last()
        self._streaming_node = assistant_node
        self._stream_worker = self._stream_response(assistant_node)

    def _accept_input(self) -> None:
        """Clear the input bar — the acceptance side of submit (the bar itself
        never clears; a refused submit keeps the typed text)."""
        with contextlib.suppress(Exception):
            self.query_one(InputBar).text = ""

    def _update_model_label(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one(AppHeader).set_model(self.core.model)

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
        self._cancel_stream_worker()
        old_id = self.core.conversation_id
        node = self.core.new_conversation()
        logger.info("new conversation | old_id=%s", old_id)
        self._reset_transient_ui()
        message_list = self.query_one(MessageList)
        for child in list(message_list.children):
            await child.remove()
        await message_list.add_node(node)
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
        self._cancel_stream_worker()
        nodes = self.core.resume_conversation(result)
        self._reset_transient_ui()
        # Rebuild in a single reconcile pass (not a per-node add_node loop): each
        # add_node rebuilds every separator and scrolls to the end, so mounting a
        # whole conversation one node at a time reflowed the pane N times and read
        # as a settling animation. reconcile mounts the rows once, places the
        # separators once, and scrolls once.
        await self._rebuild_message_list()
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

    @work(name="handle_import")
    async def _handle_import_command(self) -> None:
        """`/import`: pick one file, snapshot it, and open the draft editor so the
        AI can extract from it (ctx0 §4.2). The raw file is read once here and
        held on ``_import_source``; only the edited extract will reach the model.

        Uses the single-select ``ImportScreen``: import condenses exactly one
        file, so the picker returns one path (highlight + Enter) — there is no
        multi-select to reconcile."""
        files = self._workspace.list_files()
        if not files:
            await self._hint("No files in .ctx/context/ to import.")
            return
        path = await self.push_screen_wait(ImportScreen(self._workspace))
        if not path:
            return
        try:
            source = self.core.read_file(path)
        except (OSError, ValueError) as exc:
            await self._hint(f"Could not read {path}: {exc}")
            return
        if not source.strip():
            await self._hint(f"{path} is empty — nothing to import.")
            return
        self._open_import_editor(path, source)
        logger.info("import started | path=%s", path)

    # --- streaming ------------------------------------------------------

    # AIDEV-NOTE: exit_on_error=False — a provider/build failure must surface as
    # the worker's ERROR state (mapped to end_turn(error=…) at the convergence
    # point), not crash the app. The worker body handles no endings itself.
    @work(name="stream_response", exit_on_error=False)
    async def _stream_response(self, assistant_node: Node) -> None:
        message_list = self.query_one(MessageList)
        inspector = self.query_one(DetailInspector)
        usage_gen_before = self.core.usage_generation
        async for _token in self.core.stream(assistant_node):
            message_list.update_content(assistant_node.id, assistant_node.content)
            self._stream_to_inspector(inspector, assistant_node)
        logger.info("response finalized | length=%d", len(assistant_node.content))
        if self.core.usage_generation != usage_gen_before:
            # This turn produced a fresh provider anchor: the gauge is now
            # exact for the current node set. Remember it so a later change
            # (a /include before the next turn) re-marks the gauge stale.
            self._gauge_anchor = self._node_signature()

    def _stream_to_inspector(self, inspector: DetailInspector, node: Node) -> None:
        """Render the live stream into the left pane only when it is locked to
        this streaming node (so navigating away in Edit mode is not hijacked)."""
        state = inspector.node_state
        if state is not None and state.node_id == node.id:
            inspector.append_stream(node.content)

    def action_cancel_stream(self) -> None:
        # Ctrl+C escalation ladder: a live stream, then a live draft, then the
        # app. Cancelling work must always win over quitting (review §cluster).
        if self._stream_worker and not self._stream_worker.is_finished:
            self._stream_worker.cancel()
        elif self._draft_worker and not self._draft_worker.is_finished:
            self._draft_worker.cancel()
        else:
            self.exit()

    def _cancel_stream_worker(self) -> None:
        """Cancel a live turn worker before abandoning its conversation.

        /new and /resume call this so the worker stops burning tokens; its
        terminal CANCELLED still reaches on_worker_state_changed, where the
        core's stale-turn guard makes the late end_turn a no-op."""
        if self._stream_worker and not self._stream_worker.is_finished:
            self._stream_worker.cancel()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """The single convergence point where a turn ends (review §Turn
        lifecycle): Textual fires this on ALL terminal transitions — SUCCESS,
        ERROR, and CANCELLED *including a cancel before the worker's first
        tick*, which a generator ``finally`` can never observe. Each terminal
        state maps to one ``core.end_turn`` outcome; the durable mark and the
        persist happen there, in the core."""
        if event.worker.name != "stream_response" or event.state not in (
            WorkerState.SUCCESS,
            WorkerState.CANCELLED,
            WorkerState.ERROR,
        ):
            return
        self._stream_worker = None
        node = self._streaming_node
        self._streaming_node = None
        if node is None:
            return
        if event.state is WorkerState.CANCELLED:
            self.core.end_turn(node, cancelled=True)
        elif event.state is WorkerState.ERROR:
            self.core.end_turn(node, error=str(event.worker.error))
            logger.error("stream error | error=%s", event.worker.error)
        else:
            self.core.end_turn(node)
        # Re-render the row from the node's now-durable state (error/interrupted
        # marks come from meta, never one-shot widget text).
        self.query_one(MessageList).refresh_ending(node.id)
        if event.state is WorkerState.CANCELLED and node.content == "":
            # A zero-token cancel leaves an empty assistant node at the tip
            # rendered as a phantom ▌ row — drop it (task 48). A partial
            # stream (any tokens) is left exactly as-is. A view decision,
            # deliberately outside end_turn.
            self._drop_interrupted_node(node)
        # The assistant node now carries its full text — its weight (and the
        # context-basis share of every other node) only just became real.
        self._refresh_token_ui()

    @work(name="drop_interrupted", exit_on_error=False)
    async def _drop_interrupted_node(self, node: Node) -> None:
        """Retire a zero-token interrupted assistant node from the live view.

        Rewinds the active tip back to the node's preceding user turn via the
        core ``rewind`` — append-only, so the empty node lingers as an invisible
        abandoned tail, never a hard delete — then reconciles the message list so
        the phantom ``▌`` row disappears and the tip is back at the user turn."""
        if node.prev_id is None:
            return
        if all(n.id != node.id for n in self.core.nodes):
            # Stale turn: /new or /resume already replaced the line this node
            # lived on — there is nothing on screen to retire, and rewinding
            # would target the wrong conversation.
            return
        self.core.rewind(node.prev_id)
        await self._rebuild_message_list()
        self._refresh_token_ui()
