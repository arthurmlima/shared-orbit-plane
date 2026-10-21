#!/usr/bin/env python3
"""Verify the 'shared 16-byte window across tiles' diagnostic with exact bytes (no hashing) for fold and nwin."""
import json, sys
from pathlib import Path
import numpy as np
P = Path(__file__).resolve().parent
sys.path.insert(0, str(P / '..' / 'tools'))
import plane_ref
ref = plane_ref.ref
cfg = json.loads((P / 'heldout/config.json').read_text())
N, T, L = 6, 64, 20000
out = {}
for ki, pair in enumerate(cfg['key_nonce_pairs']):
    key, nonce = bytes.fromhex(pair['key']), bytes.fromhex(pair['nonce'])
    R = np.empty((L, N), np.int64); C = np.empty_like(R)
    for t, (rows, cols) in enumerate(ref.plane_iter(key, nonce, N, L + T, 6, 8)):
        if t >= T: R[t - T] = rows; C[t - T] = cols
    D = np.abs(R[:, :, None] - C[:, None, :])
    bl = np.where(D > 0, np.floor(np.log2(np.maximum(D, 1))).astype(np.int64) + 1, 0)
    norm = np.where(D > 0, D << np.maximum(32 - bl, 0), 0)
    for name, S in [('fold', (((norm >> 15) ^ (norm >> 23)) & 255)), ('nwin', ((norm >> 15) & 255)), ('window', ((D >> 8) & 255)), ('xor', (((R[:, :, None] ^ C[:, None, :]) >> 8) & 255))]:
        flat = S.astype(np.uint8).transpose(1, 2, 0).reshape(N * N, L)
        seen = {}
        hits = []
        for t in range(N * N):
            s = flat[t].tobytes()
            for j in range(L - 16 + 1):
                w = s[j:j + 16]
                if w in seen and seen[w][0] != t: hits.append((seen[w], (t, j)))
                seen.setdefault(w, (t, j))
        out[f'{name}_key{ki}'] = {'exact_shared_windows': len(hits), 'examples': [list(map(list, h)) for h in hits[:3]]}
    print('key', ki, 'done', flush=True)
(P / 'window_across_exact.json').write_text(json.dumps(out, indent=1) + '\n')
print(json.dumps({k: v['exact_shared_windows'] for k, v in out.items()}))
