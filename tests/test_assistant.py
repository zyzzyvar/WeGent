from dataclasses import replace

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


def assistant_test_settings():
    return replace(load_settings(), safety_mode=False)


@pytest.mark.anyio
async def test_current_message_is_not_duplicated_when_already_recorded(tmp_path) -> None:
    settings = assistant_test_settings()
    db = Database(tmp_path / "test.sqlite3")
    db.init()
    llm = CapturingLLM()
    assistant = AssistantService(settings, db, llm)

    db.record_message(openid="openid", role="user", content="hello", msg_id="msg-1")
    await assistant.handle_text("openid", "hello", current_message_recorded=True)

    user_messages = [msg for msg in llm.messages if msg["role"] == "user"]
    assert [msg["content"] for msg in user_messages] == ["hello"]


@pytest.mark.anyio
async def test_memory_is_user_scoped_and_can_delete_by_index(tmp_path) -> None:
    settings = assistant_test_settings()
    db = Database(tmp_path / "test.sqlite3")
    db.init()
    assistant = AssistantService(settings, db, CapturingLLM())

    assert await assistant.handle_text("user-a", "记住 我喜欢简洁回答") == "记住了。"
    assert await assistant.handle_text("user-b", "查看记忆") == "目前还没有长期记忆。"

    listed = await assistant.handle_text("user-a", "查看记忆")
    assert "我喜欢简洁回答" in listed

    assert await assistant.handle_text("user-a", "忘记记忆 1") == "已忘记第 1 条记忆。"
    assert await assistant.handle_text("user-a", "查看记忆") == "目前还没有长期记忆。"


@pytest.mark.anyio
async def test_task_list_and_cancel(tmp_path) -> None:
    settings = assistant_test_settings()
    db = Database(tmp_path / "test.sqlite3")
    db.init()
    assistant = AssistantService(settings, db, CapturingLLM())

    created = await assistant.handle_text("openid", "提醒我 2026-06-03 09:00 检查水电费")
    assert "已创建任务 #1" in created

    listed = await assistant.handle_text("openid", "任务列表")
    assert "#1" in listed
    assert "检查水电费" in listed

    assert await assistant.handle_text("openid", "取消任务 1") == "已取消任务 #1。"
    assert await assistant.handle_text("openid", "任务列表") == "当前没有待处理任务。"


@pytest.mark.anyio
async def test_skill_toggle_controls_memory_prompt(tmp_path) -> None:
    settings = assistant_test_settings()
    db = Database(tmp_path / "test.sqlite3")
    db.init()
    llm = CapturingLLM()
    assistant = AssistantService(settings, db, llm)

    await assistant.handle_text("openid", "记住 我喜欢中文回答")
    await assistant.handle_text("openid", "卸载技能 记忆")
    await assistant.handle_text("openid", "hello")
    system_prompt = llm.messages[0]["content"]
    assert "Known long-term user memories" not in system_prompt

    await assistant.handle_text("openid", "安装技能 记忆")
    await assistant.handle_text("openid", "hello again")
    system_prompt = llm.messages[0]["content"]
    assert "Known long-term user memories" in system_prompt
    assert "我喜欢中文回答" in system_prompt


@pytest.mark.anyio
async def test_skill_list_shows_planned_capabilities(tmp_path) -> None:
    settings = assistant_test_settings()
    db = Database(tmp_path / "test.sqlite3")
    db.init()
    assistant = AssistantService(settings, db, CapturingLLM())

    result = await assistant.handle_text("openid", "技能列表")

    assert "记忆：已启用" in result
    assert "定时任务：已启用" in result
    assert "语音：接入中" in result
    assert "图片识别：接入中" in result
