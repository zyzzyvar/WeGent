from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    aliases: tuple[str, ...]
    summary: str
    prompt_hint: str
    default_enabled: bool = False
    ready: bool = True


BUILTIN_SKILLS: dict[str, Skill] = {
    "memory": Skill(
        id="memory",
        name="记忆",
        aliases=("memory", "记忆", "长期记忆"),
        summary="保存和读取用户级长期偏好、事实和上下文。",
        prompt_hint="Use the user's long-term memories when they are relevant.",
        default_enabled=True,
    ),
    "tasks": Skill(
        id="tasks",
        name="定时任务",
        aliases=("tasks", "任务", "提醒", "定时任务"),
        summary="创建、查看、取消到点执行的一次性任务。",
        prompt_hint="Help the user create and manage scheduled tasks when they ask.",
        default_enabled=True,
    ),
    "voice": Skill(
        id="voice",
        name="语音",
        aliases=("voice", "语音", "语音识别", "语音回复"),
        summary="处理语音识别结果，并在后续接入语音回复。",
        prompt_hint="Handle voice messages naturally when speech input is available.",
        ready=False,
    ),
    "images": Skill(
        id="images",
        name="图片识别",
        aliases=("images", "image", "图片", "图片识别", "视觉"),
        summary="理解用户发送的图片，并结合对话给出分析。",
        prompt_hint="Analyze image content when a vision model and image payload are available.",
        ready=False,
    ),
}


def resolve_skill_id(value: str) -> str | None:
    normalized = value.strip().lower()
    for skill in BUILTIN_SKILLS.values():
        names = {skill.id.lower(), skill.name.lower(), *(alias.lower() for alias in skill.aliases)}
        if normalized in names:
            return skill.id
    return None
