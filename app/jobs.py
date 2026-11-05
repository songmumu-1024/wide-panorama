"""内存作业队列：Demo 用轮询方式展示进度，不引入额外中间件。"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field


@dataclass
class Job:
    id: str
    status: str = "queued"          # queued | running | done | error
    progress: int = 0
    message: str = ""
    error: str | None = None
    result: dict | None = None
    params: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, params: dict) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], params=params)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def start(self, job_id: str, message: str = "开始生成") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = "running"
                job.progress = 1
                job.message = message

    def progress(self, job_id: str, pct: int, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.progress = pct
                job.message = message

    def finish(self, job_id: str, result: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = "done"
                job.progress = 100
                job.message = "完成"
                job.result = result

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = "error"
                job.error = error
                job.message = "生成失败"
