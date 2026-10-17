"""Unit tests for address checks, log parsing, odds, and thermal text."""

from __future__ import annotations

import hashlib
import unittest

from app.btc_address import AddressError, validate_public_address
from app.odds import block_odds
from app.parser import MinerLogParser
from app.system_stats import parse_pmset_therm

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode(raw: bytes) -> str:
    num = int.from_bytes(raw, "big")
    chars = []
    while num:
        num, rem = divmod(num, 58)
        chars.append(_B58[rem])
    pad = 0
    for byte in raw:
        if byte == 0:
            pad += 1
        else:
            break
    return "1" * pad + "".join(reversed(chars or ["1"]))


def _wif() -> str:
    payload = b"\x80" + (b"\x11" * 32)
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return _b58encode(payload + checksum)


class AddressTests(unittest.TestCase):
    def test_bip173_vector(self):
        self.assertEqual(
            validate_public_address("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"),
            "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        )

    def test_bad_bech32_checksum(self):
        with self.assertRaises(AddressError):
            validate_public_address("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5")

    def test_taproot_vector(self):
        address = "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0"
        self.assertEqual(validate_public_address(address), address)

    def test_base58_addresses(self):
        self.assertEqual(
            validate_public_address("1BoatSLRHtKNngkdXEeobR76b53LETtpyT"),
            "1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
        )
        payload = b"\x05" + (b"\x22" * 20)
        checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        p2sh = _b58encode(payload + checksum)
        self.assertTrue(p2sh.startswith("3"))
        self.assertEqual(validate_public_address(p2sh), p2sh)
        broken = p2sh[:-1] + ("1" if p2sh[-1] != "1" else "2")
        with self.assertRaises(AddressError):
            validate_public_address(broken)

    def test_rejects_wif_and_hex_and_seed(self):
        with self.assertRaises(AddressError):
            validate_public_address(_wif())
        with self.assertRaises(AddressError):
            validate_public_address("11" * 32)
        with self.assertRaises(AddressError):
            validate_public_address(" ".join(["abandon"] * 12))


class ParserTests(unittest.TestCase):
    def test_real_pool_lines(self):
        parser = MinerLogParser()
        lines = [
            "[2026-10-17 13:49:39] Starting Stratum on stratum+tcp://solo.ckpool.org:3333",
            "[2026-10-17 13:49:39] 2 miner threads started, using 'sha256d' algorithm.",
            "[2026-10-17 13:49:40] Stratum requested work restart",
            "[2026-10-17 13:49:41] thread 0: 2097152 hashes, 15452 khash/s",
            "[2026-10-17 13:49:41] thread 1: 2097152 hashes, 15441 khash/s",
            "this is not a stat line",
        ]
        for line in lines:
            parser.feed(line)
        self.assertEqual(parser.pool, "connected")
        self.assertEqual(parser.algo, "sha256d")
        self.assertEqual(parser.parse_errors, 0)
        self.assertAlmostEqual(parser.hashrate_hs(), (15452 + 15441) * 1000)

    def test_share_counts(self):
        parser = MinerLogParser()
        parser.feed("[2026-10-17 13:50:00] accepted: 1/3 (33.33%), 10.00 khash/s (booooo)")
        self.assertEqual(parser.accepted, 1)
        self.assertEqual(parser.rejected, 2)


class OddsTests(unittest.TestCase):
    def test_lottery_is_tiny(self):
        odds = block_odds(11_000_000, 140_577_680_051_919.62)
        self.assertTrue(odds["ready"])
        self.assertGreater(odds["expected_years"], 1_000_000)
        self.assertLess(odds["probability_per_day"], 1e-9)
        hashes = 140_577_680_051_919.62 * 2**32
        expected = 86400 * 11_000_000 / hashes
        self.assertAlmostEqual(odds["probability_per_day"], expected, delta=expected * 1e-6)

    def test_zero_hashrate(self):
        self.assertFalse(block_odds(0, 100)["ready"])


class ThermalTests(unittest.TestCase):
    def test_full_speed(self):
        text = "CPU_Scheduler_Limit \t= 100\nCPU_Speed_Limit \t= 100\n"
        parsed = parse_pmset_therm(text)
        self.assertFalse(parsed["throttling"])
        self.assertEqual(parsed["speed_limit"], 100)

    def test_throttled(self):
        parsed = parse_pmset_therm("CPU_Speed_Limit \t= 70")
        self.assertTrue(parsed["throttling"])


if __name__ == "__main__":
    unittest.main()
