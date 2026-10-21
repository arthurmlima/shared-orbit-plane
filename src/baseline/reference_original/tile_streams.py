"""Per-tile keystreams of the baseline units (rtl/trivium_unit.v, rtl/grain_unit.v) and the expected
ciphertext of the full-mesh runs.

Mapping (track decision): from the 256-bit key K (32 bytes, key words little-endian as for ChaCha) and the
96-bit nonce (12 bytes; the firmware's frame nonce = stream id (4 bytes) || frame counter (8 bytes)):
  Trivium : key = K[0:10] (first 80 key bits); IV = nonce[0:9] (nonce bits 0..71) || tile index (1 byte)
  Grain   : key = K[0:16];                    IV = nonce[0:11] || tile index (1 byte)
Key bits 80..255 (Trivium) / 128..255 (Grain) and nonce bits 72..95 (Trivium) / 88..95 (Grain) are unused.
Tile (x, y) of an N x N mesh has index y * N + x and owns the pixels [x0, x1) x [y0, y1) with
x0 = floor(x * W / N) (balanced partition of rtl/mpriscv.v, PART_ALIGN = 1). Byte j of a pass encrypts the
tile's j-th pixel in raster order; every pass restarts the stream.
kinds: 'triv' (8 bits/cycle), 'g16z' (Grain, 8 even pre-output bits = AEADv2 keystream),
       'g8y' (Grain, all 8 pre-output bits per cycle; not the AEADv2 keystream).
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trivium_ref, grain_ref


def unit_stream(kind, key: bytes, nonce: bytes, tile: int, nbytes: int) -> bytes:
    if kind == "triv":
        return trivium_ref.keystream(key[:10], nonce[:9] + bytes([tile & 0xFF]), nbytes)
    if kind == "g16z":
        return grain_ref.z_bytes(key[:16], nonce[:11] + bytes([tile & 0xFF]), nbytes)
    if kind == "g8y":
        return grain_ref.y_bytes(key[:16], nonce[:11] + bytes([tile & 0xFF]), nbytes)
    raise ValueError(kind)


def tiles(L, N):
    return [((i * L) // N, ((i + 1) * L) // N) for i in range(N)]


def keystream_image(kind, key, nonce, W, H, N):
    ks = np.zeros((H, W), np.uint8)
    for ty, (y0, y1) in enumerate(tiles(H, N)):
        for tx, (x0, x1) in enumerate(tiles(W, N)):
            n = (x1 - x0) * (y1 - y0)
            s = unit_stream(kind, key, nonce, ty * N + tx, n)
            ks[y0:y1, x0:x1] = np.frombuffer(s, np.uint8).reshape(y1 - y0, x1 - x0)
    return ks


def encrypt_image(img, kind, key, nonce, N):
    img = np.asarray(img, dtype=np.int64)
    return img ^ keystream_image(kind, key, nonce, img.shape[1], img.shape[0], N).astype(np.int64)
