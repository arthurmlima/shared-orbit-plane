"""Bit-exact reference of the hardware multi-pseudo-orbit (pairwise LBE) keystream, rtl/lbe_unit.v.

Arithmetic: x in unsigned Q0.32, r in Q2.32, mul(a, b) = (a * b) >> 32 (truncation).
Forms (k of them, all start from the same x0 for each 8x8 block):
  F1 = mul(mul(R, x), 1 - x)          F2 = mul(R, x) - mul(mul(R, x), x)
  F3 = mul(R, x - mul(x, x))          F4 = mul(x, R - mul(R, x))
  F5 = mul(R, mul(x, 1 - x))          F6 = mul(R, x) - mul(R, mul(x, x))
Key (8 x 32-bit words K0..K7, same registers as the ChaCha unit) and nonce (N0 = stream, N1, N2 = frame):
  R = 0x3E6666666 + (K2 >> 4)   (r in [3.9, 3.9625))
  kmix = xorshift32 chain over K0..K7, N0, N1, N2 starting from 0:  a = xs(a ^ word), xs = the
         xorshift32 step (a ^= a << 13; a ^= a >> 17; a ^= a << 5), computed once per start.
  mixw(v, c) = xs(xs(kmix ^ (v + 1) * 0x9E3779B9) ^ c) for keystream block c (c = floor(y/8) * ceil(W/8) + floor(x/8)).
  All k orbits of block c start from the SAME seed x0(c) = range(mixw(0, c)), range(a) = (a & 0x3FFFFFFF) | 0x40000000,
  i.e. x0 in [0.25, 0.5): never 0, 1 or 1 - 2^-32 (fixed or absorbing points of the forms) and never in the
  tiny-seed region. The shared x0 is what makes every pair a lower-bound-error pair (Nepomuceno): both
  pseudo-orbits approximate the same exact orbit and differ only by their rounding. All 256 key bits and the
  96 nonce bits enter x0; every block and frame has a distinct x0.
  pert = p > 0: a keyed perturbation shared by all orbits. Its seed comes from a SECOND, 64-bit chain over
  the same 11 words, kmix64: s = xs64((s + (w << 32 | (w ^ GOLD))) mod 2^64) from 0 (additive absorption, so
  the mix is not linear over GF(2)); s0(c) = xs64(kmix64 ^ c), or GOLD64 if that is 0. Then
  s_{t+1} = xs64(s_t) (xorshift64: s ^= s << 13; s ^= s >> 7; s ^= s << 17), and every orbit steps
  x_{t+1} = F(x_t) XOR (s_{t+1} mod 2^p). The perturbation belongs to the system all orbits share, so the
  pairs stay LBE pairs; the orbits become non-autonomous (no exact period below 2^64 - 1). x0 is a function
  of the 32-bit kmix and s0 of the 64-bit kmix64, two different functions of the key, so the per-pass secret
  an attacker must guess is x0 + s0 = 30 + 64 = 94 bits (plus r when r is keyed).
Run T transient iterations, then L = ceil(64 / P) output iterations, P = k(k-1)/2 pairs in the order
(0,1), (0,2), ..., (k-2,k-1). Byte i of the block (i = (y mod 8) * 8 + x mod 8) is the LBE byte of pair
p = i mod P after output iteration t = i div P:
  D = |x_i - x_j| (32-bit), n = D shifted so its leading one is bit 31,
  byte = (n[22:15] XOR n[30:23])        (0 if D = 0)
i.e. mantissa bits 9..16 of the floating-point value of |d| (the fractional part of log2 LBE) folded with
mantissa bits 1..8. The fold hides the cycle relations between pair streams (scripts/lbe_cycle_test.py)."""
import struct
import numpy as np

W = 32
MASK = (1 << W) - 1
ONE = 1 << W
R_MIN = 0x3E6666666
GOLD = 0x9E3779B9


def mul(a, b):
    return (a * b) >> W


def form(f, x, R):
    if f == 0: return mul(mul(R, x), ONE - x)
    if f == 1: return mul(R, x) - mul(mul(R, x), x)
    if f == 2: return mul(R, x - mul(x, x))
    if f == 3: return mul(x, R - mul(R, x))
    if f == 4: return mul(R, mul(x, ONE - x))
    return mul(R, x) - mul(R, mul(x, x))


def lbe_byte(D):
    """Folded log-domain LBE byte: bits 9..16 below the leading one of D XOR bits 1..8 below it.
    (Bits 9..16 alone leave 4-cycle relations between pair streams visible; see scripts/lbe_cycle_test.py.)"""
    if D == 0:
        return 0
    n = D << (W - D.bit_length())          # leading one at bit 31
    return ((n >> 15) ^ (n >> 23)) & 0xFF


def key_words(key: bytes):
    return struct.unpack("<8I", key)


def xs(a):
    """One xorshift32 step on a 32-bit value (same as function xs in rtl/lbe_unit.v and rtl/lbe_dist.v)."""
    a ^= (a << 13) & MASK
    a ^= a >> 17
    a ^= (a << 5) & MASK
    return a & MASK


def key_mix(key: bytes, nonce: bytes):
    """kmix: xorshift32 chain over the 8 key words and the 3 nonce words, from 0 (11 steps in hardware)."""
    a = 0
    for w in list(key_words(key)) + list(struct.unpack("<3I", nonce)):
        a = xs(a ^ w)
    return a


M64 = (1 << 64) - 1


def xs64(s):
    """One xorshift64 step (13, 7, 17), same as function xs64 in the RTL: the keyed perturbation sequence."""
    s ^= (s << 13) & M64
    s ^= s >> 7
    s ^= (s << 17) & M64
    return s & M64


def mixw(v: int, kmix: int, c: int = 0):
    """Key-schedule word v for block counter c: xs(xs(kmix ^ (v + 1) * GOLD) ^ c)."""
    a = xs(kmix ^ ((GOLD * (v + 1)) & MASK))
    return xs(a ^ (c & MASK))


def seed_v(v: int, kmix: int, c: int = 0):
    """range(mixw(v, c)): a value in [0.25, 0.5). The design uses v = 0 only (shared seed, see seed_x0)."""
    return (mixw(v, kmix, c) & 0x3FFFFFFF) | 0x40000000


def seed_x0(kmix: int, c: int = 0):
    """The one seed all orbits of block c (or of a plane pass, c = 0) start from."""
    return seed_v(0, kmix, c)


GOLD64 = 0x9E3779B97F4A7C15


def key_mix64(key: bytes, nonce: bytes):
    """kmix64: xorshift64 chain with additive absorption over the 8 key words and 3 nonce words, from 0."""
    s = 0
    for w in list(key_words(key)) + list(struct.unpack("<3I", nonce)):
        s = xs64((s + ((w << 32) | (w ^ GOLD))) & M64)
    return s


def pert_seed(kmix64: int, c: int = 0):
    """Initial xorshift64 state of the keyed perturbation for block counter c: xs64(kmix64 ^ c), never 0."""
    s = xs64(kmix64 ^ (c & MASK))
    return s if s else GOLD64


def key_R(key: bytes):
    return R_MIN + (key_words(key)[2] >> 4)


def block(key: bytes, nonce: bytes, c: int, k: int = 4, T: int = 40, pert: int = 0):
    R = key_R(key)
    km = key_mix(key, nonce)
    km64 = key_mix64(key, nonce)
    pairs = [(i, j) for i in range(k) for j in range(i + 1, k)]
    P = len(pairs)
    L = -(-64 // P)
    x = [seed_x0(km, c)] * k
    s = pert_seed(km64, c)
    pmask = (1 << pert) - 1 if pert else 0
    out = bytearray(64)
    for it in range(T + L):
        s = xs64(s)
        pb = s & pmask
        x = [form(f, xi, R) ^ pb for f, xi in enumerate(x)]
        t = it - T
        if t >= 0:
            for p, (i, j) in enumerate(pairs):
                idx = t * P + p
                if idx < 64:
                    out[idx] = lbe_byte(abs(x[i] - x[j]))
    return bytes(out)


def keystream_image(key, nonce, Wimg, Himg, k=4, T=40, pert=0):
    bpr = -(-Wimg // 8)
    ks = np.zeros((Himg, Wimg), np.uint8)
    for by in range(-(-Himg // 8)):
        for bx in range(bpr):
            blk = block(key, nonce, by * bpr + bx, k, T, pert)
            for yy in range(8):
                for xx in range(8):
                    y, x = by * 8 + yy, bx * 8 + xx
                    if y < Himg and x < Wimg:
                        ks[y, x] = blk[yy * 8 + xx]
    return ks


def encrypt_image(img, key, nonce, k=4, T=40, pert=0):
    img = np.asarray(img, dtype=np.int64)
    return img ^ keystream_image(key, nonce, img.shape[1], img.shape[0], k, T, pert).astype(np.int64)


if __name__ == "__main__":
    key = bytes(range(32))
    nonce = struct.pack("<3I", 0, 1, 0)
    print("block 0:", block(key, nonce, 0).hex())
    print("block 1:", block(key, nonce, 1).hex())
