"""
Session management for picho

Provides session persistence and context compaction.
"""

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
    dict_to_message,
    parse_entry,
    CURRENT_SESSION_VERSION,
)

from .manager import SessionManager

from .compaction import (
    CompactionSettings,
    CompactionPreparation,
    estimate_tokens,
    calculate_total_tokens,
    estimate_context_tokens,
    should_compact,
    prepare_compaction,
    generate_summary,
    extract_file_ops,
    serialize_conversation,
)

__all__ = [
    "SessionHeader",
    "SessionEntry",
    "SessionMessageEntry",
    "ModelChangeEntry",
    "ThinkingLevelChangeEntry",
    "CompactionEntry",
    "BranchSummaryEntry",
    "SessionInfo",
    "SessionContext",
    "SessionEntryType",
    "SessionManager",
    "CompactionSettings",
    "CompactionPreparation",
    "generate_id",
    "get_timestamp",
    "message_to_dict",
    "dict_to_message",
    "parse_entry",
    "estimate_tokens",
    "calculate_total_tokens",
    "estimate_context_tokens",
    "should_compact",
    "prepare_compaction",
    "generate_summary",
    "extract_file_ops",
    "serialize_conversation",
    "CURRENT_SESSION_VERSION",
]
