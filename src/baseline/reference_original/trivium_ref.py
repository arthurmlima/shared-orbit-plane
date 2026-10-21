"""Bit-exact Python reference of Trivium (De Canniere & Preneel, eSTREAM portfolio).

Specification (desc.pdf, eSTREAM): 288-bit state s1..s288.
  t1 = s66 + s93;  t2 = s162 + s177;  t3 = s243 + s288;  z = t1 + t2 + t3
  t1 += s91 s92 + s171;  t2 += s175 s176 + s264;  t3 += s286 s287 + s69
  (s1..s93) <- (t3, s1..s92); (s94..s177) <- (t1, s94..s176); (s178..s288) <- (t2, s178..s287)
Load: (s1..s93) = (K1..K80, 0..0); (s94..s177) = (IV1..IV80, 0..0); (s178..s288) = (0..0, 1, 1, 1);
4 * 288 = 1152 steps without output, then one keystream bit per step.

Byte/bit convention (eSTREAM phase-3 API, as in the ECRYPT test vectors): key byte p, bit k (k = 0 is
the LSB) is K_{80-8p-k}; same for the IV. Keystream bits are packed into bytes LSB first: byte j holds
z_{8j+1} in bit 0 ... z_{8j+8} in bit 7.

Two implementations: `_slow` (one step at a time, literal transcription of the specification) and the
default chunked one (64 steps at a time on numpy bit arrays, using the three-register recurrences);
`selftest()` checks that they agree.
"""
import numpy as np

INIT_STEPS = 4 * 288


def key_bits(b: bytes):
    """K_1..K_80 (index 0 = K_1) from 10 bytes in the eSTREAM convention. A shorter IV (the ECRYPT
    32- and 64-bit IV profiles) is zero-padded in front, which is what the published vectors require."""
    b = bytes(10 - len(b)) + bytes(b)
    K = [0] * 80
    for p in range(10):
        for k in range(8):
            K[79 - 8 * p - k] = (b[p] >> k) & 1
    return K


def load_state(key: bytes, iv: bytes):
    """State as a list s[0..287] with s[i-1] = s_i."""
    s = [0] * 288
    s[0:80] = key_bits(key)
    s[93:173] = key_bits(iv)
    s[285] = s[286] = s[287] = 1
    return s


def _step(s):
    t1 = s[65] ^ s[92]
    t2 = s[161] ^ s[176]
    t3 = s[242] ^ s[287]
    z = t1 ^ t2 ^ t3
    t1 ^= (s[90] & s[91]) ^ s[170]
    t2 ^= (s[174] & s[175]) ^ s[263]
    t3 ^= (s[285] & s[286]) ^ s[68]
    s[:] = [t3] + s[0:92] + [t1] + s[93:176] + [t2] + s[177:287]
    return z


def keystream_slow(key: bytes, iv: bytes, nbytes: int) -> bytes:
    s = load_state(key, iv)
    for _ in range(INIT_STEPS):
        _step(s)
    out = bytearray()
    for _ in range(nbytes):
        v = 0
        for k in range(8):
            v |= _step(s) << k
        out.append(v)
    return bytes(out)


def keystream(key: bytes, iv: bytes, nbytes: int) -> bytes:
    """nbytes keystream bytes (eSTREAM convention). Register sequences a, b, c: at time t register A holds
    a[t..t+92] with s_i = a[t+93-i], B holds b[t..t+83] (s_{93+i} = b[t+84-i]), C holds c[t..t+110]
    (s_{177+i} = c[t+111-i]); each step appends one bit to each sequence."""
    s = load_state(key, iv)
    nsteps = INIT_STEPS + 8 * nbytes
    W = 64
    nch = (nsteps + W - 1) // W
    L = nch * W
    a = np.zeros(L + 93, np.uint8); b = np.zeros(L + 84, np.uint8); c = np.zeros(L + 111, np.uint8)
    for i in range(1, 94):
        a[93 - i] = s[i - 1]
    for i in range(1, 85):
        b[84 - i] = s[93 + i - 1]
    for i in range(1, 112):
        c[111 - i] = s[177 + i - 1]
    z = np.zeros(L, np.uint8)
    for ch in range(nch):
        t = ch * W
        r = slice(t, t + W)
        A0, A1, A2, A24, A27 = a[t:t + W], a[t + 1:t + 1 + W], a[t + 2:t + 2 + W], a[t + 24:t + 24 + W], a[t + 27:t + 27 + W]
        B0, B1, B2, B6, B15 = b[t:t + W], b[t + 1:t + 1 + W], b[t + 2:t + 2 + W], b[t + 6:t + 6 + W], b[t + 15:t + 15 + W]
        C0, C1, C2, C24, C45 = c[t:t + W], c[t + 1:t + 1 + W], c[t + 2:t + 2 + W], c[t + 24:t + 24 + W], c[t + 45:t + 45 + W]
        z[r] = A27 ^ A0 ^ B15 ^ B0 ^ C45 ^ C0
        t1 = A27 ^ A0 ^ (A2 & A1) ^ B6
        t2 = B15 ^ B0 ^ (B2 & B1) ^ C24
        t3 = C45 ^ C0 ^ (C2 & C1) ^ A24
        b[t + 84:t + 84 + W] = t1
        c[t + 111:t + 111 + W] = t2
        a[t + 93:t + 93 + W] = t3
    zb = z[INIT_STEPS:INIT_STEPS + 8 * nbytes].reshape(nbytes, 8)
    return bytes((zb << np.arange(8, dtype=np.uint8)).sum(axis=1).astype(np.uint8).tobytes())


def port_vector(b: bytes) -> int:
    """80-bit RTL port value with bit (i-1) = K_i (or IV_i): the bit-reversal of the little-endian integer."""
    K = key_bits(b)
    return sum(bit << i for i, bit in enumerate(K))


def selftest(n=3, nbytes=300, seed=1):
    rng = np.random.default_rng(seed)
    for _ in range(n):
        k, v = bytes(rng.integers(0, 256, 10, dtype=np.uint8)), bytes(rng.integers(0, 256, 10, dtype=np.uint8))
        assert keystream(k, v, nbytes) == keystream_slow(k, v, nbytes)
    return True


if __name__ == "__main__":
    print("selftest", selftest())
    print(keystream(bytes.fromhex("80000000000000000000"), bytes(10), 16).hex().upper())
