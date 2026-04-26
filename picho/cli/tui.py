"""picho chat TUI.

Hermes-style terminal chat UI built on prompt_toolkit + rich.

This tui implementation is inspired by hermes-agent:
https://github.com/nousresearch/hermes-agent

Design:
- A single prompt_toolkit ``Application`` owns the bottom region:
  input composer + status bar + optional confirmation bar.
- Everything else (banner, streaming assistant output, tool activity,
  system messages) is streamed as ANSI text via ``patch_stdout`` +
  ``print_formatted_text(ANSI(...))`` so the input area stays pinned
  at the bottom.
- The runner's event subscription drives rendering. Streaming deltas
  are appended in-place on the current line (no widget replacement),
  terminated on ``message_end``/``turn_end``.
- ChatTUI keeps the same public API as before (``await chat_tui.run()``),
  so cli/chat.py does not need to change.
"""

from __future__ import annotations

import asyncio
import io
import shutil
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from prompt_toolkit import print_formatted_text
from prompt_toolkit.application import Application
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    ConditionalContainer,
    FormattedTextControl,
    HSplit,
    Layout,
    Window,
    VSplit,
)
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.widgets import TextArea
from rich.console import Console
from rich.panel import Panel
from rich.text import Text as RichText

from ..agent import AgentEvent
from ..logger import get_logger, log_exception
from ..runner import Runner, SessionState
from .config import CLIConfig, format_for_display
from .confirmation import ConfirmationManager, ConfirmationRequest

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Theme (hermes-style default skin; extension point kept for future skins)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Theme:
    gold: str = "#FFD700"
    amber: str = "#FFBF00"
    bronze: str = "#CD7F32"
    dark_gold: str = "#B8860B"
    cornsilk: str = "#FFF8DC"
    dim: str = "#8B8682"
    label: str = "#DAA520"
    ok: str = "#8FBC8F"
    warn: str = "#FFD700"
    error: str = "#FF6B6B"
    muted: str = "#C0C0C0"
    panel_border: str = "#CD7F32"
    response_border: str = "#FFD700"
    status_bar_bg: str = "#1A1A2E"


THEME = Theme()


# ---------------------------------------------------------------------------
# ANSI helpers (direct ANSI avoids rich.Live/full-screen state management)
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _fg(hex_color: str, *, bold: bool = False) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    prefix = "\033[1;" if bold else "\033[0;"
    return f"{prefix}38;2;{r};{g};{b}m"


RESET = "\033[0m"
DIM = "\033[2m"


def ansi(text: str, hex_color: str, *, bold: bool = False) -> str:
    return f"{_fg(hex_color, bold=bold)}{text}{RESET}"


def cprint(text: str) -> None:
    """Print an ANSI-colored line through prompt_toolkit's renderer."""
    print_formatted_text(ANSI(text))


# ---------------------------------------------------------------------------
# Banner (rich Panel rendered once to ANSI at startup)
# ---------------------------------------------------------------------------


def _render_banner(session_id: str, model_name: str, workspace: str) -> str:
    """Render the startup banner as ANSI text via rich."""
    workspace_path = Path(workspace) if workspace else Path("-")
    workspace_label = workspace_path.name or str(workspace_path)

    width = max(60, min(shutil.get_terminal_size((100, 24)).columns - 2, 110))
    console = Console(
        file=io.StringIO(),
        force_terminal=True,
        color_system="truecolor",
        width=width,
        legacy_windows=False,
    )

    body = RichText()
    body.append("⚕ picho chat", style=f"bold {THEME.gold}")
    body.append("   ")
    body.append("Hermes-style coding terminal", style=f"italic {THEME.dim}")
    body.append("\n")
    body.append("model ", style=THEME.label)
    body.append(model_name, style=THEME.cornsilk)
    body.append("   │   ", style=THEME.bronze)
    body.append("session ", style=THEME.label)
    body.append(session_id[:12], style=THEME.dim)
    body.append("\n")
    body.append("workspace ", style=THEME.label)
    body.append(workspace_label, style=THEME.cornsilk)
    body.append("   │   ", style=THEME.bronze)
    body.append(str(workspace_path), style=THEME.dim)
    body.append("\n\n")
    body.append(
        "Type your message, use /help for commands, Ctrl+C to abort, Ctrl+D to quit.",
        style=THEME.dim,
    )

    panel = Panel(
        body,
        border_style=THEME.panel_border,
        padding=(0, 2),
        title=RichText(" Messenger of the Code ", style=f"bold {THEME.amber}"),
        subtitle=RichText(session_id, style=THEME.dim),
        subtitle_align="right",
    )
    console.print(panel)
    return console.file.getvalue()


# ---------------------------------------------------------------------------
# Chat application
# ---------------------------------------------------------------------------


class ChatApp:
    """Hermes-style chat TUI driven by runner events.

    Rendering model:
    - Scrollback (assistant text, tool activity, system messages, errors)
      is streamed as ANSI to stdout via ``patch_stdout``.
    - The bottom-pinned region is a prompt_toolkit Application with:
        * a single-line status bar
        * a confirmation prompt bar (visible only in confirmation mode)
        * a TextArea input composer
    """

    def __init__(
        self,
        runner: Runner,
        session_id: str,
        config: CLIConfig,
        confirmation_manager: ConfirmationManager | None = None,
    ):
        self.runner = runner
        self.session_id = session_id
        self.config = config
        self.confirmation_manager = confirmation_manager

        self.running = True
        self._loop: asyncio.AbstractEventLoop | None = None
        self._unsubscribe: Callable[[], None] | None = None

        # Streaming state
        # We stream by *line*: accumulate incoming deltas in _stream_buf and
        # only print through prompt_toolkit once a newline arrives (or the
        # message ends). Directly writing partial lines to stdout under
        # ``patch_stdout`` is unsafe — prompt_toolkit redraws the bottom
        # region on every flush and may swallow unterminated lines.
        self._stream_kind: str | None = None  # "thinking" | "assistant" | None
        self._stream_buf: str = ""
        self._stream_segment_has_output: bool = False
        # Whether a ``╭─ picho ─...─╮`` top bar has been printed for the
        # current assistant turn but the matching bottom bar hasn't been
        # printed yet. Used to group thinking + content inside one frame.
        self._assistant_frame_open: bool = False
        # Tracks which kinds we have already shown inside the current
        # assistant frame. When ``thinking`` is followed by ``assistant``
        # we insert a thin divider between them.
        self._frame_kinds_seen: set[str] = set()
        self._output_lock = threading.Lock()

        # Confirmation state
        self._pending_confirmation: ConfirmationRequest | None = None
        self._confirmation_mode = False

        # prompt_toolkit UI
        self._kb = KeyBindings()
        self._input = TextArea(
            height=Dimension(min=1, max=8),
            prompt=self._input_prompt,
            multiline=True,
            wrap_lines=True,
            accept_handler=self._on_accept,
            history=InMemoryHistory(),
            style=f"fg:{THEME.cornsilk}",
        )

        self._status_control = FormattedTextControl(
            text=self._build_status_fragments, focusable=False
        )
        self._confirm_control = FormattedTextControl(
            text=self._build_confirmation_fragments, focusable=False
        )

        self._bind_keys()

        layout = Layout(
            HSplit(
                [
                    # Confirmation bar (only visible during confirmation mode)
                    ConditionalContainer(
                        Window(
                            content=self._confirm_control,
                            height=1,
                            style=f"bg:{THEME.status_bar_bg}",
                        ),
                        filter=Condition(lambda: self._confirmation_mode),
                    ),
                    # Status bar
                    Window(
                        content=self._status_control,
                        height=1,
                        style=f"bg:{THEME.status_bar_bg}",
                    ),
                    # Input composer
                    VSplit(
                        [
                            Window(
                                width=2,
                                content=FormattedTextControl(
                                    text=lambda: [("", "")],
                                ),
                            ),
                            self._input,
                        ]
                    ),
                ]
            ),
            focused_element=self._input,
        )

        self._app: Application = Application(
            layout=layout,
            key_bindings=self._kb,
            full_screen=False,
            mouse_support=False,
            editing_mode=EditingMode.EMACS,
        )

    # ---- prompt_toolkit callbacks --------------------------------------

    def _input_prompt(self) -> FormattedText:
        symbol = "› " if not self._confirmation_mode else "? "
        color = THEME.gold if not self._confirmation_mode else THEME.warn
        return FormattedText([(f"bold fg:{color}", symbol)])

    def _build_status_fragments(self) -> FormattedText:
        state = self.runner.get_session(self.session_id)
        model_name = "unknown"
        workspace = "-"
        assistant_name = self.config.chat.assistant_name or "picho"
        if state:
            model = state.agent.state.model
            model_name = getattr(model, "model_name", "unknown")
            workspace = state.workspace or "-"

        is_streaming = self.runner.is_streaming(self.session_id)
        has_queued = self.runner.has_queued_messages(self.session_id)
        workspace_label = Path(workspace).name or workspace

        sep = (f"fg:{THEME.bronze}", " │ ")
        fragments: list[tuple[str, str]] = [
            (f"fg:{THEME.bronze}", " ─ "),
            (f"bold fg:{THEME.gold}", assistant_name),
            sep,
            (f"fg:{THEME.cornsilk}", model_name),
            sep,
            (f"fg:{THEME.dim}", self.session_id[:12]),
            sep,
            (f"fg:{THEME.label}", workspace_label),
        ]
        if is_streaming:
            fragments += [sep, (f"bold fg:{THEME.ok}", "● STREAMING")]
        if has_queued:
            fragments += [sep, (f"bold fg:{THEME.warn}", "◆ QUEUED")]
        fragments += [
            sep,
            (
                f"fg:{THEME.dim}",
                "Enter send · Alt+Enter newline · Ctrl+C abort · Ctrl+D quit",
            ),
        ]
        return FormattedText(fragments)

    def _build_confirmation_fragments(self) -> FormattedText:
        title = self._pending_confirmation.title if self._pending_confirmation else ""
        return FormattedText(
            [
                (f"fg:{THEME.bronze}", " ─ "),
                (f"bold fg:{THEME.warn}", "CONFIRM"),
                (f"fg:{THEME.bronze}", " │ "),
                (f"fg:{THEME.cornsilk}", title[:60]),
                (f"fg:{THEME.bronze}", " │ "),
                (f"fg:{THEME.ok}", "[y] approve"),
                (f"fg:{THEME.bronze}", "  "),
                (f"fg:{THEME.error}", "[n] reject"),
                (f"fg:{THEME.bronze}", "  "),
                (f"fg:{THEME.dim}", "Ctrl+C reject"),
            ]
        )

    def _bind_keys(self) -> None:
        kb = self._kb

        @kb.add("c-c")
        def _(event) -> None:
            if self._confirmation_mode:
                self._handle_confirmation_reject()
                return
            if self.runner.is_streaming(self.session_id):
                self.runner.abort(self.session_id)
                self._emit_system("Aborted current streaming")
            else:
                self._emit_system("Press Ctrl+D to quit")

        @kb.add("c-d")
        def _(event) -> None:
            self.running = False
            event.app.exit()

        # Enter: submit the current input.
        #
        # With ``TextArea(multiline=True)`` the default Enter handler
        # inserts a newline (no auto-submit). We override Enter to run
        # the accept_handler, matching hermes' Enter-to-send convention.
        @kb.add("enter")
        def _(event) -> None:
            buf = event.current_buffer
            if not self._on_accept(buf):
                # ``_on_accept`` already consumed the text; nothing else
                # to do. Returning False keeps the buffer empty.
                pass

        # Alt+Enter / Ctrl+J / Ctrl+Enter → insert a newline.
        #
        # Most terminals do NOT distinguish Shift+Enter from Enter at
        # the byte level, so we can't reliably bind Shift+Enter. Users
        # who want "Shift+Enter = newline" can configure their terminal
        # to send ESC+Enter (e.g. iTerm2 "Natural Text Editing") which
        # arrives here as escape+enter, or simply use Alt+Enter / Ctrl+J.
        @kb.add("escape", "enter")
        @kb.add("c-j")
        def _(event) -> None:
            event.current_buffer.insert_text("\n")

        # Quick y/n keys while in confirmation mode and input is empty
        @kb.add("y", filter=Condition(lambda: self._confirmation_mode))
        def _(event) -> None:
            if not self._input.text:
                self._handle_confirmation_approve()
            else:
                event.app.current_buffer.insert_text("y")

        @kb.add("n", filter=Condition(lambda: self._confirmation_mode))
        def _(event) -> None:
            if not self._input.text:
                self._handle_confirmation_reject()
            else:
                event.app.current_buffer.insert_text("n")

    def _on_accept(self, buff) -> bool:
        text = buff.text
        buff.reset()
        if not text:
            return False
        if self._confirmation_mode:
            self._handle_confirmation_input(text)
        else:
            self._process_input(text)
        return False

    # ---- output helpers ------------------------------------------------

    def _emit(self, text: str) -> None:
        """Write an ANSI line to scrollback, safely from any thread."""
        with self._output_lock:
            try:
                cprint(text)
            except Exception:
                # Fallback: plain write
                print(text, flush=True)

    # ---- streaming helpers --------------------------------------------
    #
    # Why line-buffered instead of raw writes?
    #
    # prompt_toolkit's ``patch_stdout`` collects whatever is written to
    # ``sys.stdout`` and re-emits it *above* the persistent bottom region
    # on each render tick. A partial line (no trailing ``\n``) stays in
    # an internal buffer and can be visually overwritten when the bottom
    # region refreshes, which manifests as "only the last few characters
    # survived" — exactly the drop we saw with doubao's token-by-token
    # streaming. By buffering until a newline arrives we only ever hand
    # prompt_toolkit complete lines, which are always safe to re-emit.

    def _stream_prefix_head(self, kind: str) -> str:
        # Inside an assistant frame, streaming lines have no left gutter —
        # the ``╭─ picho ─...─╮`` top bar already marks the block, and
        # content is allowed to use the full width. Thinking lines get a
        # faint ``⋯`` on the first line only, as a visual hint.
        if kind == "thinking":
            return ansi("⋯ ", THEME.dim)
        return ""

    def _stream_prefix_cont(self, kind: str) -> str:
        if kind == "thinking":
            return ansi("  ", THEME.dim)
        return ""

    def _stream_body_color(self, kind: str) -> str:
        return THEME.dim if kind == "thinking" else THEME.cornsilk

    def _print_stream_line(self, kind: str, body: str, *, is_head: bool) -> None:
        prefix = (
            self._stream_prefix_head(kind)
            if is_head
            else self._stream_prefix_cont(kind)
        )
        color = self._stream_body_color(kind)
        self._emit(f"{prefix}{ansi(body, color)}")

    def _flush_stream(self, *, close: bool) -> None:
        """Emit any buffered partial stream line.

        When ``close`` is True we finalize the current stream segment:
        the trailing partial line (if any) is printed as a complete line
        and internal state is reset so the next delta starts a fresh
        prefixed block.
        """
        if self._stream_kind is None:
            return
        kind = self._stream_kind
        buf = self._stream_buf
        if buf:
            # Emit any completed lines first. This happens when the last
            # delta contained a newline mid-string; those lines would
            # already have been printed by ``_append_stream_delta`` — so
            # here ``buf`` is always the "current incomplete line".
            # When closing, treat it as a full final line.
            if close:
                # Head vs. cont is derived from whether *this* segment has
                # already printed at least one line.
                self._print_stream_line(
                    kind, buf, is_head=not self._stream_segment_has_output
                )
                self._stream_buf = ""
        if close:
            self._stream_kind = None
            self._stream_buf = ""
            self._stream_segment_has_output = False

    def _append_stream_delta(self, kind: str, delta: str) -> None:
        """Feed one streaming delta into the line buffer.

        - Switches segment if ``kind`` changes (flushes previous kind).
        - Any complete lines (terminated by ``\\n``) are printed through
          ``print_formatted_text`` so ``patch_stdout`` sees whole lines.
        - A trailing partial line stays in ``_stream_buf`` and will be
          printed on the next newline, the next kind switch, or when
          ``_flush_stream(close=True)`` is called at message/turn end.
        - When the assistant frame isn't open yet, the first delta of a
          turn opens it with the ``╭─ picho ─...─╮`` top bar. When the
          kind changes *within* an already-open frame (typically from
          ``thinking`` to ``assistant``), a thin divider is drawn so the
          two segments are visually separated.
        """
        if not delta:
            return
        if self._stream_kind is not None and self._stream_kind != kind:
            self._flush_stream(close=True)
        # Ensure the frame is open and decide whether a divider is needed
        # before starting the new segment.
        if not self._assistant_frame_open:
            self._open_assistant_frame()
        if kind not in self._frame_kinds_seen and self._frame_kinds_seen:
            # Moving into a new kind inside the same frame — draw a divider.
            self._draw_frame_divider()

        if self._stream_kind is None:
            self._stream_kind = kind
            self._stream_buf = ""
            self._stream_segment_has_output = False

        self._frame_kinds_seen.add(kind)
        self._stream_buf += delta
        # Emit every complete line we now have.
        while True:
            idx = self._stream_buf.find("\n")
            if idx < 0:
                break
            line = self._stream_buf[:idx]
            self._stream_buf = self._stream_buf[idx + 1 :]
            self._print_stream_line(
                kind, line, is_head=not self._stream_segment_has_output
            )
            self._stream_segment_has_output = True

    def _close_streaming_line(self) -> None:
        """Finalize any in-progress streaming output."""
        self._flush_stream(close=True)

    # ---- assistant frame (top/bottom bars around a turn) ---------------

    def _frame_width(self) -> int:
        try:
            cols = shutil.get_terminal_size((100, 24)).columns
        except Exception:
            cols = 100
        return max(40, min(cols, 120))

    def _open_assistant_frame(self) -> None:
        """Print the ``╭─ picho ─...─╮`` top bar for a fresh assistant turn."""
        if self._assistant_frame_open:
            return
        name = self.config.chat.assistant_name or "picho"
        width = self._frame_width()
        # "╭─ picho ─" + fill "─" + "─╮"
        head = f"╭─ {name} ─"
        tail = "─╮"
        fill = "─" * max(1, width - len(head) - len(tail))
        bar = head + fill + tail
        self._emit(ansi(bar, THEME.response_border, bold=True))
        self._assistant_frame_open = True
        self._frame_kinds_seen = set()

    def _close_assistant_frame(self, usage_text: str | None = None) -> None:
        """Print the ``╰─ ... tokens ─╯`` bottom bar if a frame is open."""
        if not self._assistant_frame_open:
            return
        width = self._frame_width()
        head = "╰─"
        tail = "─╯"
        if usage_text:
            middle = f"─ {usage_text} ─"
            fill_len = max(1, width - len(head) - len(middle) - len(tail))
            bar = head + "─" * fill_len + middle + tail
        else:
            fill = "─" * max(1, width - len(head) - len(tail))
            bar = head + fill + tail
        self._emit(ansi(bar, THEME.response_border, bold=True))
        self._assistant_frame_open = False
        self._frame_kinds_seen = set()

    def _draw_frame_divider(self) -> None:
        """A dashed divider used between thinking and content inside a frame."""
        width = self._frame_width()
        bar = ("╌" * ((width + 1) // 2))[:width]
        self._emit(ansi(bar, THEME.bronze))

    def _format_usage(self, usage: Any) -> str | None:
        """Build a compact ``tokens in=X out=Y cache=Z`` suffix string.

        Returns ``None`` when no usage info is available. Falls back to
        individual attributes if a field is missing — different providers
        expose slightly different shapes (e.g. some lack cache_* fields).
        """
        if usage is None:
            return None
        try:
            in_t = int(getattr(usage, "input_tokens", 0) or 0)
            out_t = int(getattr(usage, "output_tokens", 0) or 0)
            cache_r = int(getattr(usage, "cache_read", 0) or 0)
            cache_w = int(getattr(usage, "cache_write", 0) or 0)
        except Exception:
            return None
        if in_t == 0 and out_t == 0 and cache_r == 0 and cache_w == 0:
            return None
        parts = [f"in={in_t}", f"out={out_t}"]
        if cache_r or cache_w:
            parts.append(f"cache r={cache_r} w={cache_w}")
        return "tokens " + " ".join(parts)

    # ---- plain emitters ------------------------------------------------

    def _emit_user(self, text: str) -> None:
        self._close_streaming_line()
        self._close_assistant_frame()
        prefix = ansi("● ", THEME.amber, bold=True)
        for i, line in enumerate(text.splitlines() or [""]):
            cont = prefix if i == 0 else ansi("  ", THEME.amber)
            self._emit(f"{cont}{ansi(line, THEME.cornsilk)}")

    def _emit_system(self, text: str) -> None:
        self._close_streaming_line()
        self._close_assistant_frame()
        prefix = ansi("│ ", THEME.bronze)
        for i, line in enumerate(text.splitlines() or [""]):
            cont = prefix if i == 0 else ansi("  ", THEME.bronze)
            self._emit(f"{cont}{ansi(line, THEME.dark_gold)}")

    def _emit_error(self, text: str) -> None:
        self._close_streaming_line()
        self._close_assistant_frame()
        prefix = ansi("✗ ", THEME.error, bold=True)
        for i, line in enumerate(text.splitlines() or [""]):
            cont = prefix if i == 0 else ansi("  ", THEME.error)
            self._emit(f"{cont}{ansi(line, THEME.error)}")

    def _emit_assistant_full(self, text: str) -> None:
        """Render a complete assistant message (used when replaying history)."""
        self._close_streaming_line()
        self._close_assistant_frame()
        self._open_assistant_frame()
        for line in text.splitlines() or [""]:
            self._emit(ansi(line, THEME.cornsilk))
        self._close_assistant_frame()

    def _emit_tool_call(self, title: str, details: str | None, error: bool) -> None:
        self._close_streaming_line()
        self._close_assistant_frame()
        color = THEME.error if error else THEME.amber
        body_color = THEME.error if error else THEME.cornsilk
        self._emit(f"{ansi('┊ ', color)}{ansi(title, body_color, bold=True)}")
        if details:
            for line in details.splitlines():
                self._emit(f"{ansi('  ', color)}{ansi(line, THEME.dim)}")

    def _emit_confirmation_result(self, approved: bool, title: str) -> None:
        self._close_streaming_line()
        self._close_assistant_frame()
        if approved:
            mark = ansi("✓ ", THEME.ok, bold=True)
            self._emit(f"{mark}{ansi('Approved: ' + title, THEME.cornsilk)}")
        else:
            mark = ansi("✗ ", THEME.error, bold=True)
            self._emit(f"{mark}{ansi('Rejected: ' + title, THEME.cornsilk)}")

    # ---- confirmation handling -----------------------------------------

    def _show_confirmation_request(self, request: ConfirmationRequest) -> None:
        self._pending_confirmation = request
        self._confirmation_mode = True
        self._close_streaming_line()

        self._emit(
            f"{ansi('! ', THEME.warn, bold=True)}{ansi(request.title, THEME.cornsilk, bold=True)}"
        )
        for line in (request.message or "").splitlines():
            self._emit(f"{ansi('  ', THEME.dark_gold)}{ansi(line, THEME.muted)}")
        self._emit(
            f"{ansi('  ', THEME.dark_gold)}"
            f"{ansi('[y] approve   [n] reject   Ctrl+C reject', THEME.dim)}"
        )
        self._request_refresh()

    def _handle_confirmation_approve(self) -> None:
        if self._pending_confirmation:
            title = self._pending_confirmation.title
            self._pending_confirmation.approve()
            self._emit_confirmation_result(True, title)
            self._pending_confirmation = None
            self._confirmation_mode = False
            self._request_refresh()

    def _handle_confirmation_reject(self) -> None:
        if self._pending_confirmation:
            title = self._pending_confirmation.title
            self._pending_confirmation.reject()
            self._emit_confirmation_result(False, title)
            self._pending_confirmation = None
            self._confirmation_mode = False
            self._request_refresh()

    def _handle_confirmation_input(self, text: str) -> None:
        t = text.strip().lower()
        if t in ("y", "yes"):
            self._handle_confirmation_approve()
        elif t in ("n", "no"):
            self._handle_confirmation_reject()
        else:
            self._emit_system("Please answer 'y' or 'n'")

    # ---- user input dispatch -------------------------------------------

    def _process_input(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if text.startswith("/"):
            self._handle_command(text)
        else:
            loop = self._loop or asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(self._handle_message(text), loop)

    def _handle_command(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=2)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else None

        if command in ("/quit", "/q"):
            self.running = False
            self._app.exit()
            return

        if command == "/abort":
            if self.runner.is_streaming(self.session_id):
                self.runner.abort(self.session_id)
                self._emit_system("Aborted current streaming")
            else:
                self._emit_system("No active streaming to abort")
            return

        if command == "/new":
            self.session_id = self.runner.create_session()
            self._subscribe_current()
            self._emit_system(f"Created session: {self.session_id}")
            self._request_refresh()
            return

        if command == "/sessions":
            limit = None
            if args:
                try:
                    limit = int(args)
                except ValueError:
                    limit = None
            sessions = self.runner.list_persisted_sessions(limit)
            if not sessions:
                self._emit_system("No sessions found")
                return
            lines = [f"Sessions (showing {len(sessions)}):"]
            for s in sessions:
                mark = " *" if s["session_id"] == self.session_id else ""
                first = (s.get("first_message") or "")[:50]
                if len(s.get("first_message") or "") > 50:
                    first += "..."
                lines.append(f"  {s['session_id']}{mark}")
                lines.append(f"    Messages: {s['message_count']}, First: {first}")
            self._emit_system("\n".join(lines))
            return

        if command == "/checkout":
            if not args:
                self._emit_system("Usage: /checkout <session_id>")
                return
            target_id = args.strip()
            if self.runner.has_session(target_id):
                self.session_id = target_id
                self._subscribe_current()
                self._emit_system(f"Switched to session: {target_id}")
                self._request_refresh()
                return
            sessions = self.runner.list_persisted_sessions()
            session_file = next(
                (s["session_file"] for s in sessions if s["session_id"] == target_id),
                None,
            )
            if not session_file:
                self._emit_system(f"Session not found: {target_id}")
                return
            try:
                self.session_id = self.runner.load_session(session_file)
                self._subscribe_current()
                state = self.runner.get_session(self.session_id)
                if state:
                    for entry in state.session.get_entries():
                        msg = getattr(entry, "message", None)
                        if not msg:
                            continue
                        role = msg.get("role", "unknown")
                        if role == "user":
                            self._emit_user(
                                self._extract_text_content(msg.get("content", ""))
                            )
                        elif role == "assistant":
                            err = msg.get("error_message")
                            if err:
                                self._emit_error(err)
                            else:
                                self._emit_assistant_full(
                                    self._extract_text_content(msg.get("content", ""))
                                )
                self._emit_system(f"Loaded session: {target_id}")
                self._request_refresh()
            except Exception as e:
                self._emit_system(f"Failed to load session: {e}")
            return

        if command == "/agent":
            state: SessionState | None = self.runner.get_session(self.session_id)
            if state:
                agent = state.agent
                model = agent.state.model
                lines = [
                    "Current agent info:",
                    f"  Model: {getattr(model, 'model_name', 'N/A')}",
                    f"  Streaming: {agent.state.is_streaming}",
                    f"  Has Queued: {agent.has_queued_messages()}",
                ]
                self._emit_system("\n".join(lines))
            return

        if command == "/help":
            self._emit_system(
                "Commands:\n"
                "  /quit, /q        - Exit\n"
                "  /abort           - Abort current streaming\n"
                "  /new             - Create new session\n"
                "  /sessions [n]    - List sessions (last n)\n"
                "  /checkout <id>   - Switch to session\n"
                "  /agent           - Show agent info\n"
                "  /help            - Show this help\n\n"
                "Input keys:\n"
                "  Enter            - Send\n"
                "  Alt+Enter / Ctrl+J - Insert newline (multi-line input)\n"
                "  Ctrl+C           - Abort streaming / reject confirmation\n"
                "  Ctrl+D           - Quit\n\n"
                "During streaming:\n"
                "  Normal input = steer (interrupt)\n"
                "  > prefix = follow-up (after current turn)"
            )
            return

        self._emit_system(f"Unknown command: {command}")

    async def _handle_message(self, message: str) -> None:
        is_follow_up = message.startswith(">")
        if is_follow_up:
            message = message[1:].strip()

        is_streaming = self.runner.is_streaming(self.session_id)
        if not is_streaming:
            self._emit_user(message)

        try:
            if is_streaming:
                if is_follow_up:
                    self.runner.follow_up(self.session_id, message)
                    self._emit_system("Follow-up queued")
                else:
                    self.runner.steer(self.session_id, message)
                    self._emit_user(message + " [steering]")
            else:
                await self.runner.prompt(self.session_id, message)
        except Exception as e:
            log_exception(_log, "Failed to send message", e)
            self._emit_error(f"Error: {e}\n{traceback.format_exc()}")
        finally:
            self._request_refresh()

    # ---- runner event subscription -------------------------------------

    def _extract_text_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    texts.append(c.get("text", ""))
                elif hasattr(c, "text"):
                    texts.append(c.text)
            return " ".join(texts)
        return str(content)

    def _subscribe_current(self) -> None:
        if self._unsubscribe:
            try:
                self._unsubscribe()
            except Exception:
                pass
            self._unsubscribe = None

        config = self.config

        def on_event(event: AgentEvent) -> None:
            try:
                etype = event.type

                if etype == "thinking_delta":
                    if not config.chat.show_thinking:
                        return
                    delta = self._delta_from_event(event)
                    if not delta:
                        return
                    self._append_stream_delta("thinking", delta)

                elif etype == "content_delta":
                    delta = self._delta_from_event(event)
                    if not delta:
                        return
                    self._append_stream_delta("assistant", delta)

                elif etype == "message_end" and event.message:
                    # Flush any buffered streaming text, then close the
                    # assistant frame with a token-usage subtitle.
                    self._close_streaming_line()
                    role = getattr(event.message, "role", "")
                    if role == "assistant":
                        err = getattr(event.message, "error_message", None)
                        usage_text = self._format_usage(
                            getattr(event.message, "usage", None)
                        )
                        self._close_assistant_frame(usage_text=usage_text)
                        if err:
                            self._emit_error(err)
                    else:
                        # Non-assistant message_end — make sure no stray
                        # frame stays open.
                        self._close_assistant_frame()

                elif etype == "tool_execution_start":
                    if not config.chat.show_tool_execution:
                        return
                    tool_name = getattr(event, "tool_name", "unknown")
                    details = None
                    if config.chat.show_tool_args != "off":
                        args = getattr(event, "args", {})
                        if args:
                            import json

                            args_str = json.dumps(args, ensure_ascii=False)
                            shown = format_for_display(
                                args_str, config.chat.show_tool_args, max_chars=120
                            )
                            if shown:
                                details = f"Args: {shown}"
                    self._emit_tool_call(
                        f"Tool call: {tool_name}", details, error=False
                    )

                elif etype == "tool_execution_end":
                    if (
                        not config.chat.show_tool_execution
                        or config.chat.show_tool_result == "off"
                    ):
                        return
                    result = getattr(event, "result", None)
                    if not result:
                        return
                    is_error = bool(getattr(result, "is_error", False))
                    content = getattr(result, "content", None)
                    if not content or not hasattr(content, "__iter__"):
                        return
                    texts = [
                        getattr(item, "text", "")
                        for item in content
                        if hasattr(item, "text")
                    ]
                    if not texts:
                        return
                    result_str = "\n".join(t for t in texts if t)
                    if is_error:
                        shown = result_str
                    else:
                        shown = format_for_display(
                            result_str, config.chat.show_tool_result, max_chars=500
                        )
                    if shown:
                        label = "Tool error" if is_error else "Tool result"
                        self._emit_tool_call(label, shown, error=is_error)

                elif etype == "turn_end":
                    # Safety net: close any stray frame that didn't get
                    # closed via ``message_end`` (e.g. abort / error).
                    self._close_streaming_line()
                    if self._assistant_frame_open:
                        self._close_assistant_frame()

                self._request_refresh()
            except Exception as exc:
                log_exception(_log, f"Error handling event {event.type}", exc)

        self._unsubscribe = self.runner.subscribe(self.session_id, on_event)
        self._request_refresh()

    @staticmethod
    def _delta_from_event(event: AgentEvent) -> str:
        assistant_event = getattr(event, "assistant_event", None)
        if not assistant_event:
            return ""
        data = getattr(assistant_event, "data", None)
        if not data:
            return ""
        return getattr(data, "delta", "") or ""

    # ---- lifecycle -----------------------------------------------------

    def _request_refresh(self) -> None:
        try:
            self._app.invalidate()
        except Exception:
            pass

    async def _ticker(self) -> None:
        """Periodic status-bar refresh (streaming/queued indicators)."""
        while self.running:
            await asyncio.sleep(0.2)
            self._request_refresh()

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()

        # Print banner (once, before the Application takes the screen).
        state = self.runner.get_session(self.session_id)
        model_name = "unknown"
        workspace = "-"
        if state:
            model = state.agent.state.model
            model_name = getattr(model, "model_name", "unknown")
            workspace = state.workspace or "-"
        banner = _render_banner(self.session_id, model_name, workspace)
        print(banner, end="", flush=True)

        # Subscribe to runner events and wire confirmation bridge.
        self._subscribe_current()
        if self.confirmation_manager:
            self.confirmation_manager.set_on_request(self._show_confirmation_request)

        self._emit_system(
            "Welcome to picho. Type your message or use /help for commands."
        )

        ticker_task = asyncio.create_task(self._ticker())

        try:
            with patch_stdout(raw=True):
                await self._app.run_async()
        finally:
            self.running = False
            ticker_task.cancel()
            if self._unsubscribe:
                try:
                    self._unsubscribe()
                except Exception:
                    pass
                self._unsubscribe = None


class ChatTUI:
    """Public entry point, kept API-compatible with the previous Textual TUI."""

    def __init__(
        self,
        runner: Runner,
        session_id: str,
        config: CLIConfig,
        confirmation_manager: ConfirmationManager | None = None,
    ):
        self._app = ChatApp(runner, session_id, config, confirmation_manager)

    async def run(self) -> None:
        await self._app.run()
