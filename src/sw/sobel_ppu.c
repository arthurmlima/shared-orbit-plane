/* Same 8-step Sobel toolchain, each step executed by the Tile's PPU.
 * The core only sequences the steps, computes the global threshold and synchronises. */
#include "mpriscv.h"

#ifdef TREE_REDUCE
/* Two-level (row, then column) reduction: 4N mostly-neighbouring reads per Tile instead
 * of 2N^2 all-to-all reads. Row sums are published in step 0, which is dead after step 1. */
static int global_mean(int local_sum, int dst, int x0, int y0, int w, int h, int n)
{
    int id = mp_id(), mx = id % n, my = id / n;
    set_pixel(local_sum & 0xffff, x0, y0, dst, 0);
    set_pixel((local_sum >> 16) & 0xffff, x0 + 1, y0, dst, 0);
    barrier();
    unsigned row = 0;
    for (int tx = 0; tx < n; tx++) {
        int ox = MP_ORG(tx, w, n), oy = MP_ORG(my, h, n);
        row += ((unsigned)(get_pixel(ox + 1, oy, dst, 0) & 0xffff) << 16) |
               (unsigned)(get_pixel(ox, oy, dst, 0) & 0xffff);
    }
    set_pixel(row & 0xffff, x0, y0, 0, 0);
    set_pixel((row >> 16) & 0xffff, x0 + 1, y0, 0, 0);
    barrier();
    unsigned total = 0;
    for (int ty = 0; ty < n; ty++) {
        int ox = MP_ORG(mx, w, n), oy = MP_ORG(ty, h, n);
        total += ((unsigned)(get_pixel(ox + 1, oy, 0, 0) & 0xffff) << 16) |
                 (unsigned)(get_pixel(ox, oy, 0, 0) & 0xffff);
    }
    return (int)(total / (unsigned)(w * h));
}
#else

/* Global threshold = mean of the whole image's step-`src` values, independent of how the
 * image is partitioned. Each Tile publishes its 32-bit local sum as two 16-bit pixels of
 * step `dst` at its own origin, then gathers the N*N partial sums (Tile origins follow the
 * same balanced partition rule as the hardware: x0(i) = i*W/N). */
static int global_mean(int local_sum, int dst, int x0, int y0, int w, int h, int n)
{
    set_pixel(local_sum & 0xffff, x0, y0, dst, 0);
    set_pixel((local_sum >> 16) & 0xffff, x0 + 1, y0, dst, 0);
    barrier();
    unsigned total = 0;
    for (int ty = 0; ty < n; ty++)
        for (int tx = 0; tx < n; tx++) {
            int ox = MP_ORG(tx, w, n), oy = MP_ORG(ty, h, n);
            unsigned lo = get_pixel(ox, oy, dst, 0) & 0xffff;
            unsigned hi = get_pixel(ox + 1, oy, dst, 0) & 0xffff;
            total += (hi << 16) | lo;
        }
    barrier();
    return (int)(total / (unsigned)(w * h));
}

#endif

static const int K_MEAN[9] = { 1, 1, 1,  1, 1, 1,  1, 1, 1 };
static const int K_SX[9]   = {-1, 0, 1, -2, 0, 2, -1, 0, 1 };
static const int K_SY[9]   = {-1,-2,-1,  0, 0, 0,  1, 2, 1 };
/* x/9 == (x*7282)>>16 exactly for 0 <= x <= 2295 (9 * 255) */
#define DIV9_SCALE 7282
#define DIV9_SHIFT 16

#if defined(ENCRYPT_OUTPUT) || defined(FUSED_ENCRYPT)
/* RFC 8439 test key (public); frame 1 of stream 0 */
static void ks_setup(void)
{
    static const uint32_t KEY[8] = { 0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c,
                                     0x13121110, 0x17161514, 0x1b1a1918, 0x1f1e1d1c };
    ks_set_key(KEY); ks_set_nonce(0, 1, 0); ks_start();
}
#endif

int main(void)
{
    int x0 = mp_xinit(), y0 = mp_yinit(), w = mp_img_w(), h = mp_img_h(), n = mp_n();

#ifdef KS_EARLY
    ks_setup();             /* the first keystream blocks are generated while Sobel runs */
#endif
    mark(1); ppu_halo(0); barrier();                         /* input halo */
             ppu_conv3x3(K_MEAN, DIV9_SCALE, DIV9_SHIFT, 0, 1, 1); barrier();
    mark(2); ppu_conv3x3(K_SX, 1, 0, 1, 2, 0);              barrier();
    mark(3); ppu_conv3x3(K_SY, 1, 0, 1, 3, 0);              barrier();
    mark(4); ppu_unary(PPU_ABS, 2, 4, 0);                   barrier();
    mark(5); ppu_unary(PPU_ABS, 3, 5, 0);                   barrier();
    mark(6); ppu_binary(PPU_ADD, 4, 5, 6, 0);               barrier();
    mark(7);
    int t = global_mean(ppu_sum(6), 7, x0, y0, w, h, n);
#ifdef FUSED_ENCRYPT
    /* encrypt-on-writeback: the threshold op XORs the keystream into its result, so the
     * plaintext edge map is never stored and no extra pass is needed */
#ifndef KS_EARLY
    ks_setup();
#endif
    ppu_threshold(6, 7, t, 255, 0, PPU_F_ENC);              barrier();
    mark(8);
#else
    ppu_threshold(6, 7, t, 255, 0, 0);                      barrier();
    mark(8);
#ifdef ENCRYPT_OUTPUT
    /* separate pass: encrypt the edge map (step 7) into step 0, which is dead after step 1 */
#ifndef KS_EARLY
    ks_setup();
#endif
    ppu_unary(PPU_XORKS, 7, 0, 0);                          barrier();
    mark(9);
#endif
#endif
    return 0;
}
