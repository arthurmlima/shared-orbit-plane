#!/usr/bin/env python3
"""Bit-exact software reference of the orbit plane with the four byte extractors.

Generator arithmetic, key schedule and perturbation are imported unchanged from the baseline references
(baseline/reference_original/lbe_dist_ref.py and lbe_ref.py). Only the byte extraction is parameterized:
  ext 0  normalized fold   D = |a-b|, n = D << lz, byte = n[22:15] ^ n[30:23], 0 if D = 0   (lbe_ref.lbe_byte)
  ext 1  difference window byte = D[15:8]
  ext 2  pairwise XOR      byte = (a ^ b)[15:8]
  ext 3  normalized window byte = n[22:15], 0 if D = 0
Usage:
  plane_ref.py vectors OUT.txt            directed + random (a, b) vectors with the four expected bytes
  plane_ref.py expected N OUT.mem KEYS    expected.mem for the equivalence bench (keys.mem format)
"""
import os, sys, struct
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, '..', 'baseline', 'reference_original')
sys.path.insert(0, BASE)
import lbe_ref                      # noqa: E402
import lbe_dist_ref as ref          # noqa: E402

W = 32
MASK = (1 << W) - 1
EXT_NAMES = {0: 'fold', 1: 'window', 2: 'xor', 3: 'nwin'}


def ext_byte(ext, a, b):
    a &= MASK; b &= MASK
    if ext == 2:
        return ((a ^ b) >> 8) & 0xFF
    D = a - b if a >= b else b - a
    if ext == 1:
        return (D >> 8) & 0xFF
    if D == 0:
        return 0
    n = D << (W - D.bit_length())
    if ext == 3:
        return (n >> 15) & 0xFF
    return ((n >> 15) ^ (n >> 23)) & 0xFF


def _check_fold_matches_baseline():
    rng = np.random.default_rng(1)
    for _ in range(2000):
        a, b = (int(v) for v in rng.integers(0, 1 << 32, 2, dtype=np.uint64))
        assert ext_byte(0, a, b) == lbe_ref.lbe_byte(abs(a - b))


_check_fold_matches_baseline()


def tile_streams(key, nonce, N, nbytes, ext=0, T=64, lean=6, pert=8):
    """uint8[N, N, nbytes] bytes of every tile [ty, tx], extractor ext."""
    out = np.zeros((N, N, nbytes), np.uint8)
    for it, (rows, cols) in enumerate(ref.plane_iter(key, nonce, N, T + nbytes, lean, pert)):
        if it >= T:
            for ty in range(N):
                for tx in range(N):
                    out[ty, tx, it - T] = ext_byte(ext, rows[ty], cols[tx])
    return out


def keystream_image(key, nonce, Wimg, Himg, N, ext=0, T=64, lean=6, pert=8):
    xs, ys = ref.tiles(Wimg, N), ref.tiles(Himg, N)
    need = max((x1 - x0) * (y1 - y0) for x0, x1 in xs for y0, y1 in ys)
    out = {(tx, ty): bytearray() for tx in range(N) for ty in range(N)}
    for it, (rows, cols) in enumerate(ref.plane_iter(key, nonce, N, T + need, lean, pert)):
        if it >= T:
            for ty in range(N):
                for tx in range(N):
                    out[(tx, ty)].append(ext_byte(ext, rows[ty], cols[tx]))
    ks = np.zeros((Himg, Wimg), np.uint8)
    for ty, (y0, y1) in enumerate(ys):
        for tx, (xa, xb) in enumerate(xs):
            n = (xb - xa) * (y1 - y0)
            ks[y0:y1, xa:xb] = np.frombuffer(bytes(out[(tx, ty)][:n]), np.uint8).reshape(y1 - y0, xb - xa)
    return ks


def encrypt_image(img, key, nonce, N, ext=0, T=64, lean=6, pert=8):
    img = np.asarray(img, dtype=np.int64)
    return img ^ keystream_image(key, nonce, img.shape[1], img.shape[0], N, ext, T, lean, pert).astype(np.int64)


def vectors():
    """Directed and random (a, b) pairs: list of (a, b)."""
    v = []
    for a in [0, 1, 0x80000000, 0xFFFFFFFF, 0x12345678]:
        v.append((a, a))                                  # D = 0
    for d in [1, 2, 3]:
        v += [(0x40000000 + d, 0x40000000), (0x40000000, 0x40000000 + d)]
    for k in range(32):
        v += [(1 << k, 0), (0, 1 << k), ((1 << k) - 1, 0), (0, (1 << k) - 1),
              (0xA5A5A5A5, (0xA5A5A5A5 - (1 << k)) & MASK), ((0xA5A5A5A5 - (1 << k)) & MASK, 0xA5A5A5A5)]
    v += [(0, 0xFFFFFFFF), (0xFFFFFFFF, 0), (0x7FFFFFFF, 0x80000000), (0x80000000, 0x7FFFFFFF)]
    for lead in [31, 30, 23, 22, 15, 14, 8, 7, 0]:
        d = (1 << lead) | ((0x5A5A5A5A) & ((1 << lead) - 1))
        v += [(d, 0), (0, d), (0xC0000000 + d if lead < 30 else d, 0xC0000000 if lead < 30 else 0)]
    for seed in (11, 22, 33):
        rng = np.random.default_rng(seed)
        arr = rng.integers(0, 1 << 32, (100000, 2), dtype=np.uint64)
        v += [(int(a), int(b)) for a, b in arr]
    return v


def main():
    cmd = sys.argv[1]
    if cmd == 'vectors':
        v = vectors()
        with open(sys.argv[2], 'w') as f:
            for a, b in v:
                f.write(f"{a:08x} {b:08x} " + ' '.join(f"{ext_byte(e, a, b):02x}" for e in range(4)) + '\n')
        print(len(v), 'vectors')
    elif cmd == 'expected':
        N, out, keys = int(sys.argv[2]), sys.argv[3], sys.argv[4]
        ext = int(sys.argv[5]) if len(sys.argv) > 5 else 0
        tw = 120 // N
        words = [int(w, 16) for w in open(keys).read().split()]
        with open(out, 'w') as f:
            for cs in range(len(words) // 11):
                kw = words[cs * 11:(cs + 1) * 11]
                key = struct.pack('<8I', *kw[:8]); nonce = struct.pack('<3I', *kw[8:11])
                s = tile_streams(key, nonce, N, tw * tw, ext)
                for ty in range(N):
                    for tx in range(N):
                        for j in range(tw * tw):
                            f.write(f"{int(s[ty, tx, j]):02x}\n")
        print('expected', N, ext, out)
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
