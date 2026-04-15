from __future__ import annotations

import asyncio

from .models import TaskInfo, TaskPayload, TaskSendResponse, TaskStatus


class TaskState:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._busy = False
        self._current_task: TaskInfo | None = None

    async def get_status(self) -> TaskStatus:
        async with self._lock:
            return TaskStatus(
                busy=self._busy,
                current_task=self._current_task.model_copy(deep=True) if self._current_task else None,
            )

    async def send_task(self, payload: TaskPayload) -> TaskSendResponse:
        async with self._lock:
            if self._busy:
                return TaskSendResponse(
                    ok=False,
                    busy=True,
                    current_task=self._current_task.model_copy(deep=True) if self._current_task else None,
                    message="已有任务执行中",
                )

            self._current_task = TaskInfo(
                task_type=payload.task_type,
                task_content=payload.task_content.strip(),
            )
            self._busy = True
            return TaskSendResponse(
                ok=True,
                busy=True,
                current_task=self._current_task.model_copy(deep=True),
            )

    async def clear(self) -> TaskStatus:
        async with self._lock:
            self._busy = False
            self._current_task = None
            return TaskStatus(busy=False, current_task=None)
