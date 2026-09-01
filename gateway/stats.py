"""轻量内存统计：请求计数、成功率、最近错误。重启即清零。"""
from __future__ import annotations

import threading
import time


class Stats:
    def __init__(self):
        self._lock = threading.Lock()
        self.start_time = time.time()
        self.total = 0
        self.success = 0
        self.fail = 0
        self.last_errors: list[tuple[float, str]] = []

    def record(self, ok: bool, error: str = "") -> None:
        with self._lock:
            self.total += 1
            if ok:
                self.success += 1
            else:
                self.fail += 1
                self.last_errors.append((time.time(), error[:200]))
                self.last_errors = self.last_errors[-20:]

    def snapshot(self) -> dict:
        with self._lock:
            uptime = int(time.time() - self.start_time)
            success_rate = (
                round(self.success / self.total * 100, 1) if self.total else None
            )
            return {
                "uptime_sec": uptime,
                "total": self.total,
                "success": self.success,
                "fail": self.fail,
                "success_rate": success_rate,
                "last_errors": [
                    {"time": ts, "message": msg} for ts, msg in self.last_errors
                ],
            }


_stats = Stats()


def get_stats() -> Stats:
    return _stats
