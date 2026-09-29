"""AES-256-GCM in pure Python (standard library only).

Used only to decrypt the small rendezvous messages (a few hundred bytes, a few times per outage),
so speed does not matter. If the `cryptography` package happens to be installed, it is used
instead. The pure implementation is checked against NIST test vectors and against `cryptography`
in tests/test_aesgcm.py.
"""
from __future__ import annotations

import hmac
import os


def _lib():
    """cryptography's AESGCM if installed (and not disabled with KALEBRIDGE_PURE_AES=1), else None."""
    if os.environ.get("KALEBRIDGE_PURE_AES") == "1":
        return None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM
    except Exception:  # noqa: BLE001
        return None

_SBOX = [0] * 256


def _init_sbox() -> None:
    # Generate the AES S-box (multiplicative inverse in GF(2^8) + affine transform).
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        _SBOX[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    _SBOX[0] = 0x63


_init_sbox()


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _expand_key(key: bytes) -> list:
    if len(key) not in (16, 24, 32):
        raise ValueError("AES key must be 16, 24 or 32 bytes")
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return [sum(w[4 * r:4 * r + 4], []) for r in range(nr + 1)]


def _encrypt_block(rk: list, block: bytes) -> bytes:
    s = [block[i] ^ rk[0][i] for i in range(16)]
    nr = len(rk) - 1
    for rnd in range(1, nr + 1):
        s = [_SBOX[b] for b in s]
        # ShiftRows (state is column-major: index = 4*col + row)
        s = [s[(4 * ((c + r) % 4)) + r] for c in range(4) for r in range(4)]
        if rnd != nr:  # MixColumns
            out = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                t = a[0] ^ a[1] ^ a[2] ^ a[3]
                out += [a[i] ^ t ^ _xtime(a[i] ^ a[(i + 1) % 4]) for i in range(4)]
            s = out
        k = rk[rnd]
        s = [s[i] ^ k[i] for i in range(16)]
    return bytes(s)


def _gmul(x: int, y: int) -> int:
    r = 0xE1 << 120
    z = 0
    for i in range(127, -1, -1):
        if (y >> i) & 1:
            z ^= x
        x = (x >> 1) ^ r if x & 1 else x >> 1
    return z


def _ghash(h: int, aad: bytes, ct: bytes) -> int:
    y = 0
    for data in (aad, ct):
        for i in range(0, len(data), 16):
            blk = data[i:i + 16].ljust(16, b"\0")
            y = _gmul(y ^ int.from_bytes(blk, "big"), h)
    y = _gmul(y ^ ((len(aad) * 8) << 64 | (len(ct) * 8)), h)
    return y


def _ctr(rk: list, j0: bytes, data: bytes) -> bytes:
    out = bytearray()
    ctr = int.from_bytes(j0[12:], "big")
    for i in range(0, len(data), 16):
        ctr = (ctr + 1) & 0xFFFFFFFF
        ks = _encrypt_block(rk, j0[:12] + ctr.to_bytes(4, "big"))
        chunk = data[i:i + 16]
        out += bytes(a ^ b for a, b in zip(chunk, ks))
    return bytes(out)


def _j0(rk: list, h: int, iv: bytes) -> bytes:
    if len(iv) == 12:
        return iv + b"\0\0\0\1"
    return _ghash(h, b"", iv).to_bytes(16, "big")


def py_encrypt(key: bytes, iv: bytes, pt: bytes, aad: bytes = b"") -> bytes:
    rk = _expand_key(key)
    h = int.from_bytes(_encrypt_block(rk, b"\0" * 16), "big")
    j0 = _j0(rk, h, iv)
    ct = _ctr(rk, j0, pt)
    tag = (_ghash(h, aad, ct) ^ int.from_bytes(_encrypt_block(rk, j0), "big")).to_bytes(16, "big")
    return ct + tag


def py_decrypt(key: bytes, iv: bytes, ct_and_tag: bytes, aad: bytes = b"") -> bytes:
    if len(ct_and_tag) < 16:
        raise ValueError("ciphertext too short")
    ct, tag = ct_and_tag[:-16], ct_and_tag[-16:]
    rk = _expand_key(key)
    h = int.from_bytes(_encrypt_block(rk, b"\0" * 16), "big")
    j0 = _j0(rk, h, iv)
    want = (_ghash(h, aad, ct) ^ int.from_bytes(_encrypt_block(rk, j0), "big")).to_bytes(16, "big")
    if not hmac.compare_digest(want, tag):
        raise ValueError("authentication failed")
    return _ctr(rk, j0, ct)


def backend() -> str:
    return "cryptography" if _lib() else "pure-python"


def decrypt(key: bytes, iv: bytes, ct_and_tag: bytes, aad: bytes = b"") -> bytes:
    """Raises ValueError (or cryptography's InvalidTag) if the tag does not verify."""
    lib = _lib()
    return lib(key).decrypt(iv, ct_and_tag, aad) if lib else py_decrypt(key, iv, ct_and_tag, aad)


def encrypt(key: bytes, iv: bytes, pt: bytes, aad: bytes = b"") -> bytes:
    lib = _lib()
    return lib(key).encrypt(iv, pt, aad) if lib else py_encrypt(key, iv, pt, aad)
