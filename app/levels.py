"""Three mining intensities for an 8-core iMac."""

from __future__ import annotations

LEVELS = {
    "bajo": {"threads": 2, "nice": 15, "label": "Bajo"},
    "medio": {"threads": 4, "nice": 10, "label": "Medio"},
    "alto": {"threads": 8, "nice": 5, "label": "Alto"},
}


def normalize_level(level: str | None, threads: int | None = None) -> str:
    if level in LEVELS:
        return level
    if isinstance(threads, int) and threads <= 2:
        return "bajo"
    if isinstance(threads, int) and threads >= 8:
        return "alto"
    return "medio"
