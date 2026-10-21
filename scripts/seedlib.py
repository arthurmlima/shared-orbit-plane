#!/usr/bin/env python3
"""Fixed-width configuration mixing and initial-state arithmetic; never iterates a recurrence."""

MASK32=(1<<32)-1
MASK64=(1<<64)-1
G32=0x9e3779b9
G64=0x9e3779b97f4a7c15


def xs32(a):
    a=(a^((a<<13)&MASK32))&MASK32;a^=a>>17;return (a^((a<<5)&MASK32))&MASK32
def xs64(a):
    a=(a^((a<<13)&MASK64))&MASK64;a^=a>>7;return (a^((a<<17)&MASK64))&MASK64


def seed_record(index,key,nonce):
    raw=bytes.fromhex(key)+bytes.fromhex(nonce)
    assert len(bytes.fromhex(key))==32 and len(bytes.fromhex(nonce))==12
    m32=m64=0
    for pos in range(0,44,4):
        w=int.from_bytes(raw[pos:pos+4],'little');m32=xs32(m32^w)
        m64=xs64((m64+((w<<32)|(w^0x9e3779b9)))&MASK64)
    return {'index':index,'key':key,'nonce':nonce,'derived_mix32_hex':f'{m32:08x}','derived_mix64_hex':f'{m64:016x}',
            'derived_x0_hex':f'{0x40000000|(xs32(xs32(m32^0x9e3779b9))&0x3fffffff):08x}',
            'derived_s0_hex':f'{xs64(m64) or 0x9e3779b97f4a7c15:016x}'}


def plane_initial(a,b):
    return 0x40000000|(xs32(xs32(a^G32))&0x3fffffff), xs64(b) or G64


def local_initial(a,b,t):
    assert 0<=a<=MASK32 and 0<=b<=MASK64 and t>0
    raw=xs64(b^((t*G64)&MASK64))
    # TM fallback is applied to raw low32, independently of the XS fallback.
    return {'raw_q64_hex':f'{raw:016x}','XS_state0_hex':f'{raw or G64:016x}',
            'LG_x0_hex':f'{0x40000000|(xs32(xs32(a^((t*G32)&MASK32)))&0x3fffffff):08x}',
            'LG_s0_hex':f'{raw or G64:016x}','TM_state0_hex':f'{(raw&MASK32) or 1:08x}'}
