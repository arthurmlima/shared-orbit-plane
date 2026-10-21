"""Bit-exact reference of the distributed multi-pseudo-orbit generator (rtl/lbe_dist.v, KS_IMPL = 5).

Orbit plane: an N x N mesh runs 2N pseudo-orbits of the logistic map from ONE seed per pass:
  row orbit R_y, computed by tile (y, y), broadcast to the N tiles of row y;
  column orbit C_x, computed by tile (x, (x + 1) mod N), broadcast to the N tiles of column x.
Every orbit uses a different finite-precision variant v of the map (row y: v = 2y, column x: v = 2x + 1):
  expression e = v mod 6 (F1..F6 as in lbe_ref.py) evaluated with g = v div 6 guard bits
  (intermediate products kept with 32 + g fractional bits, the result truncated back to Q0.32).
Tile (x, y) owns the pair (R_y, C_x): after T transient iterations, iteration T + 1 + j gives byte j of the
tile's keystream = lbe_ref.lbe_byte(|R_y - C_x|) (folded log-domain LBE byte).
Byte j encrypts the tile's j-th pixel in raster order (the PPU sweep). N^2 distinct pairs from 2N orbits.
Seed: all 2N orbits of a pass start from the SAME x0 = range(xs(xs(kmix ^ GOLD))) in [0.25, 0.5) (lbe_ref:
kmix = xorshift32 chain over the 8 key words and 3 nonce words), so every pair (R_y, C_x) is a genuine
lower-bound-error pair: two pseudo-orbits of one exact orbit that differ only by their rounding.
pert = p > 0: keyed perturbation shared by all orbits (lbe_ref.key_mix64 / pert_seed / xs64): one xorshift64
state per pass, seeded from a 64-bit key chain, stepped once per iteration, its low p bits XORed into every
new orbit value. All orbits see the same perturbation, so the pairs stay LBE pairs; the orbits become
non-autonomous and the per-pass secret is x0 (30 bits, 32-bit chain) + s0 (64 bits, 64-bit chain) = 94 bits
(122 with keyed r).
The ciphertext depends on N (each tile's stream is sequential), unlike the per-block generators.
form_v(v, x, R, lean=k) is the multiplier-lean variant: r = 4 - 2^-k and every multiply by r becomes
(t << 2) - (t >> k) (one multiply per form instead of two); R is ignored."""
import struct
import numpy as np
from lbe_ref import R_MIN, GOLD, MASK, lbe_byte, key_mix, key_mix64, seed_x0, pert_seed, xs64, key_R

W = 32


def form_v(v, x, R, lean=0):
    """Variant v of the logistic map on Q0.32 state x, r in Q2.32 (or r = 4 - 2^-lean, shift-subtract)."""
    e, g = v % 6, v // 6
    S = W + g
    ONE = 1 << S
    xx = x << g
    m = lambda a, b: (a * b) >> S
    if lean:
        RR = ((1 << 34) - (1 << (32 - lean))) << g
        rm = lambda t: (t << 2) - (t >> lean)
    else:
        RR = R << g
        rm = lambda t: m(RR, t)
    rx = rm(xx)
    if e == 0: y = m(rx, ONE - xx)
    elif e == 1: y = rx - m(rx, xx)
    elif e == 2: y = rm(xx - m(xx, xx))
    elif e == 3: y = m(xx, RR - rx)
    elif e == 4: y = rm(m(xx, ONE - xx))
    else: y = rx - rm(m(xx, xx))
    return (y >> g) & MASK


def seed(key: bytes, nonce: bytes):
    """(kmix, R) for this key and nonce."""
    return key_mix(key, nonce), key_R(key)


def orbit_seeds(key: bytes, nonce: bytes, N):
    """Start values of the N row orbits (variant 2y) and N column orbits (variant 2x + 1): all equal to x0."""
    x0 = seed_x0(key_mix(key, nonce))
    return [x0] * N, [x0] * N


def plane_iter(key, nonce, N, iters, lean=0, pert=0):
    """Yields (rows, cols) after each of the first `iters` iterations of a pass (the T transient ones included)."""
    R = key_R(key)
    rows, cols = orbit_seeds(key, nonce, N)
    s = pert_seed(key_mix64(key, nonce))
    pmask = (1 << pert) - 1 if pert else 0
    for _ in range(iters):
        s = xs64(s)
        pb = s & pmask
        rows = [form_v(2 * y, v, R, lean) ^ pb for y, v in enumerate(rows)]
        cols = [form_v(2 * x + 1, v, R, lean) ^ pb for x, v in enumerate(cols)]
        yield rows, cols


def tiles(Wimg, N):
    return [((i * Wimg) // N, ((i + 1) * Wimg) // N) for i in range(N)]


def keystream_image(key, nonce, Wimg, Himg, N, T=64, lean=0, pert=0):
    xs, ys = tiles(Wimg, N), tiles(Himg, N)
    need = max((x1 - x0_) * (y1 - y0) for x0_, x1 in xs for y0, y1 in ys)
    out = {(tx, ty): bytearray() for tx in range(N) for ty in range(N)}
    for it, (rows, cols) in enumerate(plane_iter(key, nonce, N, T + need, lean, pert)):
        if it >= T:
            for ty in range(N):
                for tx in range(N):
                    out[(tx, ty)].append(lbe_byte(abs(rows[ty] - cols[tx])))
    ks = np.zeros((Himg, Wimg), np.uint8)
    for ty, (y0, y1) in enumerate(ys):
        for tx, (xa, xb) in enumerate(xs):
            n = (xb - xa) * (y1 - y0)
            ks[y0:y1, xa:xb] = np.frombuffer(bytes(out[(tx, ty)][:n]), np.uint8).reshape(y1 - y0, xb - xa)
    return ks


def tile_streams(key, nonce, N, nbytes, T=64, lean=0, pert=0):
    """nbytes keystream bytes of every tile of an N x N plane, as a (N, N, nbytes) uint8 array [ty, tx]."""
    out = np.zeros((N, N, nbytes), np.uint8)
    for it, (rows, cols) in enumerate(plane_iter(key, nonce, N, T + nbytes, lean, pert)):
        if it >= T:
            for ty in range(N):
                for tx in range(N):
                    out[ty, tx, it - T] = lbe_byte(abs(rows[ty] - cols[tx]))
    return out


def encrypt_image(img, key, nonce, N, T=64, lean=0, pert=0):
    img = np.asarray(img, dtype=np.int64)
    return img ^ keystream_image(key, nonce, img.shape[1], img.shape[0], N, T, lean, pert).astype(np.int64)


if __name__ == "__main__":
    key = bytes(range(32)); nonce = struct.pack("<3I", 0, 1, 0)
    km, R = seed(key, nonce)
    print(f"kmix {km:08x} R {R:09x}")
    print("row seeds", [f"{s:08x}" for s in orbit_seeds(key, nonce, 3)[0]], "col seeds", [f"{s:08x}" for s in orbit_seeds(key, nonce, 3)[1]])
    ks = keystream_image(key, nonce, 24, 24, 3)
    print(ks[:2])
