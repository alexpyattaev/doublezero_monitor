# Minimal impl for TaskGroup to avoid deps
import asyncio
from contextlib import AbstractAsyncContextManager


class TaskGroup(AbstractAsyncContextManager):
    def __init__(self):
        self._tasks = set()
        self._errors = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # Wait for all tasks to complete
        await self._wait_for_tasks()
        # If any subtask raised, re-raise the first one
        if self._errors and exc is None:
            raise self._errors[0]

    def create_task(self, coro, *, name=None):
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)

        def _on_done(t):
            self._tasks.discard(t)
            try:
                exc = t.exception()
            except asyncio.CancelledError:
                return
            if exc is not None:
                self._errors.append(exc)
                # cancel all remaining tasks if one failed
                for other in list(self._tasks):
                    other.cancel()

        task.add_done_callback(_on_done)
        return task

    async def _wait_for_tasks(self):
        if self._tasks:
            await asyncio.wait(self._tasks)
