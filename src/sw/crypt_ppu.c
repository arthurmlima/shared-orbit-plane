/* Encrypt-only workload with the S-local keystream unit.
 *   step 1 = step 0 XOR keystream   (encrypt)
 *   step 2 = step 1 XOR keystream   (decrypt, must equal step 0)
 * Test key 00..1f (RFC 8439 example key; not secret), frame nonce (stream 0, frame 1). */
#include "mpriscv.h"

static const uint32_t KEY[8] = { 0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c,
                                 0x13121110, 0x17161514, 0x1b1a1918, 0x1f1e1d1c };

int main(void)
{
    ks_set_key(KEY);
    ks_set_nonce(0, 1, 0);
    mark(1); ks_start(); ppu_unary(PPU_XORKS, 0, 1, 0); barrier();
    mark(2); ks_start(); ppu_unary(PPU_XORKS, 1, 2, 0); barrier();
    mark(3);
    return 0;
}
