"""CPU load and thermal signals that do not need sudo."""

from __future__ import annotations

import re
import subprocess

_SPEED = re.compile(r"CPU_Speed_Limit\s*=\s*(\d+)")


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


def temperature_celsius() -> float | None:
    """macOS does not expose CPU temperature to a normal user.

    `powermetrics` can read SMC sensors, but it asks for an administrator
    password. This function never prompts and never uses sudo.
    """
    return None
