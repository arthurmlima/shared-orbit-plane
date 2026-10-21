#!/usr/bin/env python3
"""Ablation A1 software side: with the keyed perturbation removed (PERT = 0) every orbit is autonomous and eventually
periodic. For the four held-out keys and N in 3, 4, 6, 8: Brent tail (mu) and cycle (lambda) of every row and column
orbit variant from the pass seed x0 (exact hardware arithmetic, lean 6, cap 2^24), the number of tile streams whose
pass of 120/N x 120/N bytes reaches a cycle, and the 16-byte window repeats within and across tiles of the fold
streams (exact bytes) at N = 6 with 125,000 bytes per tile, compared with PERT = 8."""
import json, os, subprocess, sys
from pathlib import Path
import numpy as np
P = Path(__file__).resolve().parent
sys.path.insert(0, str(P / '..' / 'tools'))
import plane_ref
ref, lbe_ref = plane_ref.ref, plane_ref.lbe_ref
cfg = json.loads((P / 'heldout/config.json').read_text())
out = {'orbits': [], 'streams': {}}
lines = []
keys = [(bytes.fromhex(p['key']), bytes.fromhex(p['nonce'])) for p in cfg['key_nonce_pairs']]
for ki, (key, nonce) in enumerate(keys):
    x0 = lbe_ref.seed_x0(lbe_ref.key_mix(key, nonce))
    for v in range(16):
        lines.append(f"{0x3E6666666} {v} {x0} 6")
# Compile the exact finite-precision recurrence from source on every run.
subprocess.run([os.environ.get('CC', 'gcc'), '-O2', '-o', str(P / 'lbe_period'), str(P / 'lbe_period.c')], check=True)
res = subprocess.run([str(P / 'lbe_period')], input='\n'.join(lines) + '\n', capture_output=True, text=True, check=True).stdout.split('\n')
i = 0
for ki in range(4):
    for v in range(16):
        f = res[i].split(); i += 1
        out['orbits'].append({'key_index': ki, 'variant': v, 'mu': int(f[4]), 'lambda': int(f[5]), 'capped': int(f[6])})
for N in (3, 4, 6, 8):
    tw = 120 // N; Q = tw * tw
    cyc = 0; minmu = None
    for ki in range(4):
        for y in range(N):
            for x in range(N):
                o_r = next(o for o in out['orbits'] if o['key_index'] == ki and o['variant'] == 2 * y)
                o_c = next(o for o in out['orbits'] if o['key_index'] == ki and o['variant'] == 2 * x + 1)
                # a tile stream repeats within the pass only if both orbits are inside their cycles and lcm fits
                start, end = 64, 64 + Q
                inside = (not o_r['capped'] and not o_c['capped'] and o_r['mu'] <= start and o_c['mu'] <= start)
                if inside:
                    import math
                    L = math.lcm(o_r['lambda'], o_c['lambda'])
                    if L < Q: cyc += 1
    out['streams'][f'N{N}'] = {'tile_streams_checked': 4 * N * N, 'streams_with_period_shorter_than_pass': cyc, 'pass_bytes': Q}
# 16-byte repeats, fold, N = 6, 125,000 bytes, pert 0 and 8
N, T, L = 6, 64, 125000
for pert in (0, 8):
    rep = {'within': 0, 'across': 0}
    for ki, (key, nonce) in enumerate(keys):
        R = np.empty((L, N), np.int64); C = np.empty_like(R)
        for t, (rows, cols) in enumerate(ref.plane_iter(key, nonce, N, L + T, 6, pert)):
            if t >= T: R[t - T] = rows; C[t - T] = cols
        D = np.abs(R[:, :, None] - C[:, None, :])
        bl = np.where(D > 0, np.floor(np.log2(np.maximum(D, 1))).astype(np.int64) + 1, 0)
        norm = np.where(D > 0, D << np.maximum(32 - bl, 0), 0)
        S = (((norm >> 15) ^ (norm >> 23)) & 255).astype(np.uint8).transpose(1, 2, 0).reshape(N * N, L)
        seen = {}
        for t in range(N * N):
            s = S[t].tobytes()
            for j in range(L - 15):
                w = s[j:j + 16]
                if w in seen:
                    if seen[w][0] == t: rep['within'] += 1
                    else: rep['across'] += 1
                else: seen[w] = (t, j)
        # distinct 32-bit orbit values along each orbit (period evidence at the pass scale)
        if pert == 0 and ki == 0:
            out['distinct_values_key0'] = {f'v{v}': int(len(np.unique(np.concatenate([R, C], axis=1)[:, v]))) for v in range(2 * N)}
    out[f'window16_fold_N6_L125000_pert{pert}'] = rep
(P / 'pert0_recurrence.json').write_text(json.dumps(out, indent=1) + '\n')
print(json.dumps({k: v for k, v in out.items() if k != 'orbits'}, indent=1))
print('capped', sum(o['capped'] for o in out['orbits']), 'of', len(out['orbits']), 'min lambda', min(o['lambda'] for o in out['orbits'] if not o['capped']) if any(not o['capped'] for o in out['orbits']) else None)
