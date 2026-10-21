"""Bit-exact Python reference of Grain-128AEADv2 (Hell, Johansson, Maximov, Meier, Soennerup, Yoshida;
NIST LWC final round, spec grain-128aead-spec-final.pdf, Sections 2.1-2.6).

State: LFSR s_0..s_127, NFSR b_0..b_127, kept here as sequences s[t], b[t] (register at time t holds
s[t..t+127], b[t..t+127]).
  y_t      = h + s_{t+93} + sum_{j in A} b_{t+j},  A = {2, 15, 36, 45, 64, 73, 89}
  h        = x0 x1 + x2 x3 + x4 x5 + x6 x7 + x0 x4 x8 with (x0..x8) = (b12, s8, s13, s20, b95, s42, s60, s79, s94)
  L(S_t)   = s_t + s_{t+7} + s_{t+38} + s_{t+70} + s_{t+81} + s_{t+96}
  F(B_t)   = b_t + b26 + b56 + b91 + b96 + b3 b67 + b11 b13 + b17 b18 + b27 b59 + b40 b48 + b61 b65 + b68 b84
             + b22 b24 b25 + b70 b78 b82 + b88 b92 b93 b95                (indices relative to t)
  s_{t+128} = L(S_t) + y_t [t < 384] + k_{t-256} [320 <= t < 384]
  b_{t+128} = s_t + F(B_t) + y_t [t < 384] + k_{t-320} [320 <= t < 384]
Load: b_i = k_i (i < 128), s_i = IV_i (i < 96), s_96..s_126 = 1, s_127 = 0.
Accumulator a = y_384..y_447, shift register r = y_448..y_511; keystream z_i = y_{512+2i}, authentication
bits z'_i = y_{512+2i+1}. Bytes are read LSB first (key byte p bit j = k_{8p+j}; same for IV, data, tag).
The AEAD function follows the NIST-API mapping of Sec. 2.6 and the designers' reference code
(DER-encoded AD length || AD unencrypted, message encrypted, padding bit 1, 64-bit tag).
"""
import numpy as np

A_SET = (2, 15, 36, 45, 64, 73, 89)
W = 32           # chunk width: new bits enter at index 128, the highest tap is 96, so 32 steps are independent


def _bits(data: bytes, n: int):
    return np.array([(data[i // 8] >> (i % 8)) & 1 for i in range(n)], np.uint8)


def _pack(bits):
    bits = np.asarray(bits, np.uint8)
    nb = len(bits) // 8
    return (bits[:8 * nb].reshape(nb, 8) << np.arange(8, dtype=np.uint8)).sum(axis=1).astype(np.uint8).tobytes()


class Grain:
    def __init__(self, key: bytes, iv: bytes, extra_steps: int):
        """Runs the 512 initialisation clocks plus `extra_steps` pre-output clocks; y holds every y_t."""
        k = _bits(key, 128)
        n = 512 + extra_steps
        L = ((n + W - 1) // W) * W
        s = np.zeros(L + 128, np.uint8); b = np.zeros(L + 128, np.uint8); y = np.zeros(L, np.uint8)
        b[:128] = k
        s[:96] = _bits(iv, 96)
        s[96:127] = 1
        self.load_s, self.load_b = s[:128].copy(), b[:128].copy()
        for t in range(0, L, W):
            S = lambda o: s[t + o:t + o + W]
            B = lambda o: b[t + o:t + o + W]
            x0, x4 = B(12), B(95)
            h = (x0 & S(8)) ^ (S(13) & S(20)) ^ (x4 & S(42)) ^ (S(60) & S(79)) ^ (x0 & x4 & S(94))
            yy = h ^ S(93)
            for j in A_SET:
                yy = yy ^ B(j)
            Lf = S(0) ^ S(7) ^ S(38) ^ S(70) ^ S(81) ^ S(96)
            Ff = (B(0) ^ B(26) ^ B(56) ^ B(91) ^ B(96) ^ (B(3) & B(67)) ^ (B(11) & B(13)) ^ (B(17) & B(18))
                  ^ (B(27) & B(59)) ^ (B(40) & B(48)) ^ (B(61) & B(65)) ^ (B(68) & B(84))
                  ^ (B(22) & B(24) & B(25)) ^ (B(70) & B(78) & B(82)) ^ (B(88) & B(92) & B(93) & B(95)))
            tt = np.arange(t, t + W)
            fb = np.where(tt < 384, yy, 0).astype(np.uint8)
            kl = np.where((tt >= 320) & (tt < 384), k[np.clip(tt - 256, 0, 127)], 0).astype(np.uint8)
            kn = np.where((tt >= 320) & (tt < 384), k[np.clip(tt - 320, 0, 127)], 0).astype(np.uint8)
            s[t + 128:t + 128 + W] = Lf ^ fb ^ kl
            b[t + 128:t + 128 + W] = S(0) ^ Ff ^ fb ^ kn
            y[t:t + W] = yy
        self.s, self.b, self.y, self.n = s, b, y, n

    def state_bytes(self, t):
        """(NFSR, LFSR) at time t as 16-byte strings (LSB first), as printed in the specification."""
        return _pack(self.b[t:t + 128]), _pack(self.s[t:t + 128])

    def acc_reg_bytes(self):
        return _pack(self.y[384:448]), _pack(self.y[448:512])


def z_bytes(key: bytes, iv: bytes, nbytes: int, skip_bits: int = 0) -> bytes:
    """Encryption keystream z_i = y_{512+2i} (i >= skip_bits), packed LSB first."""
    nz = skip_bits + 8 * nbytes
    g = Grain(key, iv, 2 * nz)
    return _pack(g.y[512 + 2 * skip_bits:512 + 2 * nz:2])


def y_bytes(key: bytes, iv: bytes, nbytes: int) -> bytes:
    """All pre-output bits y_512, y_513, ... packed LSB first (NOT the AEADv2 encryption keystream)."""
    g = Grain(key, iv, 8 * nbytes)
    return _pack(g.y[512:512 + 8 * nbytes])


def der(n: int) -> bytes:
    if n < 128:
        return bytes([n])
    bs = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(bs)]) + bs


def aead_encrypt(key: bytes, iv: bytes, ad: bytes, pt: bytes) -> bytes:
    """NIST-API Grain-128AEADv2 encryption: ciphertext || 64-bit tag."""
    adb = der(len(ad)) + ad
    nad, nm = 8 * len(adb), 8 * len(pt)
    g = Grain(key, iv, 2 * (nad + nm) + 1)
    y = g.y
    acc = [int(v) for v in y[384:448]]
    sr = [int(v) for v in y[448:512]]
    t = 512
    mbits = list(_bits(adb, nad)) + list(_bits(pt, nm)) if (nad + nm) else []
    cbits = []
    for i, m in enumerate(mbits):
        z, za = int(y[t]), int(y[t + 1])
        t += 2
        if i >= nad:
            cbits.append(m ^ z)
        if m:
            acc = [a ^ r for a, r in zip(acc, sr)]
        sr = sr[1:] + [za]
    # padding bit 1: its keystream bit is generated (unused) and the accumulator absorbs the register
    t += 1
    acc = [a ^ r for a, r in zip(acc, sr)]
    return _pack(cbits) + _pack(acc)


if __name__ == "__main__":
    k = bytes(range(16)); n = bytes(range(12))
    print(aead_encrypt(k, n, b"", b"").hex().upper())
