"""Parse pooler's minerd stderr. Unknown lines are kept and never raise."""

from __future__ import annotations

import re

_THREAD = re.compile(
    r"thread\s+(\d+):\s+(\d+)\s+hashes,\s+([0-9]+(?:\.[0-9]+)?)\s+khash/s"
)
_TOTAL = re.compile(r"Total:\s+([0-9]+(?:\.[0-9]+)?)\s+khash/s")
_ACCEPTED = re.compile(
    r"accepted:\s+(\d+)/(\d+)\s+\([0-9.]+%\),\s+([0-9]+(?:\.[0-9]+)?)\s+khash/s"
)
_STARTED = re.compile(
    r"(\d+)\s+miner threads started,\s+using\s+'([^']+)'\s+algorithm"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_log_line(line: str) -> str:
    text = _CONTROL.sub("", line).strip()
    return text[:300]


class MinerLogParser:
    def __init__(self) -> None:
        self.thread_khs: dict[int, float] = {}
        self.expected_threads: int | None = None
        self.algo: str | None = None
        self.accepted = 0
        self.rejected = 0
        self.pool = "starting"
        self.parse_errors = 0
        self.last_total_khs: float | None = None

    def feed(self, line: str) -> None:
        try:
            self._feed(clean_log_line(line))
        except Exception:
            self.parse_errors += 1

    def hashrate_hs(self) -> float:
        if self.last_total_khs is not None and not self.thread_khs:
            return self.last_total_khs * 1000.0
        if not self.thread_khs:
            return 0.0
        return sum(self.thread_khs.values()) * 1000.0

    def _feed(self, line: str) -> None:
        if not line:
            return
        started = _STARTED.search(line)
        if started:
            self.expected_threads = int(started.group(1))
            self.algo = started.group(2)
            self.thread_khs.clear()
            self.last_total_khs = None
            return
        thread = _THREAD.search(line)
        if thread:
            self.thread_khs[int(thread.group(1))] = float(thread.group(3))
            if self.pool in ("starting", "connecting"):
                self.pool = "connected"
            return
        total = _TOTAL.search(line)
        if total:
            self.last_total_khs = float(total.group(1))
            return
        accepted = _ACCEPTED.search(line)
        if accepted:
            good = int(accepted.group(1))
            total_shares = int(accepted.group(2))
            self.accepted = good
            self.rejected = max(0, total_shares - good)
            self.last_total_khs = float(accepted.group(3))
            return
        lowered = line.lower()
        if "stratum authentication failed" in lowered:
            self.pool = "auth_failed"
            return
        if "starting stratum" in lowered:
            self.pool = "connecting"
            return
        if "stratum requested work restart" in lowered:
            self.pool = "connected"
            return
        if (
            "stratum connection failed" in lowered
            or "stratum connection interrupted" in lowered
            or "stratum connection timed out" in lowered
            or "retry after" in lowered
        ):
            self.pool = "reconnecting"
            return
        if "workio thread dead" in lowered:
            self.pool = "exited"
