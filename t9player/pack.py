"""Encrypted content packs (assets/pack.bin), each opened by its own code.

A pack can add a theme with everything it needs. The key is derived from the code itself (PBKDF2),
so the source does not contain the codes, and without the right code nothing in a pack can be read -
not even by editing the settings file. Settings keep the derived key of each opened pack.

Encryption: SHA-256 in counter mode as the key stream, HMAC-SHA-256 over nonce + ciphertext
(only the standard library is used).
"""

import base64
import hashlib
import hmac
import json
import os
import random
import zlib

ITERATIONS = 200_000


def _normal(code):
    return (code or "").strip().lower().encode("utf-8")


def derive(code, salt, iterations=ITERATIONS):
    """64 bytes: 32 for the cipher, 32 for the MAC."""
    return hashlib.pbkdf2_hmac("sha256", _normal(code), salt, iterations, dklen=64)


def _stream(key, nonce, size):
    out = bytearray()
    counter = 0
    while len(out) < size:
        out += hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(out[:size])


def _xor(data, stream):
    if not data:
        return b""
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big")


def _open_item(key, item):
    nonce = base64.b64decode(item["n"])
    cipher = base64.b64decode(item["c"])
    mac = hmac.new(key[32:], nonce + cipher, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, item["m"]):
        return None
    plain = _xor(cipher, _stream(key[:32], nonce, len(cipher)))
    return json.loads(zlib.decompress(plain).decode("utf-8"))


def seal(entries, iterations=ITERATIONS, salt=None):
    """Pack dict for [(code, payload), ...]."""
    salt = salt or os.urandom(16)
    items = []
    for code, payload in entries:
        key = derive(code, salt, iterations)
        nonce = os.urandom(16)
        plain = zlib.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"), 9)
        cipher = _xor(plain, _stream(key[:32], nonce, len(plain)))
        mac = hmac.new(key[32:], nonce + cipher, hashlib.sha256).hexdigest()
        items.append({"n": base64.b64encode(nonce).decode(), "c": base64.b64encode(cipher).decode(), "m": mac})
    random.SystemRandom().shuffle(items)          # the order says nothing about the contents
    return {"v": 1, "salt": base64.b64encode(salt).decode(), "iter": iterations, "items": items}


def load(path=None):
    """The pack dict, or None when the file is missing or damaged."""
    if path is None:
        from . import paths
        path = os.path.join(paths.ASSETS_DIR, "pack.bin")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) and data.get("items") else None
    except (OSError, ValueError):
        return None


def open_with_code(code, pack):
    """(key_hex, payload) for a code, or (None, None) when nothing opens with it."""
    if not pack or not (code or "").strip():
        return None, None
    key = derive(code, base64.b64decode(pack["salt"]), int(pack.get("iter", ITERATIONS)))
    for item in pack["items"]:
        try:
            payload = _open_item(key, item)
        except Exception:
            payload = None
        if payload is not None:
            return key.hex(), payload
    return None, None


def open_with_key(key_hex, pack):
    """Payload for a key saved in the settings, or None."""
    if not pack:
        return None
    try:
        key = bytes.fromhex(key_hex)
    except (TypeError, ValueError):
        return None
    if len(key) != 64:
        return None
    for item in pack["items"]:
        try:
            payload = _open_item(key, item)
        except Exception:
            payload = None
        if payload is not None:
            return payload
    return None
