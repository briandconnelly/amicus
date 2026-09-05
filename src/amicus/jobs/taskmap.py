"""A persisted task_id -> job_id map, written atomically (ADR 0004)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class TaskJobMap:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def _read(self) -> dict[str, str]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items()}

    def entries(self) -> dict[str, str]:
        return self._read()

    def job_for(self, task_id: str) -> str | None:
        return self._read().get(task_id)

    def task_for(self, job_id: str) -> str | None:
        for task_id, job in self._read().items():
            if job == job_id:
                return task_id
        return None

    def record(self, task_id: str, job_id: str) -> None:
        data = self._read()
        data[task_id] = job_id
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, sort_keys=True)
            tmp.replace(self._path)
        finally:
            if tmp.exists():
                tmp.unlink()
