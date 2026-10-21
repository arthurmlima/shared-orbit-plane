/* MPRISC-V Tile-code API (reproduction). */
#ifndef MPRISCV_H
#define MPRISCV_H
#include <stdint.h>

#define MP_GET_BASE 0x20000000u
#define MP_SET_BASE 0x30000000u
#define MP_BARRIER  ((volatile uint32_t *)0x40000000u)
#define MP_MARK     ((volatile uint32_t *)0x50000000u)
#define MP_CFG      ((volatile uint32_t *)0x70000000u)

#define MP_ENC(x, y, s, f) (((uint32_t)(f) << 24) | ((uint32_t)(s) << 20) | \
                            ((uint32_t)(y) << 12) | ((uint32_t)(x) << 2))

/* Hard-coded Tile setup */
int mp_xinit(void);
int mp_yinit(void);
int mp_tw(void);
int mp_th(void);
int mp_img_w(void);
int mp_img_h(void);
int mp_n(void);
int mp_id(void);
/* partition granularity of the hardware (PART_ALIGN) */
static inline int mp_part_align(void) { return ((volatile int *)0x70000000u)[8]; }

/* Origin (first column or row) of Tile i along an axis of length len, same rule as rtl/mpriscv.v.
 * Build with -DPART_ALIGN=A to match hardware built with PART_ALIGN = A (default 1). */
#ifndef PART_ALIGN
#define PART_ALIGN 1
#endif
#if PART_ALIGN == 1
#define MP_ORG(i, len, n) ((i) * (len) / (n))
#else
#define MP_ORG(i, len, n) ((i) >= (n) ? (len) : \
    (PART_ALIGN * ((i) * (((len) + PART_ALIGN - 1) / PART_ALIGN) / (n)) > (len) ? (len) : \
     PART_ALIGN * ((i) * (((len) + PART_ALIGN - 1) / PART_ALIGN) / (n))))
#endif

/* Fetch any pixel of MPRISC-V (local or remote) through the NoC. */
int  get_pixel(int x, int y, int s, int f);
/* Write a pixel into the local Pixel-Memory. */
void set_pixel(int pixel, int x, int y, int s, int f);
/* Global synchronisation of all Tiles. */
void barrier(void);
/* Timestamp marker for the host. */
void mark(int id);
#endif

/* ---- Pixel Processing Unit (PPU) API ---- */
#define PPU_REG ((volatile int32_t *)0x80000000u)
enum { PPU_CONV3 = 0, PPU_ABS = 1, PPU_MOV = 2, PPU_THRESH = 3, PPU_SUM = 4, PPU_HALO = 5,
       PPU_ADD = 8, PPU_SUB = 9, PPU_MAX = 10, PPU_MIN = 11, PPU_ABSDIFF = 12 };
#define PPU_HALO_OUT (1 << 16)   /* push border outputs to neighbours' halo */
#define PPU_ENC_OUT  (1 << 17)   /* XOR the keystream into every result as it is written */
/* flags for the last argument of the ppu_* calls */
#define PPU_F_HALO 1
#define PPU_F_ENC  2             /* encrypt-on-writeback (pointwise ops; needs the keystream unit) */
/* All calls sweep the whole Tile region and return when the PPU is done. */
void ppu_conv3x3(const int *k, int scale, int shift, int src, int dst, int halo);
void ppu_unary(int op, int src, int dst, int halo);
void ppu_binary(int op, int a, int b, int dst, int halo);
void ppu_threshold(int src, int dst, int thr, int hi, int lo, int halo);
int  ppu_sum(int src);
void ppu_halo(int step);

/* ---- Keystream unit (ChaCha, partition-invariant pixel keystream) ---- */
#define KS_REG ((volatile uint32_t *)0x90000000u)
#define PPU_XORKS 6                  /* PPU op: pixel ^= keystream byte (encrypt == decrypt) */
void ks_set_key(const uint32_t key[8]);
void ks_set_nonce(uint32_t stream, uint32_t frame_lo, uint32_t frame_hi);
void ks_start(void);                 /* restart the block prefetcher for a new sweep */
uint32_t ks_blocks(void);            /* blocks generated so far (statistics) */
