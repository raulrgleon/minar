"""Start and stop the local minerd process. One miner, fixed pool, no shell."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import psutil

from app.parser import MinerLogParser, clean_log_line
from app.system_stats import TEMP_STOP_C, read_cpu_temperature, read_thermal

POOL_URL = "stratum+tcp://solo.ckpool.org:3333"
POOL_PASSWORD = "x"
_MACHO_MAGICS = {
    b"\xfe\xed\xfa\xcf",
    b"\xfe\xed\xfa\xce",
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
}


class MinerError(RuntimeError):
    pass


class MinerService:
    def __init__(self, binary: Path) -> None:
        self.binary = binary
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._monitor: threading.Thread | None = None
        self._closed = False
        self._stop_requested = False
        self._parser = MinerLogParser()
        self._logs: deque[str] = deque(maxlen=80)
        self._history: deque[dict] = deque(maxlen=180)
        self._sample_sum = 0.0
        self._sample_count = 0
        self._last_sample_at = 0.0
        self._last_counted = False
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._stop_reason: str | None = None
        self._exit_code: int | None = None
        self._threads = 0
        self._nice = 10
        self._address = ""
        self._cpu_percent = 0.0
        self._temp_c: float | None = None
        self._temp_note = "Leyendo la temperatura del núcleo."
        self._temp_reads = 0
        self._thermal = {"available": False, "speed_limit": None, "throttling": False, "error": None}
        self._throttle_hits = 0
        self._monitor = threading.Thread(target=self._monitor_loop, name="minar-monitor", daemon=True)
        self._monitor.start()

    def close(self) -> None:
        self._closed = True
        self.stop(None)

    def snapshot(self) -> dict:
        with self._lock:
            running = self._is_running_locked()
            hashrate = self._parser.hashrate_hs()
            avg = (self._sample_sum / self._sample_count) if self._sample_count else 0.0
            uptime = self._uptime_locked(running)
            return {
                "running": running,
                "threads": self._threads,
                "address": self._address,
                "hashrate_hs": hashrate,
                "hashrate_avg_hs": avg,
                "history": list(self._history),
                "accepted": self._parser.accepted,
                "rejected": self._parser.rejected,
                "uptime_s": uptime,
                "pool": self._pool_locked(running),
                "logs": list(self._logs),
                "parse_errors": self._parser.parse_errors,
                "algo": self._parser.algo,
                "cpu_percent": self._cpu_percent,
                "cpu_temp_c": self._temp_c,
                "temp_note": self._temp_note,
                "speed_limit": self._thermal.get("speed_limit"),
                "thermal_available": bool(self._thermal.get("available")),
                "throttling": bool(self._thermal.get("throttling")),
                "stop_reason": self._stop_reason,
                "exit_code": self._exit_code,
                "nice": self._nice,
                "pool_url": POOL_URL,
            }

    def start(self, address: str, threads: int, nice: int) -> None:
        self._require_binary()
        with self._lock:
            if self._is_running_locked():
                raise MinerError("El minero ya está en marcha.")
            self._parser = MinerLogParser()
            self._logs.clear()
            self._history.clear()
            self._sample_sum = 0.0
            self._sample_count = 0
            self._last_sample_at = 0.0
            self._last_counted = False
            self._started_at = time.time()
            self._stopped_at = None
            self._stop_reason = None
            self._exit_code = None
            self._stop_requested = False
            self._threads = threads
            self._nice = nice
            self._address = address
            self._throttle_hits = 0
            cmd = [
                "/usr/bin/caffeinate",
                "-ims",
                "/usr/bin/nice",
                "-n",
                str(nice),
                str(self.binary),
                "-a",
                "sha256d",
                "-o",
                POOL_URL,
                "-u",
                address,
                "-p",
                POOL_PASSWORD,
                "-t",
                str(threads),
            ]
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
            except OSError as exc:
                self._proc = None
                self._started_at = None
                raise MinerError(f"No pude arrancar el minero: {exc}") from exc
            proc = self._proc
            self._reader = threading.Thread(
                target=self._read_output,
                args=(proc,),
                name="minar-reader",
                daemon=True,
            )
            self._reader.start()

    def stop(self, reason: str | None) -> None:
        with self._lock:
            proc = self._proc
            self._stop_requested = True
            if reason:
                self._stop_reason = reason
        if proc is None or proc.poll() is not None:
            with self._lock:
                if self._started_at and self._stopped_at is None:
                    self._stopped_at = time.time()
            return
        _terminate_group(proc)
        with self._lock:
            self._stopped_at = time.time()
            self._exit_code = proc.poll()

    def _require_binary(self) -> None:
        path = self.binary
        if not path.is_file():
            raise MinerError("No está bin/minerd. Ejecuta scripts/build-minerd.sh.")
        if path.is_symlink():
            raise MinerError("bin/minerd no puede ser un enlace simbólico.")
        resolved = path.resolve()
        root = path.parent.resolve()
        if root != resolved.parent or resolved.name != "minerd":
            raise MinerError("El minero tiene que ser el archivo bin/minerd de este proyecto.")
        try:
            with path.open("rb") as handle:
                magic = handle.read(4)
        except OSError as exc:
            raise MinerError(f"No pude leer bin/minerd: {exc}") from exc
        if magic not in _MACHO_MAGICS:
            raise MinerError("bin/minerd no es un ejecutable de macOS.")
        if not os.access(path, os.X_OK):
            raise MinerError("bin/minerd no tiene permiso de ejecución.")

    def _read_output(self, proc: subprocess.Popen) -> None:
        stream = proc.stderr
        try:
            if stream is not None:
                for raw in stream:
                    self._consume(raw)
        finally:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            with self._lock:
                if self._proc is proc:
                    self._exit_code = proc.returncode
                    if self._stopped_at is None:
                        self._stopped_at = time.time()
                    if not self._stop_requested and self._parser.pool != "auth_failed":
                        self._parser.pool = "exited"

    def _consume(self, raw: str) -> None:
        line = clean_log_line(raw)
        now = time.time()
        with self._lock:
            if line:
                self._logs.append(line)
            self._parser.feed(line)
            rate = self._parser.hashrate_hs()
            if rate <= 0:
                return
            stable = self._started_at is not None and now - self._started_at >= 8
            if self._history and now - self._last_sample_at < 1:
                previous = self._history[-1]["hs"]
                self._history[-1] = {"t": now, "hs": rate}
                if self._last_counted:
                    self._sample_sum += rate - previous
                elif stable:
                    self._sample_sum += rate
                    self._sample_count += 1
                    self._last_counted = True
                return
            self._history.append({"t": now, "hs": rate})
            self._last_sample_at = now
            # The first scan is a short burst and reads higher than the sustained rate.
            if stable:
                self._sample_sum += rate
                self._sample_count += 1
                self._last_counted = True
            else:
                self._last_counted = False

    def _monitor_loop(self) -> None:
        psutil.cpu_percent(interval=None)
        self._store_temperature(read_cpu_temperature())
        while not self._closed:
            time.sleep(2)
            try:
                cpu = float(psutil.cpu_percent(interval=None))
            except Exception:
                cpu = 0.0
            thermal = read_thermal()
            self._temp_reads += 1
            temperature = read_cpu_temperature() if self._temp_reads % 3 == 0 else None
            should_stop = False
            stop_reason = None
            with self._lock:
                self._cpu_percent = cpu
                self._thermal = thermal
                if temperature is not None:
                    self._temp_c = temperature["celsius"]
                    self._temp_note = temperature["note"]
                running = self._is_running_locked()
                hot = self._temp_c is not None and self._temp_c >= TEMP_STOP_C
                if running and hot:
                    should_stop = True
                    stop_reason = (
                        f"Paré el minero porque el núcleo llegó a {self._temp_c:.0f} °C."
                    )
                elif running and thermal.get("throttling"):
                    self._throttle_hits += 1
                    if self._throttle_hits >= 2:
                        should_stop = True
                        limit = thermal.get("speed_limit")
                        stop_reason = (
                            f"Paré el minero porque macOS bajó el límite de velocidad de la CPU a {limit} de 100."
                        )
                else:
                    self._throttle_hits = 0
            if should_stop and stop_reason:
                self.stop(stop_reason)

    def _store_temperature(self, temperature: dict) -> None:
        with self._lock:
            self._temp_c = temperature["celsius"]
            self._temp_note = temperature["note"]

    def _is_running_locked(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _uptime_locked(self, running: bool) -> float:
        if self._started_at is None:
            return 0.0
        end = time.time() if running else (self._stopped_at or time.time())
        return max(0.0, end - self._started_at)

    def _pool_locked(self, running: bool) -> str:
        if self._stop_reason and not running:
            return "stopped"
        if not running:
            if self._started_at is None:
                return "stopped"
            if self._parser.pool == "auth_failed":
                return "auth_failed"
            if self._stop_requested or self._stop_reason:
                return "stopped"
            return "exited"
        return self._parser.pool


def _terminate_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
