"""
Session Manager for picho

Manages conversation sessions as append-only trees stored in JSONL files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime

from .types import (
    SessionHeader,
    SessionEntry,
    SessionMessageEntry,
    ModelChangeEntry,
    ThinkingLevelChangeEntry,
    CompactionEntry,
    BranchSummaryEntry,
    SessionInfo,
    SessionContext,
    SessionEntryType,
    generate_id,
    get_timestamp,
    message_to_dict,
    parse_entry,
    CURRENT_SESSION_VERSION,
    dict_to_message,
)
from ..logger import get_logger

_log = get_logger(__name__)


class SessionManager:
    def __init__(
        self,
        cwd: str,
        session_file: str | None = None,
        persist: bool = True,
    ):
        self.cwd = cwd
        self.persist = persist
        self.session_dir = self._get_session_dir()

        if persist and not os.path.exists(self.session_dir):
            os.makedirs(self.session_dir, exist_ok=True)
            _log.debug(f"Created session directory: {self.session_dir}")

        self.session_file: str | None = None
        self.session_id: str = ""
        self.header: SessionHeader | None = None
        self.entries: list[SessionEntryType] = []
        self.by_id: dict[str, SessionEntryType] = {}
        self.leaf_id: str | None = None

        if session_file:
            self.load_session(session_file)
        else:
            self.new_session()

    def _get_session_dir(self) -> str:
        session_dir = Path(self.cwd) / ".picho" / "sessions"
        return str(session_dir)

    def new_session(self, parent_session: str | None = None) -> str:
        self.session_id = generate_id()
        self.header = SessionHeader(
            type="session",
            version=CURRENT_SESSION_VERSION,
            id=self.session_id,
            timestamp=get_timestamp(),
            cwd=self.cwd,
            parent_session=parent_session,
        )
        self.entries = []
        self.by_id = {}
        self.leaf_id = None

        filename = f"session_{self.session_id}.jsonl"
        self.session_file = os.path.join(self.session_dir, filename)

        if self.persist:
            self._write_header()

        _log.debug(f"Created new session: {self.session_id}")
        return self.session_file

    def load_session(self, session_file: str) -> None:
        if not os.path.exists(session_file):
            _log.warning(f"Session file not found, creating new: {session_file}")
            self.new_session()
            self.session_file = session_file
            self._write_header()
            return

        self.session_file = session_file
        self._load_entries()

        if self.entries:
            last = self.entries[-1]
            self.leaf_id = last.id

        _log.debug(f"Loaded session: {self.session_id}, entries: {len(self.entries)}")

    def _load_entries(self) -> None:
        self.entries = []
        self.by_id = {}

        if not self.session_file or not os.path.exists(self.session_file):
            return

        with open(self.session_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                entry = parse_entry(line)
                if entry is None:
                    continue

                if isinstance(entry, SessionHeader):
                    self.header = entry
                    self.session_id = entry.id
                elif isinstance(entry, SessionEntry):
                    self.entries.append(entry)
                    self.by_id[entry.id] = entry

        self._migrate_if_needed()

    def _migrate_if_needed(self) -> None:
        if not self.header:
            return

        if self.header.version < 2:
            self._migrate_v1_to_v2()

        if self.header.version < CURRENT_SESSION_VERSION:
            self._rewrite_file()

    def _migrate_v1_to_v2(self) -> None:
        _log.debug(f"Migrating session {self.session_id} from v1 to v2")
        prev_id: str | None = None
        for entry in self.entries:
            if not entry.id:
                entry.id = generate_id()
            entry.parent_id = prev_id
            prev_id = entry.id

            if isinstance(entry, CompactionEntry) and hasattr(
                entry, "first_kept_entry_index"
            ):
                idx = getattr(entry, "first_kept_entry_index", None)
                if isinstance(idx, int) and idx < len(self.entries):
                    entry.first_kept_entry_id = self.entries[idx].id

        if self.header:
            self.header.version = 2

    def _write_header(self) -> None:
        if not self.session_file or not self.header:
            return

        with open(self.session_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.header.to_dict(), ensure_ascii=False) + "\n")

    def _rewrite_file(self) -> None:
        if not self.session_file or not self.header:
            return

        with open(self.session_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.header.to_dict(), ensure_ascii=False) + "\n")
            for entry in self.entries:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def _append_entry(self, entry: SessionEntryType) -> str:
        entry.id = generate_id()
        entry.parent_id = self.leaf_id
        entry.timestamp = get_timestamp()

        self.entries.append(entry)
        self.by_id[entry.id] = entry
        self.leaf_id = entry.id

        if self.persist and self.session_file:
            with open(self.session_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

        _log.debug(f"Appended entry: {entry.type} (id={entry.id})")
        return entry.id

    def append_message(self, message) -> str:
        msg_dict = message_to_dict(message)
        entry = SessionMessageEntry(message=msg_dict)
        return self._append_entry(entry)

    def append_model_change(self, provider: str, model_id: str) -> str:
        entry = ModelChangeEntry(provider=provider, model_id=model_id)
        return self._append_entry(entry)

    def append_thinking_level_change(self, thinking_level: str) -> str:
        entry = ThinkingLevelChangeEntry(thinking_level=thinking_level)
        return self._append_entry(entry)

    def append_compaction(
        self,
        summary: str,
        first_kept_entry_id: str,
        tokens_before: int,
        details: dict | None = None,
    ) -> str:
        entry = CompactionEntry(
            summary=summary,
            first_kept_entry_id=first_kept_entry_id,
            tokens_before=tokens_before,
            details=details or {},
        )
        _log.debug(f"Appended compaction: tokens_before={tokens_before}")
        return self._append_entry(entry)

    def append_branch_summary(self, from_id: str, summary: str) -> str:
        entry = BranchSummaryEntry(from_id=from_id, summary=summary)
        return self._append_entry(entry)

    def get_entry(self, entry_id: str) -> SessionEntryType | None:
        return self.by_id.get(entry_id)

    def get_leaf_entry(self) -> SessionEntryType | None:
        if self.leaf_id:
            return self.by_id.get(self.leaf_id)
        return self.entries[-1] if self.entries else None

    def get_context(self, leaf_id: str | None = None) -> SessionContext:
        target_id = leaf_id if leaf_id is not None else self.leaf_id

        if target_id is None:
            return SessionContext(messages=[], thinking_level="off", model=None)

        path = self._get_path_to_root(target_id)
        return self._build_context_from_path(path)

    def _get_path_to_root(self, entry_id: str) -> list[SessionEntryType]:
        path = []
        current_id = entry_id

        while current_id:
            entry = self.by_id.get(current_id)
            if not entry:
                break
            path.append(entry)
            current_id = entry.parent_id

        path.reverse()
        return path

    def _build_context_from_path(self, path: list[SessionEntryType]) -> SessionContext:
        messages = []
        annotations = []
        thinking_level = "off"
        model = None
        compaction = None

        for entry in path:
            if isinstance(entry, ThinkingLevelChangeEntry):
                thinking_level = entry.thinking_level
            elif isinstance(entry, ModelChangeEntry):
                model = {"provider": entry.provider, "model_id": entry.model_id}
            elif isinstance(entry, CompactionEntry):
                compaction = entry

        if compaction:
            annotations.append(
                {
                    "type": "compaction_summary",
                    "summary": compaction.summary,
                    "tokens_before": compaction.tokens_before,
                }
            )

            found_first_kept = False
            for entry in path:
                if entry.id == compaction.first_kept_entry_id:
                    found_first_kept = True

                if found_first_kept and isinstance(entry, SessionMessageEntry):
                    messages.append(dict_to_message(entry.message))
        else:
            for entry in path:
                if isinstance(entry, SessionMessageEntry):
                    messages.append(dict_to_message(entry.message))
                elif isinstance(entry, BranchSummaryEntry):
                    annotations.append(
                        {
                            "type": "branch_summary",
                            "summary": entry.summary,
                            "from_id": entry.from_id,
                        }
                    )

        return SessionContext(
            messages=messages,
            annotations=annotations,
            thinking_level=thinking_level,
            model=model,
        )

    def branch(self, from_entry_id: str | None = None) -> str:
        new_session_id = generate_id()
        new_header = SessionHeader(
            type="session",
            version=CURRENT_SESSION_VERSION,
            id=new_session_id,
            timestamp=get_timestamp(),
            cwd=self.cwd,
            parent_session=self.session_file,
        )

        filename = f"session_{new_session_id}.jsonl"
        new_session_file = os.path.join(self.session_dir, filename)

        with open(new_session_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(new_header.to_dict(), ensure_ascii=False) + "\n")

        _log.debug(f"Branched session: {self.session_id} -> {new_session_id}")
        return new_session_file

    def goto(self, entry_id: str | None) -> None:
        if entry_id is None:
            self.leaf_id = None
        elif entry_id in self.by_id:
            self.leaf_id = entry_id
        _log.debug(f"Goto entry: {entry_id}")

    def get_session_id(self) -> str:
        return self.session_id

    def get_session_file(self) -> str | None:
        return self.session_file

    def get_cwd(self) -> str:
        return self.cwd

    def get_session_dir(self) -> str:
        return self.session_dir

    def get_leaf_id(self) -> str | None:
        return self.leaf_id

    def get_entries(self) -> list[SessionEntryType]:
        return list(self.entries)

    def get_header(self) -> SessionHeader | None:
        return self.header

    def list_sessions(self) -> list[SessionInfo]:
        sessions = []

        if not os.path.exists(self.session_dir):
            return sessions

        for filename in os.listdir(self.session_dir):
            if not filename.endswith(".jsonl"):
                continue

            filepath = os.path.join(self.session_dir, filename)
            info = self._build_session_info(filepath)
            if info:
                sessions.append(info)

        sessions.sort(key=lambda s: s.modified, reverse=True)
        return sessions

    def _build_session_info(self, filepath: str) -> SessionInfo | None:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()

            if not lines:
                return None

            header_line = lines[0].strip()
            header_data = json.loads(header_line)

            if header_data.get("type") != "session":
                return None

            header = SessionHeader.from_dict(header_data)

            message_count = 0
            first_message = ""

            for line in lines[1:]:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry_data = json.loads(line)
                    if entry_data.get("type") == "message":
                        message_count += 1
                        msg = entry_data.get("message", {})
                        if not first_message and msg.get("role") == "user":
                            content = msg.get("content", "")
                            if isinstance(content, str):
                                first_message = content[:100]
                            elif isinstance(content, list):
                                texts = [
                                    c.get("text", "")
                                    for c in content
                                    if c.get("type") == "text"
                                ]
                                first_message = " ".join(texts)[:100]
                except json.JSONDecodeError:
                    continue

            stat = os.stat(filepath)
            created = (
                datetime.fromisoformat(header.timestamp)
                if header.timestamp
                else datetime.fromtimestamp(stat.st_ctime)
            )
            modified = datetime.fromtimestamp(stat.st_mtime)

            return SessionInfo(
                path=filepath,
                id=header.id,
                cwd=header.cwd,
                name=None,
                parent_session_path=header.parent_session,
                created=created,
                modified=modified,
                message_count=message_count,
                first_message=first_message or "(no messages)",
            )
        except Exception:
            return None

    def find_most_recent_session(self) -> str | None:
        sessions = self.list_sessions()
        return sessions[0].path if sessions else None

    def delete_session(self, session_file: str) -> bool:
        if session_file == self.session_file:
            return False

        try:
            if os.path.exists(session_file):
                os.remove(session_file)
                _log.info(f"Deleted session file: {session_file}")
                return True
        except Exception as e:
            _log.error(f"Failed to delete session file: {session_file}, error: {e}")

        return False

    def flush(self) -> None:
        pass
