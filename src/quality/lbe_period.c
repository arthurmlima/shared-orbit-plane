/* Tail and cycle length of logistic-map pseudo-orbits in the exact hardware arithmetic of rtl/lbe_dist.v.
 *
 * Reads lines "R v x0 lean" (decimal) from stdin:
 *   R    r in Q2.32 (34-bit integer), e.g. 0x3E6666666 + key bits
 *   v    variant: expression v mod 6 (F1..F6), guard bits v div 6, as lbe_dist_ref.form_v
 *   x0   seed in Q0.32
 *   lean 0: multiply by R; k > 0: multiplier-lean r = 4 - 2^-k, r*t = (t << 2) - (t >> k) (R is ignored)
 * Prints "R v x0 lean mu lambda capped" with Brent's algorithm: mu = tail length, lambda = cycle length,
 * capped = 1 if mu + lambda exceeded the cap (default 1 << 24, override with argv[1]).
 * Built by scripts/lbe_period_scan.py: gcc -O2 -o lbe_period lbe_period.c */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

typedef unsigned __int128 u128;
static uint64_t MASK32 = 0xFFFFFFFFull;

static inline uint64_t form_v(int v, uint64_t x, uint64_t R, int lean) {
    int e = v % 6, g = v / 6;
    int S = 32 + g;
    u128 one = (u128)1 << S;
    u128 xx = (u128)x << g, rr = (u128)R << g;
    u128 p, rx, y;
    #define M(a, b) (((u128)(a) * (u128)(b)) >> S)
    #define LM(t) (lean ? ((((u128)(t)) << 2) - (((u128)(t)) >> lean)) : M(rr, (t)))
    if (lean) rr = (((u128)1 << 34) - ((u128)1 << (32 - lean))) << g;  /* R = 4 - 2^-k, for forms that use R - rx */
    rx = LM(xx);
    switch (e) {
        case 0: y = M(rx, one - xx); break;
        case 1: y = rx - M(rx, xx); break;
        case 2: p = xx - M(xx, xx); y = LM(p); break;
        case 3: y = M(xx, rr - rx); break;
        case 4: p = M(xx, one - xx); y = LM(p); break;
        default: p = M(xx, xx); y = rx - LM(p); break;
    }
    return (uint64_t)((y >> g) & MASK32);
}

int main(int argc, char **argv) {
    uint64_t cap = argc > 1 ? strtoull(argv[1], 0, 0) : (1ull << 24);
    unsigned long long R, x0; int v, lean;
    while (scanf("%llu %d %llu %d", &R, &v, &x0, &lean) == 4) {
        /* Brent: find lambda */
        uint64_t power = 1, lam = 1;
        uint64_t tort = x0, hare = form_v(v, x0, R, lean);
        int capped = 0;
        while (tort != hare) {
            if (power == lam) { tort = hare; power *= 2; lam = 0; }
            hare = form_v(v, hare, R, lean); lam++;
            if (power + lam > cap) { capped = 1; break; }
        }
        uint64_t mu = 0;
        if (!capped) {
            tort = hare = x0;
            for (uint64_t i = 0; i < lam; i++) hare = form_v(v, hare, R, lean);
            while (tort != hare) { tort = form_v(v, tort, R, lean); hare = form_v(v, hare, R, lean); mu++; }
        }
        printf("%llu %d %llu %d %llu %llu %d\n", R, v, x0, lean, (unsigned long long)mu, (unsigned long long)lam, capped);
    }
    return 0;
}
