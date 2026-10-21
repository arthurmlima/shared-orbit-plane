/* Encrypt-on-writeback (PPU_F_ENC) unit test on the whole mesh.
 *   step 3 = (step0 + step0) ^ ks        binary op, fused
 *   step 4 = MOV(step 3) ^ ks            unary op, fused (decrypts step 3)
 *   step 5 = THRESH(step0 > 100) ^ ks    threshold, fused
 * Test key 00..1f (RFC 8439 example key; not secret), frame nonce (stream 0, frame 1). */
#include "mpriscv.h"

static const uint32_t KEY[8] = { 0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c,
                                 0x13121110, 0x17161514, 0x1b1a1918, 0x1f1e1d1c };

int main(void)
{
    ks_set_key(KEY);
    ks_set_nonce(0, 1, 0);
    mark(1); ks_start(); ppu_binary(PPU_ADD, 0, 0, 3, PPU_F_ENC);           barrier();
    mark(2); ks_start(); ppu_unary(PPU_MOV, 3, 4, PPU_F_ENC);               barrier();
    mark(3); ks_start(); ppu_threshold(0, 5, 100, 255, 0, PPU_F_ENC);       barrier();
    mark(4);
    return 0;
}
