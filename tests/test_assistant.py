import pytest

from app.assistant import AssistantService
from app.config import load_settings
from app.db import Database


class CapturingLLM:
    def __init__(self) -> None:
        self.messages = None

    async def chat(self, messages):
        self.messages = messages
        return "answer"


@pytest.mark.anyio
async def test_current_message_is_not_duplicated_when_already_recorded(tmp_path) -> None:
    settings = load_settings()
    db = Database(tmp_path / "test.sqlite3")
    db.init()
    llm = CapturingLLM()
    assistant = AssistantService(settings, db, llm)

    db.record_message(openid="openid", role="user", content="hello", msg_id="msg-1")
    await assistant.handle_text("openid", "hello", current_message_recorded=True)

    user_messages = [msg for msg in llm.messages if msg["role"] == "user"]
    assert [msg["content"] for msg in user_messages] == ["hello"]

