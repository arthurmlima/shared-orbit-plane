#!/usr/bin/env python3
"""Check deterministic initial states against separately written reference adapters."""
import json
import importlib.util
from pathlib import Path
from reproduce_seeds import ROOT, QUALITY_CONFIG
from seedlib import seed_record, local_initial, MASK64, G64


def load(relative, name):
    spec=importlib.util.spec_from_file_location(name,ROOT/relative)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def main():
    lg=load('experiments/chaos_local/local_logistic_ref.py','independent_local_logistic')
    tm=load('experiments/quality/nardo2023/strided/tent_ref.py','independent_local_tent')
    cfg=json.loads(QUALITY_CONFIG.read_text());comparisons=0
    for index,pair in enumerate(cfg['key_nonce_pairs']):
        seed=seed_record(index,pair['key'],pair['nonce'])
        a=int(seed['derived_mix32_hex'],16);b=int(seed['derived_mix64_hex'],16)
        raw=bytes.fromhex(pair['key']+pair['nonce'])
        words=[int.from_bytes(raw[p:p+4],'little') for p in range(0,44,4)]
        for n in (3,4,6,8):
            for tile in range(n*n):
                value=local_initial(a,b,tile+1)
                assert lg.seeds(words,tile)==(int(value['LG_x0_hex'],16),int(value['LG_s0_hex'],16))
                assert tm.seed(words,tile)==int(value['TM_state0_hex'],16)
                comparisons+=2
    # A salted raw zero must trigger distinct 64-bit XS and 32-bit TM fallbacks.
    for t in (1,2,36,64):
        value=local_initial(0,(t*G64)&MASK64,t)
        assert value['raw_q64_hex']=='0000000000000000'
        assert value['XS_state0_hex']==f'{G64:016x}'
        assert value['TM_state0_hex']=='00000001'
    print(json.dumps({'status':'PASS','independent_seed_comparisons':comparisons,
        'distinct_zero_fallback_cases':4,'scientific_recurrence_calls':0},indent=2))

if __name__=='__main__': main()
