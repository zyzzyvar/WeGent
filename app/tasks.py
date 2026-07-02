from __future__ import annotations

import asyncio
import logging

from app.assistant import AssistantService
from app.config import Settings
from app.db import Database, utc_now_iso
from app.wechat import WeChatOfficialClient

logger = logging.getLogger(__name__)


class TaskRunner:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        assistant: AssistantService,
        wechat: WeChatOfficialClient,
    ):
        self.settings = settings
        self.db = db
        self.assistant = assistant
        self.wechat = wechat
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="wegent-task-runner")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self._tick()
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.settings.task_poll_interval_seconds,
                )
            except TimeoutError:
                pass

    async def _tick(self) -> None:
        for task in self.db.due_tasks(utc_now_iso()):
            if not self.db.mark_task_running(task["id"]):
                continue
            try:
                if self.settings.safety_mode and not self.settings.safety_allow_proactive_task_send:
                    result = "安全模式下已禁止定时任务主动触达，任务结果未通过微信客服消息发送。"
                    self.db.record_safety_event(
                        task["openid"],
                        "task_send_skipped",
                        f"task #{task['id']} proactive send disabled",
                    )
                    self.db.complete_task(task["id"], result, status="done")
                    continue

                result = await self.assistant.handle_task(task["openid"], task["prompt"])
                message = f"任务 #{task['id']} 完成：\n{result}"
                await self.wechat.send_text(task["openid"], message)
                self.db.complete_task(task["id"], result, status="done")
            except Exception as exc:  # noqa: BLE001 - keep runner alive.
                logger.exception("Scheduled task %s failed", task["id"])
                self.db.complete_task(task["id"], str(exc), status="failed")
