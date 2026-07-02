from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.db import Database
from app.llm import LocalLLMClient
from app.skills import BUILTIN_SKILLS, Skill, resolve_skill_id


REMIND_RE = re.compile(
    r"^(?:/remind|提醒我|提醒)\s+"
    r"(?P<time>\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})\s+"
    r"(?P<prompt>.+)$"
)
DELETE_MEMORY_RE = re.compile(r"^(?:忘记记忆|删除记忆)\s*#?(?P<index>\d+)$")
CANCEL_TASK_RE = re.compile(r"^(?:取消任务|删除任务)\s*#?(?P<task_id>\d+)$")
SKILL_ACTION_RE = re.compile(r"^(?P<action>安装技能|启用技能|卸载技能|关闭技能|技能详情)\s+(?P<skill>.+)$")


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
            {"role": "system", "content": self._system_prompt()},
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
                "2. 查看记忆 / 忘记记忆 2\n"
                "3. 提醒我 2026-06-03 09:00 检查某件事\n"
                "4. 任务列表 / 取消任务 3\n"
                "5. 技能列表 / 安装技能 记忆 / 卸载技能 定时任务\n"
                "6. 关闭记忆 / 开启记忆"
            )

        skill_result = self._handle_skill_command(openid, text)
        if skill_result is not None:
            return skill_result

        if text.startswith("记住"):
            if self.settings.safety_mode and not self.settings.safety_allow_memory:
                return "当前内部验证版已关闭长期记忆写入。"
            if not self._skill_enabled(openid, "memory"):
                return "记忆技能当前未启用。发送“安装技能 记忆”后，我再保存长期记忆。"
            memory = text.removeprefix("记住").strip(" ：:")
            if not memory:
                return "可以，告诉我需要记住的内容。比如：记住 我喜欢简洁的回答。"
            self.db.add_memory(openid, memory)
            return "记住了。"

        if text in {"查看记忆", "我的记忆", "/memory"}:
            if self.settings.safety_mode and not self.settings.safety_allow_memory:
                return "当前内部验证版已关闭长期记忆读取。"
            memories = self.db.list_memories(openid, limit=self.settings.max_memory_items)
            if not memories:
                return "目前还没有长期记忆。"
            lines = [f"{idx}. {row['content']}" for idx, row in enumerate(memories, start=1)]
            return "我现在记得：\n" + "\n".join(lines)

        match = DELETE_MEMORY_RE.match(text)
        if match:
            if self.settings.safety_mode and not self.settings.safety_allow_memory:
                return "当前内部验证版已关闭长期记忆。"
            memories = self.db.list_memories(openid, limit=self.settings.max_memory_items)
            index = int(match.group("index"))
            if index < 1 or index > len(memories):
                return "没有找到这条记忆。发送“查看记忆”可以看到当前编号。"
            self.db.delete_memory(openid, int(memories[index - 1]["id"]))
            return f"已忘记第 {index} 条记忆。"

        if text in {"清空记忆", "删除记忆", "忘掉我", "/forget"}:
            count = self.db.clear_memories(openid)
            return f"已清空 {count} 条记忆。"

        if text in {"关闭记忆", "暂停记忆"}:
            self.db.set_memory_enabled(openid, False)
            return "长期记忆已关闭。之后我仍会处理当前对话，但不会读取或新增长期记忆。"

        if text in {"开启记忆", "打开记忆"}:
            self.db.set_memory_enabled(openid, True)
            return "长期记忆已开启。你可以用“记住 ...”明确告诉我需要保存的偏好。"

        if text in {"任务列表", "查看任务", "我的任务", "/tasks"}:
            return self._format_tasks(openid)

        match = CANCEL_TASK_RE.match(text)
        if match:
            task_id = int(match.group("task_id"))
            if self.db.cancel_task(openid, task_id):
                return f"已取消任务 #{task_id}。"
            return "没有找到可取消的待处理任务。发送“任务列表”可以查看当前任务。"

        match = REMIND_RE.match(text)
        if match:
            if self.settings.safety_mode and not self.settings.safety_allow_task_creation:
                return "当前内部验证版已关闭定时任务创建，避免主动触达带来的平台风险。"
            if not self._skill_enabled(openid, "tasks"):
                return "定时任务技能当前未启用。发送“安装技能 定时任务”后，我再帮你创建提醒。"
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
        memory_enabled = (
            memory_enabled
            and self.settings.safety_allow_memory
            and self._skill_enabled(openid, "memory")
        )

        system_parts = [self._system_prompt()]
        skill_prompt = self._enabled_skill_prompt(openid)
        if skill_prompt:
            system_parts.append(skill_prompt)
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

    def _system_prompt(self) -> str:
        parts = [self.settings.system_prompt]
        if self.settings.safety_mode:
            parts.append(
                "Safety mode is enabled. You are an AI assistant, not a human, human customer "
                "service agent, account manager, doctor, lawyer, financial adviser, or public "
                "official. Never imply that a human is replying when the answer is generated by AI. "
                "Refuse requests involving illegal activity, fraud, credential handling, privacy "
                "secrets, adult content, self-harm or violence, and personalized medical, legal, "
                "or financial decisions. Keep answers concise and avoid proactive outreach."
            )
        return "\n\n".join(parts)

    def _parse_local_time(self, value: str) -> datetime:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M")
        return parsed.replace(tzinfo=self.tz)

    def _handle_skill_command(self, openid: str, text: str) -> str | None:
        if text in {"技能列表", "我的技能", "/skills"}:
            return self._format_skills(openid)

        match = SKILL_ACTION_RE.match(text)
        if not match:
            return None

        action = match.group("action")
        skill_id = resolve_skill_id(match.group("skill"))
        if skill_id is None:
            return "没有找到这个技能。发送“技能列表”可以查看当前支持的技能。"

        skill = BUILTIN_SKILLS[skill_id]
        if action == "技能详情":
            return self._format_skill_detail(openid, skill)

        if not skill.ready:
            return f"{skill.name}技能还在接入中，当前不能安装。"

        enabled = action in {"安装技能", "启用技能"}
        self.db.set_skill_enabled(openid, skill.id, enabled)
        state = "已启用" if enabled else "已停用"
        return f"{skill.name}技能{state}。"

    def _format_skills(self, openid: str) -> str:
        lines = ["当前技能："]
        for skill in BUILTIN_SKILLS.values():
            if skill.ready:
                state = "已启用" if self._skill_enabled(openid, skill.id) else "未启用"
            else:
                state = "接入中"
            lines.append(f"- {skill.name}：{state}。{skill.summary}")
        lines.append("可以发送“安装技能 记忆”“卸载技能 定时任务”“技能详情 图片识别”。")
        return "\n".join(lines)

    def _format_skill_detail(self, openid: str, skill: Skill) -> str:
        if skill.ready:
            state = "已启用" if self._skill_enabled(openid, skill.id) else "未启用"
        else:
            state = "接入中"
        return (
            f"{skill.name}\n"
            f"状态：{state}\n"
            f"说明：{skill.summary}\n"
            f"别名：{', '.join(skill.aliases)}"
        )

    def _format_tasks(self, openid: str) -> str:
        tasks = self.db.list_tasks(openid, statuses=("pending", "running"), limit=10)
        if not tasks:
            return "当前没有待处理任务。"

        lines = ["当前待处理任务："]
        for row in tasks:
            due_at = datetime.fromisoformat(row["due_at"]).astimezone(self.tz)
            status = "处理中" if row["status"] == "running" else "待处理"
            lines.append(
                f"#{row['id']} {due_at.strftime('%Y-%m-%d %H:%M')} "
                f"{status}：{row['title']}"
            )
        return "\n".join(lines)

    def _skill_enabled(self, openid: str, skill_id: str) -> bool:
        skill = BUILTIN_SKILLS[skill_id]
        return self.db.is_skill_enabled(openid, skill_id, default=skill.default_enabled)

    def _enabled_skill_prompt(self, openid: str) -> str:
        enabled = [
            skill
            for skill in BUILTIN_SKILLS.values()
            if skill.ready and self._skill_enabled(openid, skill.id)
        ]
        if not enabled:
            return ""
        lines = [f"- {skill.name}: {skill.prompt_hint}" for skill in enabled]
        return "Enabled assistant skills:\n" + "\n".join(lines)
