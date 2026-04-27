from __future__ import annotations

from pathlib import Path

from picho.provider.types import AssistantMessage, TextContent, UserMessage
from picho.session.manager import SessionManager


def test_session_manager_persists_and_loads_context(tmp_path: Path):
    manager = SessionManager(cwd=str(tmp_path), persist=True)
    manager.append_thinking_level_change("high")
    manager.append_model_change("mock", "mock-model")
    manager.append_message(UserMessage(content="hello"))
    manager.append_message(AssistantMessage(content=[TextContent(text="hi there")]))

    session_file = manager.get_session_file()
    assert session_file is not None
    assert Path(session_file).exists()
    assert Path(session_file).parent == tmp_path

    loaded = SessionManager(cwd=str(tmp_path), session_file=session_file, persist=True)
    context = loaded.get_context()

    assert context.thinking_level == "high"
    assert context.model == {"provider": "mock", "model_id": "mock-model"}
    assert [message.role for message in context.messages] == ["user", "assistant"]
    assert context.messages[0].content == "hello"
    assert context.messages[1].content[0].text == "hi there"


def test_session_manager_compaction_context_keeps_summary_and_recent_messages(
    tmp_path: Path,
):
    manager = SessionManager(cwd=str(tmp_path), persist=False)
    manager.append_message(UserMessage(content="first user"))
    manager.append_message(
        AssistantMessage(content=[TextContent(text="first assistant")])
    )
    kept_user_id = manager.append_message(UserMessage(content="second user"))
    manager.append_message(
        AssistantMessage(content=[TextContent(text="second assistant")])
    )
    manager.append_compaction(
        summary="earlier conversation summary",
        first_kept_entry_id=kept_user_id,
        tokens_before=321,
    )

    context = manager.get_context()

    assert context.annotations == [
        {
            "type": "compaction_summary",
            "summary": "earlier conversation summary",
            "tokens_before": 321,
        }
    ]
    assert [message.role for message in context.messages] == ["user", "assistant"]
    assert context.messages[0].content == "second user"
    assert context.messages[1].content[0].text == "second assistant"


def test_session_manager_branch_and_delete(tmp_path: Path):
    manager = SessionManager(cwd=str(tmp_path), persist=True)
    manager.append_message(UserMessage(content="branch me"))

    session_file = manager.get_session_file()
    assert session_file is not None

    branch_file = manager.branch()
    assert Path(branch_file).exists()

    branched = SessionManager(cwd=str(tmp_path), session_file=branch_file, persist=True)
    header = branched.get_header()
    assert header is not None
    assert header.parent_session == session_file

    assert manager.delete_session(session_file) is False
    assert manager.delete_session(branch_file) is True
    assert Path(branch_file).exists() is False
