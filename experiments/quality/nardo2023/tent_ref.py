#!/usr/bin/env python3
"""Clean-room Nardo2023 Figure2 recurrence plus this study's byte/seed adapters.

Published mapping: b1 is MSB. Next vector is
(b2 XOR b1,...,bK XOR b1,b(K-1) XOR bK); K=32 matches a published width.
No change to recurrence, no nonlinear perturbation, and no warmup is added.
The published design emits a full fixed-point word. Our one-byte/take interface returns
current_state[7:0] and advances the word once on each accepted take.
"""
MASK32=(1<<32)-1
MASK64=(1<<64)-1
GOLD=0x9e3779b97f4a7c15

def xs64(value):
    value=(value^(value<<13))&MASK64
    value=(value^(value>>7))&MASK64
    return (value^(value<<17))&MASK64

def seed(words,tile):
    if len(words)!=11: raise ValueError('eleven configuration words required')
    mix=0
    for word in words:
        mix=xs64((mix+((word<<32)|(word^0x9e3779b9)))&MASK64)
    value=xs64(mix^((GOLD*(tile+1))&MASK64))&MASK32
    return value or 1

def step(value):
    # Independent scalar form follows the b1...bK indexing in Figure2.
    msb=(value>>31)&1
    result=0
    for bit in range(30,-1,-1):
        result=(result<<1)|(((value>>bit)&1)^msb)
    return (result<<1)|(((value>>1)^value)&1)

def step_fast(value):
    top=((value&0x7fffffff)^(0x7fffffff if value&0x80000000 else 0))<<1
    return top|(((value>>1)^value)&1)

def stream(words,tile,n):
    value=seed(words,tile)
    result=bytearray(n)
    for i in range(n):
        result[i]=value&255
        value=step_fast(value)
    return result
