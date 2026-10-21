/* S-sw baseline: the same partition-invariant ChaCha keystream, computed in software on
 * each Tile's PicoRV32 and applied with get_pixel/set_pixel (local reads use the PM bypass).
 *   step 1 = step 0 XOR keystream   (encrypt)
 *   step 2 = step 1 XOR keystream   (decrypt)
 * Compile-time options: -DKS_GEOM=0|1 (64x1 or 8x8 blocks), -DKS_ROUNDS=8|12|20. */
#include "mpriscv.h"

#ifndef KS_GEOM
#define KS_GEOM 1
#endif
#ifndef KS_ROUNDS
#define KS_ROUNDS 20
#endif

static const uint32_t KEY[8] = { 0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c,
                                 0x13121110, 0x17161514, 0x1b1a1918, 0x1f1e1d1c };
static const uint32_t NONCE[3] = { 0, 1, 0 };          /* stream 0, frame 1 */

#define ROTL(v, c) (((v) << (c)) | ((v) >> (32 - (c))))
#define QR(a, b, c, d) \
    a += b; d ^= a; d = ROTL(d, 16); c += d; b ^= c; b = ROTL(b, 12); \
    a += b; d ^= a; d = ROTL(d, 8);  c += d; b ^= c; b = ROTL(b, 7);

static void chacha_block(uint32_t ctr, uint8_t out[64])
{
    uint32_t x[16] = { 0x61707865, 0x3320646e, 0x79622d32, 0x6b206574,
                       KEY[0], KEY[1], KEY[2], KEY[3], KEY[4], KEY[5], KEY[6], KEY[7],
                       ctr, NONCE[0], NONCE[1], NONCE[2] };
    uint32_t s[16];
    for (int i = 0; i < 16; i++) s[i] = x[i];
    for (int r = 0; r < KS_ROUNDS; r += 2) {
        QR(s[0], s[4], s[8], s[12]); QR(s[1], s[5], s[9], s[13]);
        QR(s[2], s[6], s[10], s[14]); QR(s[3], s[7], s[11], s[15]);
        QR(s[0], s[5], s[10], s[15]); QR(s[1], s[6], s[11], s[12]);
        QR(s[2], s[7], s[8], s[13]); QR(s[3], s[4], s[9], s[14]);
    }
    for (int i = 0; i < 16; i++) {
        uint32_t v = s[i] + x[i];
        out[4 * i] = v; out[4 * i + 1] = v >> 8; out[4 * i + 2] = v >> 16; out[4 * i + 3] = v >> 24;
    }
}

static int imax(int a, int b) { return a > b ? a : b; }
static int imin(int a, int b) { return a < b ? a : b; }

static void xor_keystream(int src, int dst, int x0, int y0, int tw, int th, int w)
{
    uint8_t ks[64];
#if KS_GEOM == 1
    int bpr = (w + 7) / 8;
    for (int by = y0 / 8; by <= (y0 + th - 1) / 8; by++)
        for (int bx = x0 / 8; bx <= (x0 + tw - 1) / 8; bx++) {
            chacha_block(by * bpr + bx, ks);
            for (int y = imax(by * 8, y0); y <= imin(by * 8 + 7, y0 + th - 1); y++)
                for (int x = imax(bx * 8, x0); x <= imin(bx * 8 + 7, x0 + tw - 1); x++)
                    set_pixel(get_pixel(x, y, src, 0) ^ ks[(y & 7) * 8 + (x & 7)], x, y, dst, 0);
        }
#else
    int bpr = (w + 63) / 64;
    for (int y = y0; y < y0 + th; y++)
        for (int bx = x0 / 64; bx <= (x0 + tw - 1) / 64; bx++) {
            chacha_block(y * bpr + bx, ks);
            for (int x = imax(bx * 64, x0); x <= imin(bx * 64 + 63, x0 + tw - 1); x++)
                set_pixel(get_pixel(x, y, src, 0) ^ ks[x & 63], x, y, dst, 0);
        }
#endif
}

int main(void)
{
    int x0 = mp_xinit(), y0 = mp_yinit(), tw = mp_tw(), th = mp_th(), w = mp_img_w();
    mark(1); xor_keystream(0, 1, x0, y0, tw, th, w); barrier();
    mark(2); xor_keystream(1, 2, x0, y0, tw, th, w); barrier();
    mark(3);
    return 0;
}
