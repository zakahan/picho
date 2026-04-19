import asyncio
import traceback
from typing import Callable

from textual.app import App, ComposeResult
from textual.widgets import Input, Label, Static
from textual.containers import Vertical
from textual.widget import Widget
from textual import events

from ..runner import Runner, SessionState
from ..agent import AgentEvent
from ..logger import get_logger, log_exception
from .config import CLIConfig, format_for_display
from .confirmation import ConfirmationManager, ConfirmationRequest

_log = get_logger(__name__)


class ChatWidget(Widget):
    DEFAULT_CSS = """
    ChatWidget {
        height: 1fr;
        border: solid black;
        border-title-align: center;
        overflow-y: scroll;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._code_lines: list[str] = []
        self._content = Static("", id="chat-content")
        self.border_title = "Chat (Scroll: Up/Down, Page Up/Down)"

    def compose(self) -> ComposeResult:
        yield self._content

    def update_content(self, text: str) -> None:
        self._content.update(text)


class StatusBar(Widget):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._label = Label("Ready", id="status-label")

    def compose(self) -> ComposeResult:
        yield self._label

    def update_text(self, text: str) -> None:
        self._label.update(text)

    def set_style(self, _is_streaming: bool = False, _is_warning: bool = False) -> None:
        pass


class InputWidget(Widget):
    DEFAULT_CSS = """
    InputWidget {
        height: auto;
        min-height: 3;
        border: solid black;
        border-title-align: center;
    }
    
    InputWidget Input {
        width: 100%;
        height: auto;
        min-height: 1;
        border: none;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._input = Input(placeholder="", id="chat-input")
        self.border_title = "Input (Enter=send, Ctrl+C=abort, Ctrl+D=quit)"

    def compose(self) -> ComposeResult:
        yield self._input

    @property
    def text(self) -> str:
        return self._input.value

    @text.setter
    def text(self, value: str) -> None:
        self._input.value = value

    def focus(self) -> None:
        self._input.focus()


class ChatApp(App):
    CSS = """
    #main-container {
        height: 100%;
        width: 100%;
    }
    
    Vertical {
        height: 100%;
        width: 100%;
    }
    """
    CSS_PATH = None
    TITLE = ""
    SUB_TITLE = ""

    def __init__(
        self,
        runner: Runner,
        session_id: str,
        config: CLIConfig,
        confirmation_manager: ConfirmationManager | None = None,
    ):
        super().__init__(ansi_color=True)
        self.runner = runner
        self.session_id = session_id
        self.config = config
        self.running = True
        self._unsubscribe: Callable | None = None
        self.confirmation_manager = confirmation_manager

        self._code_lines: list[str] = []
        self._in_thinking = False
        self._current_assistant_text = ""
        self._pending_confirmation: ConfirmationRequest | None = None
        self._confirmation_mode = False

    def compose(self) -> ComposeResult:
        with Vertical(id="main-container"):
            yield ChatWidget(id="chat-widget")
            yield StatusBar(id="status-bar")
            yield InputWidget(id="input-widget")

    async def on_mount(self) -> None:
        _log.debug("ChatApp on_mount start")
        self._code_widget = self.query_one("#chat-widget", ChatWidget)
        self._status_bar = self.query_one("#status-bar", StatusBar)
        self._input_widget = self.query_one("#input-widget", InputWidget)
        self._input_widget.focus()
        _log.debug("Widgets initialized")

        self._add_system_message(
            "Welcome to picho!\n"
            "Type your message and press Enter to send.\n"
            "Use /help for available commands."
        )

        _log.debug("Subscribing to current session")
        self._subscribe_current()

        if self.confirmation_manager:
            _log.debug("Setting up confirmation manager callback")
            self.confirmation_manager.set_on_request(self._show_confirmation_request)

        _log.debug("Starting tick task")
        asyncio.create_task(self._tick())
        _log.debug("ChatApp on_mount complete")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        _log.debug(
            f"Input submitted: value_len={len(event.value)} confirmation_mode={self._confirmation_mode}"
        )
        if event.input.id == "chat-input":
            if self._confirmation_mode:
                self._handle_confirmation_input(event.value)
            elif event.value:
                self._process_input(event.value)
                self._input_widget.text = ""

    async def on_key(self, event: events.Key) -> None:
        if event.key == "ctrl+c":
            event.stop()
            if self._confirmation_mode:
                self._handle_confirmation_reject()
            elif self.runner.is_streaming(self.session_id):
                self.runner.abort(self.session_id)
                self._add_system_message("Aborted current streaming")
            else:
                self._add_system_message("Press Ctrl+D to quit")
        elif event.key == "ctrl+d":
            event.stop()
            self.running = False
            self.exit()
        elif event.key == "y" and self._confirmation_mode:
            event.stop()
            self._handle_confirmation_approve()
        elif event.key == "n" and self._confirmation_mode:
            event.stop()
            self._handle_confirmation_reject()

    async def _tick(self) -> None:
        while self.running:
            self._update_status()
            await asyncio.sleep(0.1)

    def _handle_confirmation_approve(self) -> None:
        if self._pending_confirmation:
            title = self._pending_confirmation.title
            self._pending_confirmation.approve()
            self._code_lines.append(f"\n  ✓ Confirmed: {title}")
            self._update_code_display()
            self._pending_confirmation = None
            self._confirmation_mode = False
            self._update_confirmation_display()

    def _handle_confirmation_reject(self) -> None:
        if self._pending_confirmation:
            title = self._pending_confirmation.title
            self._pending_confirmation.reject()
            self._code_lines.append(f"\n  ✗ Rejected: {title}")
            self._update_code_display()
            self._pending_confirmation = None
            self._confirmation_mode = False
            self._update_confirmation_display()

    def _handle_confirmation_input(self, text: str) -> None:
        text = text.strip().lower()
        if text in ("y", "yes"):
            self._handle_confirmation_approve()
        elif text in ("n", "no"):
            self._handle_confirmation_reject()
        else:
            self._add_system_message("Please enter 'y' or 'n'")
        self._input_widget.text = ""

    def _show_confirmation_request(self, request: ConfirmationRequest) -> None:
        self._pending_confirmation = request
        self._confirmation_mode = True

        separator = "\n" + "─" * 60
        self._code_lines.append(separator)
        self._code_lines.append(f"\n⚠️  {request.title}")
        self._code_lines.append("")
        for line in request.message.split("\n"):
            self._code_lines.append(f"  {line}")
        self._code_lines.append("")
        self._code_lines.append("  [y] Yes, execute this command")
        self._code_lines.append("  [n] No, reject this command")
        self._code_lines.append("  [Ctrl+C] Reject")
        self._code_lines.append(separator)

        self._update_code_display()
        self._update_confirmation_display()

    def _update_confirmation_display(self) -> None:
        if self._confirmation_mode and self._pending_confirmation:
            self._status_bar.update_text(
                "⚠️  CONFIRMATION REQUIRED: [y]=Yes, [n]=No, [Ctrl+C]=Reject"
            )
            self._status_bar.set_style(is_warning=True)
            self._input_widget.text = ""
        else:
            self._update_status()

    def _process_input(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        if text.startswith("/"):
            self._handle_command(text)
        else:
            asyncio.create_task(self._handle_message(text))

    def _handle_command(self, cmd: str) -> None:
        _log.debug(f"Handling command: {cmd}")
        parts = cmd.split(maxsplit=2)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else None
        if command in ("/quit", "/q"):
            self.running = False
            self.exit()
        elif command == "/abort":
            if self.runner.is_streaming(self.session_id):
                self.runner.abort(self.session_id)
                self._add_system_message("Aborted current streaming")
            else:
                self._add_system_message("No active streaming to abort")
        elif command == "/new":
            self.session_id = self.runner.create_session()
            self._subscribe_current()
            self._code_lines.clear()
            self._update_code_display()
            self._add_system_message(f"Created session: {self.session_id}")
        elif command == "/sessions":
            limit = None
            if args:
                try:
                    limit = int(args)
                except ValueError:
                    pass

            sessions = self.runner.list_persisted_sessions(limit)
            if not sessions:
                self._add_system_message("No sessions found")
            else:
                lines = [f"Sessions (showing {len(sessions)}):"]
                for s in sessions:
                    current = " *" if s["session_id"] == self.session_id else ""
                    first_msg = s.get("first_message", "")[:50]
                    if len(s.get("first_message", "")) > 50:
                        first_msg += "..."
                    lines.append(f"  {s['session_id']}{current}")
                    lines.append(
                        f"    Messages: {s['message_count']}, First: {first_msg}"
                    )
                self._add_system_message("\n".join(lines))
        elif command == "/checkout":
            if not args:
                self._add_system_message("Usage: /checkout <session_id>")
                return

            target_id = args.strip()

            if self.runner.has_session(target_id):
                self.session_id = target_id
                self._subscribe_current()
                self._code_lines.clear()
                self._update_code_display()
                self._add_system_message(f"Switched to session: {target_id}")
            else:
                sessions = self.runner.list_persisted_sessions()
                session_file = None
                for s in sessions:
                    if s["session_id"] == target_id:
                        session_file = s["session_file"]
                        break

                if not session_file:
                    self._add_system_message(f"Session not found: {target_id}")
                    return

                try:
                    self.session_id = self.runner.load_session(session_file)
                    self._subscribe_current()
                    self._code_lines.clear()
                    self._update_code_display()

                    state = self.runner.get_session(self.session_id)
                    if state:
                        for entry in state.session.get_entries():
                            if hasattr(entry, "message") and entry.message:
                                msg = entry.message
                                role = msg.get("role", "unknown")
                                if role == "user":
                                    content = self._extract_text_content(
                                        msg.get("content", "")
                                    )
                                    self._code_lines.append(f"\nYou: {content}")
                                elif role == "assistant":
                                    error_message = msg.get("error_message")
                                    if error_message:
                                        self._add_error_message(error_message)
                                    else:
                                        content = self._extract_text_content(
                                            msg.get("content", "")
                                        )
                                        self._code_lines.append(
                                            f"\nAssistant: {content}"
                                        )
                        self._update_code_display()

                    self._add_system_message(f"Loaded session: {target_id}")
                except Exception as e:
                    self._add_system_message(f"Failed to load session: {e}")
        elif command == "/agent":
            state: SessionState = self.runner.get_session(self.session_id)
            if state:
                agent = state.agent
                model = agent.state.model
                lines = [
                    "Current agent info:",
                    f"  Model: {getattr(model, 'model_name', 'N/A')}",
                    f"  Streaming: {agent.state.is_streaming}",
                    f"  Has Queued: {agent.has_queued_messages()}",
                ]
                self._add_system_message("\n".join(lines))
        elif command == "/help":
            self._add_system_message(
                "Commands:\n"
                "  /quit, /q        - Exit\n"
                "  /abort           - Abort current streaming\n"
                "  /new             - Create new session\n"
                "  /sessions [n]    - List sessions (last n)\n"
                "  /checkout <id>   - Switch to session\n"
                "  /agent           - Show agent info\n"
                "  /help            - Show this help\n\n"
                "Navigation:\n"
                "  Up/Down          - Scroll chat\n"
                "  Page Up/Down     - Scroll by page\n"
                "  Home/End         - Scroll to top/bottom\n\n"
                "During streaming:\n"
                "  Normal input = steer (interrupt)\n"
                "  > prefix = follow-up (after current turn)"
            )
        else:
            self._add_system_message(f"Unknown command: {command}")

    def _extract_text_content(self, content) -> str:
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

    def _display_assistant_error(self, error_message: str) -> None:
        self._in_thinking = False
        self._current_assistant_text = ""
        self._add_error_message(error_message)

    async def _handle_message(self, message: str) -> None:
        _log.debug(
            f"Handling message: is_follow_up={message.startswith('>')} message_len={len(message)}"
        )
        is_follow_up = message.startswith(">")
        if is_follow_up:
            message = message[1:].strip()

        is_streaming = self.runner.is_streaming(self.session_id)
        _log.debug(f"Current streaming state: {is_streaming}")

        if not is_streaming:
            self._add_user_message(message)

        try:
            if is_streaming:
                if is_follow_up:
                    _log.debug("Queuing follow-up message")
                    self.runner.follow_up(self.session_id, message)
                    self._add_system_message("Follow-up queued")
                else:
                    _log.debug("Sending steering message")
                    self.runner.steer(self.session_id, message)
                    self._add_user_message(message + " [steering]")
            else:
                _log.debug("Sending prompt message")
                await self.runner.prompt(self.session_id, message)
            _log.debug("Message sent successfully")
        except Exception as e:
            _log.error(f"Failed to send message: {e}")
            self._add_error_message(f"Error: {e}\n{traceback.format_exc()}")

    def _add_user_message(self, text: str) -> None:
        self._code_lines.append(f"\nYou: {text}")
        self._update_code_display()

    def _add_system_message(self, text: str) -> None:
        self._code_lines.append(f"\n[System] {text}")
        self._update_code_display()

    def _add_error_message(self, text: str) -> None:
        self._code_lines.append(f"\n[Error] {text}")
        self._update_code_display()

    def _update_code_display(self) -> None:
        text = "\n".join(self._code_lines)
        self._code_widget.update_content(text)
        self._code_widget.scroll_end()

    def _update_status(self) -> None:
        is_streaming = self.runner.is_streaming(self.session_id)
        has_queued = self.runner.has_queued_messages(self.session_id)

        status_parts = [f"Session: {self.session_id[:8]}..."]
        if is_streaming:
            status_parts.append("[STREAMING]")
        if has_queued:
            status_parts.append("[QUEUED]")

        self._status_bar.update_text(" | ".join(status_parts))
        self._status_bar.set_style(is_streaming=is_streaming)

    def _subscribe_current(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()

        config = self.config

        def on_event(event: AgentEvent) -> None:
            try:
                if event.type == "thinking_delta":
                    if not config.chat.show_thinking:
                        return
                    assistant_event = getattr(event, "assistant_event", None)
                    if assistant_event:
                        data = getattr(assistant_event, "data", None)
                        if data:
                            delta = getattr(data, "delta", "")
                            if delta:
                                if not self._in_thinking:
                                    self._code_lines.append("\n[Thinking] ")
                                    self._in_thinking = True
                                self._code_lines[-1] += delta
                                self._update_code_display()

                elif event.type == "content_delta":
                    if self._in_thinking:
                        self._in_thinking = False
                    assistant_event = getattr(event, "assistant_event", None)
                    if assistant_event:
                        data = getattr(assistant_event, "data", None)
                        if data:
                            delta = getattr(data, "delta", "")
                            if delta:
                                if not self._current_assistant_text:
                                    self._code_lines.append("\nAssistant: ")
                                self._current_assistant_text += delta
                                self._code_lines[-1] = (
                                    "\nAssistant: " + self._current_assistant_text
                                )
                                self._update_code_display()

                elif event.type == "message_end" and event.message:
                    self._in_thinking = False
                    self._current_assistant_text = ""
                    if getattr(event.message, "role", "") == "assistant":
                        error_message = getattr(event.message, "error_message", None)
                        if error_message:
                            self._display_assistant_error(error_message)

                elif event.type == "tool_execution_start":
                    if config.chat.show_tool_execution:
                        tool_name = getattr(event, "tool_name", "unknown")
                        self._code_lines.append(f"\n[Tool] Executing: {tool_name}")
                        if config.chat.show_tool_args != "off":
                            args = getattr(event, "args", {})
                            if args:
                                import json

                                args_str = json.dumps(args, ensure_ascii=False)
                                display_str = format_for_display(
                                    args_str, config.chat.show_tool_args, max_chars=50
                                )
                                if display_str:
                                    self._code_lines.append(f"  Args: {display_str}")
                        self._update_code_display()

                elif event.type == "tool_execution_end":
                    if (
                        config.chat.show_tool_execution
                        and config.chat.show_tool_result != "off"
                    ):
                        result = getattr(event, "result", None)
                        is_error = (
                            getattr(result, "is_error", False) if result else False
                        )
                        if result:
                            content = getattr(result, "content", None)
                            if content and hasattr(content, "__iter__"):
                                texts = []
                                for item in content:
                                    if hasattr(item, "text"):
                                        texts.append(item.text)
                                if texts:
                                    result_str = "\n".join(texts)
                                    if is_error:
                                        display_str = result_str
                                    else:
                                        display_str = format_for_display(
                                            result_str,
                                            config.chat.show_tool_result,
                                            max_chars=500,
                                        )
                                    if display_str:
                                        label = "Error" if is_error else "Result"
                                        self._code_lines.append(
                                            f"  {label}: {display_str}"
                                        )
                                        self._update_code_display()

                elif event.type == "turn_end":
                    self._code_lines.append("")
                    self._update_code_display()

                self._update_status()
            except Exception as e:
                log_exception(_log, f"Error handling event {event.type}", e)

        self._unsubscribe = self.runner.subscribe(self.session_id, on_event)

    async def run(self) -> None:
        try:
            await super().run_async()
        finally:
            self.running = False
            if self._unsubscribe:
                self._unsubscribe()


class ChatTUI:
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
