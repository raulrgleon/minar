"""Block-finding odds from hashrate and network difficulty.

A share at difficulty 1 is expected once per 2**32 hashes. Network difficulty
scales that target, so the expected hashes per Bitcoin block are difficulty * 2**32.
"""

from __future__ import annotations

import math

SECONDS_PER_BLOCK = 600
SECONDS_PER_DAY = 86400
SECONDS_PER_YEAR = 365.25 * SECONDS_PER_DAY


def format_int_es(value: float | int) -> str:
    rounded = int(round(float(value)))
    return f"{rounded:,}".replace(",", ".")


def format_hashrate(hs: float) -> str:
    units = (
        (1e18, "EH/s"),
        (1e15, "PH/s"),
        (1e12, "TH/s"),
        (1e9, "GH/s"),
        (1e6, "MH/s"),
        (1e3, "kH/s"),
    )
    for scale, name in units:
        if hs >= scale:
            return f"{hs / scale:.2f}".replace(".", ",") + f" {name}"
    return f"{hs:.0f} H/s"


def block_odds(hashrate_hs: float, difficulty: float) -> dict:
    if hashrate_hs <= 0 or difficulty <= 0 or not math.isfinite(hashrate_hs) or not math.isfinite(difficulty):
        return {"ready": False}
    hashes_per_block = difficulty * float(2**32)
    seconds = hashes_per_block / hashrate_hs
    # For a lottery this small, 1-exp(-x) is x. Use the series so tiny values stay visible.
    lam = SECONDS_PER_DAY / seconds
    if lam < 1e-8:
        probability_per_day = lam
    else:
        probability_per_day = 1.0 - math.exp(-lam)
    one_in = (1.0 / probability_per_day) if probability_per_day > 0 else None
    network_hs = hashes_per_block / SECONDS_PER_BLOCK
    years = seconds / SECONDS_PER_YEAR
    return {
        "ready": True,
        "hashrate_hs": hashrate_hs,
        "difficulty": difficulty,
        "hashes_per_block": hashes_per_block,
        "expected_seconds": seconds,
        "expected_years": years,
        "probability_per_day": probability_per_day,
        "one_in_days": one_in,
        "network_hashrate_hs": network_hs,
        "network_share": hashrate_hs / network_hs,
        "hashrate_text": format_hashrate(hashrate_hs),
        "difficulty_text": format_int_es(difficulty),
        "hashes_per_block_text": format_int_es(hashes_per_block),
        "years_text": format_int_es(years) if years >= 1 else f"{years:.2f}".replace(".", ","),
        "one_in_text": format_int_es(one_in) if one_in is not None else None,
        "network_hashrate_text": format_hashrate(network_hs),
    }
