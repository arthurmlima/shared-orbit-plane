#!/usr/bin/env python3
"""Independent integer reference for the in-house local logistic control.

This specifies a new control, not a reproduction of an external design.
All arithmetic follows the LEAN=6 form_v(0), U0.32 recurrence.
"""
MASK32 = (1 << 32) - 1
MASK64 = (1 << 64) - 1
GOLD32 = 0x9e3779b9
GOLD64 = 0x9e3779b97f4a7c15


def xs32(value):
    value = (value ^ (value << 13)) & MASK32
    value = (value ^ (value >> 17)) & MASK32
    return (value ^ (value << 5)) & MASK32


def xs64(value):
    value = (value ^ (value << 13)) & MASK64
    value = (value ^ (value >> 7)) & MASK64
    return (value ^ (value << 17)) & MASK64


def seeds(words, tile):
    if len(words) != 11:
        raise ValueError('Exactly eleven 32-bit configuration words required')
    mixed32 = mixed64 = 0
    for word in words:
        word &= MASK32
        mixed32 = xs32(mixed32 ^ word)
        mixed64 = xs64((mixed64 + ((word << 32) | (word ^ GOLD32))) & MASK64)
    mixed_tile = xs32(xs32(mixed32 ^ ((GOLD32 * (tile + 1)) & MASK32)))
    state = 0x40000000 | (mixed_tile & 0x3fffffff)
    perturb = xs64(mixed64 ^ ((GOLD64 * (tile + 1)) & MASK64)) or GOLD64
    return state, perturb


def step(state, perturb, lean=6, pert=8):
    # form_v(0): rx=floor(r*x*2^32), x'=floor(rx*(1-x)/2^32).
    # Fixed r=4-2^-LEAN uses the original shift/subtract implementation.
    rx = (state << 2) - (state >> lean)
    mapped = (rx * ((1 << 32) - state)) >> 32
    perturb = xs64(perturb)
    state = (mapped ^ (perturb & ((1 << pert) - 1))) & MASK32
    return state, perturb


def stream(words, tile, n, transient=64, lean=6, pert=8):
    """Return n bytes x[15:8]; first state follows transient+1 steps.

    The extra step matches lbe_dist's it>=T+1 emission convention. Native
    local advance is demand-driven after initialization, so stalls do not
    alter the emitted sequence. Different tile seeds do not imply independent
    streams. The construction makes no cryptographic or period guarantee.
    """
    state, perturb = seeds(words, tile)
    for _ in range(transient + 1):
        state, perturb = step(state, perturb, lean, pert)
    result = bytearray(n)
    for i in range(n):
        result[i] = (state >> 8) & 255
        state, perturb = step(state, perturb, lean, pert)
    return result
