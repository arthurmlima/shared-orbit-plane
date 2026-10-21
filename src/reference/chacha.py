"""ChaCha golden model and the partition-invariant pixel keystream used by MPRISC-V.

Keystream mapping (independent of how the image is split into tiles):
    blocks_per_row = ceil(W / 64)
    counter(x, y)  = y * blocks_per_row + x // 64        (32-bit block counter)
    byte(x, y)     = ChaCha_block(key, counter, nonce)[x % 64]
    nonce          = 96-bit frame nonce (frame id || stream id), unique per frame
    cipher(x, y)   = plain(x, y) XOR byte(x, y)          (8-bit pixels; decrypt = same op)
"""
import struct

MASK = 0xFFFFFFFF
SIGMA = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)   # "expand 32-byte k"


def rotl(v, c):
    return ((v << c) & MASK) | (v >> (32 - c))


def quarter(s, a, b, c, d):
    s[a] = (s[a] + s[b]) & MASK; s[d] = rotl(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & MASK; s[b] = rotl(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b]) & MASK; s[d] = rotl(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & MASK; s[b] = rotl(s[b] ^ s[c], 7)


def init_state(key: bytes, counter: int, nonce: bytes):
    assert len(key) == 32 and len(nonce) == 12
    return (list(SIGMA) + list(struct.unpack("<8I", key)) + [counter & MASK]
            + list(struct.unpack("<3I", nonce)))


def block(key: bytes, counter: int, nonce: bytes, rounds: int = 20) -> bytes:
    """One 64-byte ChaCha block (RFC 8439 layout: 32-bit counter, 96-bit nonce)."""
    x = init_state(key, counter, nonce)
    s = list(x)
    for _ in range(rounds // 2):
        quarter(s, 0, 4, 8, 12); quarter(s, 1, 5, 9, 13)
        quarter(s, 2, 6, 10, 14); quarter(s, 3, 7, 11, 15)
        quarter(s, 0, 5, 10, 15); quarter(s, 1, 6, 11, 12)
        quarter(s, 2, 7, 8, 13); quarter(s, 3, 4, 9, 14)
    return struct.pack("<16I", *[(s[i] + x[i]) & MASK for i in range(16)])


def frame_nonce(frame: int, stream: int = 0) -> bytes:
    return struct.pack("<IQ", stream & MASK, frame)


def blocks_per_row(W: int) -> int:
    return (W + 63) // 64


def keystream_image(key: bytes, nonce: bytes, W: int, H: int, rounds: int = 20, geom: int = 0):
    """Keystream byte for every pixel, as a list of rows.
    geom 0: 64x1 blocks, counter = y*ceil(W/64) + x//64, byte = x % 64
    geom 1: 8x8 blocks,  counter = (y//8)*ceil(W/8) + x//8, byte = (y%8)*8 + x%8"""
    if geom == 0:
        bpr = blocks_per_row(W)
        out = []
        for y in range(H):
            row = bytearray()
            for b in range(bpr):
                row += block(key, y * bpr + b, nonce, rounds)
            out.append(bytes(row[:W]))
        return out
    bpr = (W + 7) // 8
    cache = {}
    out = []
    for y in range(H):
        row = bytearray()
        for x in range(W):
            c = (y // 8) * bpr + x // 8
            if c not in cache:
                cache[c] = block(key, c, nonce, rounds)
            row.append(cache[c][(y % 8) * 8 + x % 8])
        out.append(bytes(row))
    return out


def encrypt_image(img, key: bytes, nonce: bytes, rounds: int = 20, geom: int = 0):
    """img: H x W nested list/array of 0..255; returns the same shape."""
    H, W = len(img), len(img[0])
    ks = keystream_image(key, nonce, W, H, rounds, geom)
    return [[int(img[y][x]) ^ ks[y][x] for x in range(W)] for y in range(H)]


# Fixed test key (NOT secret): bytes 0x00..0x1f, as in the RFC 8439 examples
TEST_KEY = bytes(range(32))


if __name__ == "__main__":
    import sys
    # 1) RFC 8439 section 2.3.2 block-function test vector
    k = bytes(range(32))
    n = bytes.fromhex("000000090000004a00000000")
    got = block(k, 1, n)
    rfc = bytes.fromhex(
        "10f1e7e4d13b5915500fdd1fa32071c4c7d1f4c733c068030422aa9ac3d46c4e"
        "d2826446079faa0914c2d705d98b02a2b5129cd1de164eb9cbd083e8a2503c4e")
    print("RFC 8439 2.3.2 block:", "OK" if got == rfc else "FAIL")
    # 2) cross-check against the 'cryptography' library over many counters/nonces
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    import os
    ok = True
    for t in range(200):
        key, nonce, ctr = os.urandom(32), os.urandom(12), int.from_bytes(os.urandom(4), "little")
        enc = Cipher(algorithms.ChaCha20(key, struct.pack("<I", ctr) + nonce), mode=None).encryptor()
        ok &= enc.update(bytes(64)) == block(key, ctr, nonce)
    print("cryptography lib cross-check (200 blocks):", "OK" if ok else "FAIL")
    sys.exit(0 if (got == rfc and ok) else 1)
