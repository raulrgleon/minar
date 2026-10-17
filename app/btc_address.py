"""Validate public Bitcoin addresses. Reject private keys and seeds."""

from __future__ import annotations

import hashlib
import re

_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST = 1
_BECH32M_CONST = 0x2BC830A3
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_HEX_KEY = re.compile(r"^[0-9a-fA-F]{64}$")
_WORDISH = re.compile(r"^[a-zA-Z]{2,}$")


class AddressError(ValueError):
    """The value is not a public mainnet Bitcoin address."""


def validate_public_address(value: str) -> str:
    """Return the normalized address, or raise AddressError.

    Accepts mainnet P2PKH (1...), P2SH (3...), and native segwit (bc1...).
    WIF private keys, hex keys, and word seeds are rejected on purpose.
    """
    if not isinstance(value, str):
        raise AddressError("La dirección tiene que ser texto.")
    text = value.strip()
    if not text:
        raise AddressError("Falta la dirección de Bitcoin.")
    if len(text) > 90:
        raise AddressError("Ese texto es demasiado largo para ser una dirección.")
    if any(ch.isspace() for ch in text):
        words = [w for w in text.split() if w]
        if len(words) >= 12 and all(_WORDISH.match(w) for w in words):
            raise AddressError(
                "Eso parece una semilla de palabras. Este programa solo acepta la dirección pública."
            )
        raise AddressError("La dirección no puede contener espacios.")
    if _HEX_KEY.match(text):
        raise AddressError(
            "Eso parece una clave privada en hexadecimal. Pega solo la dirección pública."
        )
    if text.lower().startswith("bc1"):
        return _validate_bech32(text)
    return _validate_base58(text)


def _validate_bech32(value: str) -> str:
    if value != value.lower() and value != value.upper():
        raise AddressError("La dirección bech32 no puede mezclar mayúsculas y minúsculas.")
    text = value.lower()
    sep = text.rfind("1")
    if sep < 1 or sep + 7 > len(text):
        raise AddressError("La dirección bech32 está incompleta.")
    hrp, data_part = text[:sep], text[sep + 1 :]
    if hrp != "bc":
        raise AddressError("Solo se aceptan direcciones mainnet que empiezan por bc1.")
    try:
        data = [_BECH32_CHARSET.index(ch) for ch in data_part]
    except ValueError as exc:
        raise AddressError("La dirección bech32 tiene un carácter inválido.") from exc
    polymod = _bech32_polymod(_hrp_expand(hrp) + data)
    if polymod not in (_BECH32_CONST, _BECH32M_CONST):
        raise AddressError("El checksum de la dirección bech32 no cuadra.")
    version = data[0]
    if version > 16:
        raise AddressError("La versión testigo de la dirección no es válida.")
    program = _convertbits(data[1:-6], 5, 8, pad=False)
    if program is None or not 2 <= len(program) <= 40:
        raise AddressError("El programa testigo de la dirección no es válido.")
    if version == 0:
        if polymod != _BECH32_CONST:
            raise AddressError("Una dirección bc1q tiene que usar checksum bech32.")
        if len(program) not in (20, 32):
            raise AddressError("Una dirección bc1q tiene que tener 20 o 32 bytes.")
    else:
        if polymod != _BECH32M_CONST:
            raise AddressError("Una dirección bc1p tiene que usar checksum bech32m.")
        if version == 1 and len(program) != 32:
            raise AddressError("Una dirección Taproot tiene que tener 32 bytes.")
    return text


def _validate_base58(value: str) -> str:
    if value[0] not in "13":
        if value[0] in "5KL9c":
            raise AddressError(
                "Eso parece una clave privada WIF. Pega solo la dirección pública, nunca la clave."
            )
        raise AddressError("La dirección base58 tiene que empezar por 1 o por 3.")
    try:
        raw = _b58decode(value)
    except ValueError as exc:
        raise AddressError("La dirección base58 tiene un carácter inválido.") from exc
    if len(raw) != 25:
        raise AddressError("La dirección base58 no tiene el tamaño de una dirección pública.")
    payload, checksum = raw[:-4], raw[-4:]
    digest = hashlib.sha256(hashlib.sha256(payload).digest()).digest()
    if digest[:4] != checksum:
        raise AddressError("El checksum de la dirección base58 no cuadra.")
    version = payload[0]
    if version == 0x80:
        raise AddressError("Eso es una clave privada, no una dirección.")
    if version not in (0x00, 0x05):
        raise AddressError("Esa versión de dirección no es P2PKH ni P2SH de mainnet.")
    if value[0] == "1" and version != 0x00:
        raise AddressError("La dirección que empieza por 1 no es P2PKH.")
    if value[0] == "3" and version != 0x05:
        raise AddressError("La dirección que empieza por 3 no es P2SH.")
    return value


def _bech32_polymod(values: list[int]) -> int:
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for value in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ value
        for i in range(5):
            if (top >> i) & 1:
                chk ^= generator[i]
    return chk


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convertbits(data: list[int], from_bits: int, to_bits: int, pad: bool) -> list[int] | None:
    acc = 0
    bits = 0
    ret: list[int] = []
    maxv = (1 << to_bits) - 1
    max_acc = (1 << (from_bits + to_bits - 1)) - 1
    for value in data:
        if value < 0 or (value >> from_bits):
            return None
        acc = ((acc << from_bits) | value) & max_acc
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (to_bits - bits)) & maxv)
    elif bits >= from_bits or ((acc << (to_bits - bits)) & maxv):
        return None
    return ret


def _b58decode(text: str) -> bytes:
    num = 0
    for char in text:
        idx = _BASE58_ALPHABET.find(char)
        if idx < 0:
            raise ValueError(char)
        num = num * 58 + idx
    pad = 0
    for char in text:
        if char == "1":
            pad += 1
        else:
            break
    body = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    return b"\x00" * pad + body
