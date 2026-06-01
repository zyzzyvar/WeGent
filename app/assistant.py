from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.db import Database
from app.llm import LocalLLMClient


REMIND_RE = re.compile(
    r"^(?:/remind|提醒我|提醒)\s+"
    r"(?P<time>\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})\s+"
    r"(?P<prompt>.+)$"
)


class AssistantService:
    def __init__(self, settings: Settings, db: Database, llm: LocalLLMClient):
        self.settings = settings
        self.db = db
        self.llm = llm
        self.tz = ZoneInfo(settings.timezone)

    async def handle_text(
        self,
        openid: str,
        content: str,
        *,
        current_message_recorded: bool = False,
    ) -> str:
        text = content.strip()
        if not current_message_recorded:
            self.db.record_message(openid=openid, role="user", content=text)

        command_result = self._handle_local_command(openid, text)
        if command_result is not None:
            self.db.record_message(openid=openid, role="assistant", content=command_result)
            return command_result

        messages = self._build_messages(
            openid,
            text,
            append_current=not current_message_recorded,
        )
        answer = await self.llm.chat(messages)
        self.db.record_message(openid=openid, role="assistant", content=answer)
        return answer

    async def handle_task(self, openid: str, prompt: str) -> str:
        messages = [
            {"role": "system", "content": self.settings.system_prompt},
            {
                "role": "user",
                "content": (
                    "A scheduled task is due. Complete it now and return the result "
                    f"for the user.\n\nTask:\n{prompt}"
                ),
            },
        ]
        return await self.llm.chat(messages)

    def _handle_local_command(self, openid: str, text: str) -> str | None:
        if not text:
            return "我在。你可以直接发问题、语音，或让我记住某个偏好。"

        if text in {"帮助", "/help", "help"}:
            return (
                "你可以直接和我对话。\n"
                "常用指令：\n"
                "1. 记住 我的偏好是...\n"
                "2. 查看记忆\n"
                "3. 清空记忆\n"
                "4. 关闭记忆 / 开启记忆\n"
                "5. 提醒我 2026-05-30 09:00 检查某件事"
            )

        if text.startswith("记住"):
            memory = text.removeprefix("记住").strip(" ：:")
            if not memory:
                return "可以，告诉我需要记住的内容。比如：记住 我喜欢简洁的回答。"
            self.db.add_memory(openid, memory)
            return "记住了。"

        if text in {"查看记忆", "我的记忆", "/memory"}:
            memories = self.db.list_memories(openid, limit=self.settings.max_memory_items)
            if not memories:
                return "目前还没有长期记忆。"
            lines = [f"{idx}. {row['content']}" for idx, row in enumerate(memories, start=1)]
            return "我现在记得：\n" + "\n".join(lines)

        if text in {"清空记忆", "删除记忆", "忘掉我", "/forget"}:
            count = self.db.clear_memories(openid)
            return f"已清空 {count} 条记忆。"

        if text in {"关闭记忆", "暂停记忆"}:
            self.db.set_memory_enabled(openid, False)
            return "长期记忆已关闭。之后我仍会处理当前对话，但不会读取或新增长期记忆。"

        if text in {"开启记忆", "打开记忆"}:
            self.db.set_memory_enabled(openid, True)
            return "长期记忆已开启。你可以用“记住 ...”明确告诉我需要保存的偏好。"

        match = REMIND_RE.match(text)
        if match:
            due_at = self._parse_local_time(match.group("time"))
            prompt = match.group("prompt").strip()
            task_id = self.db.create_task(
                openid=openid,
                title=prompt[:60],
                prompt=prompt,
                due_at=due_at.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds"),
            )
            return f"已创建任务 #{task_id}，我会在 {due_at.strftime('%Y-%m-%d %H:%M')} 处理。"

        return None

    def _build_messages(
        self,
        openid: str,
        current_text: str,
        *,
        append_current: bool,
    ) -> list[dict[str, str]]:
        user = self.db.get_user(openid)
        memory_enabled = bool(user["memory_enabled"]) if user else True

        system_parts = [self.settings.system_prompt]
        if memory_enabled:
            memories = self.db.list_memories(openid, limit=self.settings.max_memory_items)
            if memories:
                memory_text = "\n".join(f"- {row['content']}" for row in reversed(memories))
                system_parts.append(f"Known long-term user memories:\n{memory_text}")
        else:
            system_parts.append("Long-term memory is disabled for this user.")

        messages: list[dict[str, str]] = [{"role": "system", "content": "\n\n".join(system_parts)}]
        for row in self.db.recent_messages(openid, limit=8):
            role = "assistant" if row["role"] == "assistant" else "user"
            messages.append({"role": role, "content": row["content"]})
        if append_current:
            messages.append({"role": "user", "content": current_text})
        return messages

    def _parse_local_time(self, value: str) -> datetime:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M")
        return parsed.replace(tzinfo=self.tz)
