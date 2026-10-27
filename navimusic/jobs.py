"""Tareas en segundo plano con progreso y cancelación."""
from __future__ import annotations

import threading
import traceback
import uuid
from typing import Any, Callable, Dict


class Job:
    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex[:10]
        self.kind = kind
        self.status = "running"  # running | done | error | cancelled
        self.done = 0
        self.total = 0
        self.message = ""
        self.result: Any = None
        self.error = ""
        self._cancel = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def progress(self, done: int, total: int, message: str = "") -> None:
        self.done, self.total = done, total
        if message:
            self.message = message

    def to_dict(self, with_result: bool = True) -> Dict[str, Any]:
        d = {"id": self.id, "kind": self.kind, "status": self.status, "done": self.done,
             "total": self.total, "message": self.message, "error": self.error}
        if with_result and self.status in ("done", "cancelled"):
            d["result"] = self.result
        return d


JOBS: Dict[str, Job] = {}


def start(kind: str, fn: Callable[[Job], Any]) -> Job:
    job = Job(kind)
    JOBS[job.id] = job

    def run() -> None:
        try:
            job.result = fn(job)
            job.status = "cancelled" if job.cancelled else "done"
        except Exception as e:  # noqa: BLE001
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
            traceback.print_exc()

    threading.Thread(target=run, daemon=True).start()
    return job


def cancel(job_id: str) -> None:
    j = JOBS.get(job_id)
    if j:
        j._cancel.set()
