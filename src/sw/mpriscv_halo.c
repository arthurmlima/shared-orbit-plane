/* Runtime library variant linked by crypt_ppu.
 * This is mpriscv.c with the halo-only PPU control expression.
 * Compiling this source with GCC 13.4.0 and the supplied recipe reproduces
 * crypt_ppu_O2.hex byte exactly: SHA256
 * 6a231712a27d7f9f834dacacb5194caaceefae6bc781c7cd86d2be95e7cefb9f.
 * This library does not support fused-encryption flags. It is selected only
 * for crypt_ppu; fused/tree workloads use mpriscv.c.
 */
#include "mpriscv.h"
int mp_xinit(void) { return MP_CFG[0]; }
int mp_yinit(void) { return MP_CFG[1]; }
int mp_tw(void)    { return MP_CFG[2]; }
int mp_th(void)    { return MP_CFG[3]; }
int mp_img_w(void) { return MP_CFG[4]; }
int mp_img_h(void) { return MP_CFG[5]; }
int mp_n(void)     { return MP_CFG[6]; }
int mp_id(void)    { return MP_CFG[7]; }

int get_pixel(int x, int y, int s, int f)
{
    return *(volatile int32_t *)(MP_GET_BASE | MP_ENC(x, y, s, f));
}
void set_pixel(int pixel, int x, int y, int s, int f)
{
    *(volatile int32_t *)(MP_SET_BASE | MP_ENC(x, y, s, f)) = pixel;
}
void barrier(void) { *MP_BARRIER = 0; }
void mark(int id)  { *MP_MARK = id; }

static void ppu_run(int op, int a, int b, int dst, int halo)
{
    PPU_REG[16] = op | (a << 4) | (b << 8) | (dst << 12) |
                  (halo ? PPU_HALO_OUT : 0);
}
void ppu_conv3x3(const int *k, int scale, int shift, int src, int dst, int halo)
{
    for (int i = 0; i < 9; i++) PPU_REG[i] = k[i];
    PPU_REG[9] = scale; PPU_REG[10] = shift;
    ppu_run(PPU_CONV3, src, 0, dst, halo);
}
void ppu_unary(int op, int src, int dst, int halo)        { ppu_run(op, src, 0, dst, halo); }
void ppu_binary(int op, int a, int b, int dst, int halo)  { ppu_run(op, a, b, dst, halo); }
void ppu_threshold(int src, int dst, int thr, int hi, int lo, int halo)
{
    PPU_REG[11] = thr; PPU_REG[12] = hi; PPU_REG[13] = lo;
    ppu_run(PPU_THRESH, src, 0, dst, halo);
}
int ppu_sum(int src) { ppu_run(PPU_SUM, src, 0, 0, 0); return PPU_REG[17]; }
void ppu_halo(int step) { ppu_run(PPU_HALO, step, 0, 0, 0); }

void ks_set_key(const uint32_t key[8]) { for (int i = 0; i < 8; i++) KS_REG[i] = key[i]; }
void ks_set_nonce(uint32_t stream, uint32_t frame_lo, uint32_t frame_hi)
{
    KS_REG[8] = stream; KS_REG[9] = frame_lo; KS_REG[10] = frame_hi;
}
void ks_start(void) { KS_REG[15] = 1; }
uint32_t ks_blocks(void) { return KS_REG[0]; }
