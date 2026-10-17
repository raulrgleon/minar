"""CPU load, speed limit, and die temperature."""

from __future__ import annotations

import re
import subprocess

_SPEED = re.compile(r"CPU_Speed_Limit\s*=\s*(\d+)")
_DIE = re.compile(r"CPU die temperature:\s+([0-9]+(?:\.[0-9]+)?)\s+C")
_POWERMETRICS = [
    "/usr/bin/sudo",
    "-n",
    "/usr/bin/powermetrics",
    "-n",
    "1",
    "-i",
    "200",
    "--samplers",
    "smc",
]
TEMP_STOP_C = 98.0


def parse_pmset_therm(text: str) -> dict:
    match = _SPEED.search(text)
    speed_limit = int(match.group(1)) if match else None
    throttling = speed_limit is not None and speed_limit < 100
    return {
        "available": speed_limit is not None,
        "speed_limit": speed_limit,
        "throttling": throttling,
    }


def read_thermal() -> dict:
    try:
        out = subprocess.check_output(
            ["pmset", "-g", "therm"],
            text=True,
            timeout=4,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": False,
            "speed_limit": None,
            "throttling": False,
            "error": exc.__class__.__name__,
        }
    parsed = parse_pmset_therm(out)
    parsed["error"] = None
    return parsed


def parse_cpu_temperature(text: str) -> float | None:
    match = _DIE.search(text)
    if not match:
        return None
    return float(match.group(1))


def read_cpu_temperature() -> dict:
    """Read the CPU die temperature.

    The command is allowed once, without a stored password, by a root sudoers
    rule that names this exact powermetrics invocation and nothing else.
    """
    try:
        out = subprocess.check_output(
            _POWERMETRICS,
            text=True,
            timeout=8,
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return {
            "celsius": None,
            "note": "No pude leer la temperatura. El permiso de powermetrics no está activo.",
        }
    celsius = parse_cpu_temperature(out)
    if celsius is None:
        return {"celsius": None, "note": "powermetrics no devolvió la temperatura del núcleo."}
    return {"celsius": celsius, "note": f"El minero se para solo si el núcleo llega a {TEMP_STOP_C:.0f} °C."}
