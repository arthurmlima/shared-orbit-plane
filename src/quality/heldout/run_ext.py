#!/usr/bin/env python3
"""Held-out rectangle prediction for the four extractors (fresh run of the baseline protocol, same keys, same
predictor family, same split), plus per-extractor output diagnostics on the same streams:
byte histogram chi-square, zero bytes, exact duplicate streams, cross-tile equal-byte rate, 16-byte window repeats
within and across tiles, and the exact rectangle identity check for EXT 2."""
from pathlib import Path
import ctypes, hashlib, itertools, json, os, platform, subprocess, sys, time
import numpy as np
P = Path(__file__).resolve().parent
sys.path.insert(0, str(P / '..' / '..' / 'tools'))
import plane_ref                           # noqa: E402
ref = plane_ref.ref
N, T, L, SPLIT = 6, 64, 125000, 62500
EXTS = {0: 'fold', 1: 'window', 2: 'xor', 3: 'nwin'}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    if (P / 'results.json').exists(): raise RuntimeError('refusing to overwrite results.json')
    started = time.time()
    cfg = json.loads((P / 'config.json').read_text())
    pairs = cfg['key_nonce_pairs']
    subprocess.run([os.environ.get('CXX', 'g++'), '-O3', '-shared', '-fPIC', 'predict.cpp', '-o', 'predict.so'], cwd=P, check=True)
    lib = ctypes.CDLL(str(P / 'predict.so')); ptr = ctypes.POINTER(ctypes.c_uint8)
    lib.evaluate.argtypes = [ptr] * 4 + [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    def calc(arr, split):
        arr = [np.ascontiguousarray(x, dtype=np.uint8) for x in arr]; out = (ctypes.c_int * 3)()
        lib.evaluate(*(x.ctypes.data_as(ptr) for x in arr), len(arr[0]), split, out)
        return list(out)
    rects = [(y, y2, x, x2) for y, y2 in itertools.combinations(range(N), 2) for x, x2 in itertools.combinations(range(N), 2)]
    results, diag = [], []
    def score(B, ki, name):
        for y, y2, x, x2 in rects:
            pred, train, test = calc([B[y, x], B[y, x2], B[y2, x], B[y2, x2]], SPLIT)
            results.append({'key_index': ki, 'extraction': name, 'rectangle': [y, y2, x, x2], 'predictor_index': pred, 'train_correct': train, 'test_correct': test})
    def diagnostics(B, ki, name):
        flat = B.reshape(N * N, L)
        hist = np.stack([np.bincount(s, minlength=256) for s in flat])
        chi = ((hist - L / 256) ** 2 / (L / 256)).sum(axis=1)             # 255 degrees of freedom
        zeros = int((flat == 0).sum())
        dup = sum(1 for i in range(N * N) for j in range(i + 1, N * N) if np.array_equal(flat[i], flat[j]))
        eq = np.mean([np.mean(flat[i] == flat[j]) for i in range(N * N) for j in range(i + 1, N * N)])
        # 16-byte window repeats within a tile and across tiles (exact), on the first 20,000 bytes to bound cost
        Lw = 20000; win = 16
        keys = {}
        within = across = 0
        for t in range(N * N):
            s = flat[t, :Lw]
            v = np.lib.stride_tricks.sliding_window_view(s, win)
            codes = v.astype(np.uint64) @ (np.uint64(256) ** np.arange(win, dtype=np.uint64)[::-1] % np.uint64(2**61 - 1))
            codes = codes.astype(np.int64)
            u, c = np.unique(codes, return_counts=True)
            within += int((c - 1).sum())
            for code in u:
                keys.setdefault(int(code), set()).add(t)
        across = sum(1 for v in keys.values() if len(v) > 1)
        rect_exact = None
        if name == 'xor':
            y, y2, x, x2 = 0, 1, 0, 1
            rect_exact = bool(np.all((B[y, x] ^ B[y, x2] ^ B[y2, x]) == B[y2, x2]))
        diag.append({'key_index': ki, 'extraction': name, 'chi2_255_mean': float(chi.mean()), 'chi2_255_max': float(chi.max()),
                     'zero_bytes': zeros, 'zero_expected': N * N * L / 256, 'duplicate_streams': dup, 'cross_tile_equal_byte_rate': float(eq),
                     'window16_repeats_within_tiles_first20000': within, 'window16_codes_shared_across_tiles_first20000': across,
                     'rectangle_identity_exact_0101': rect_exact})
    for ki, pair in enumerate(pairs):
        key, nonce = bytes.fromhex(pair['key']), bytes.fromhex(pair['nonce'])
        R = np.empty((L, N), np.int64); C = np.empty_like(R)
        for t, (rows, cols) in enumerate(ref.plane_iter(key, nonce, N, L + T, 6, 8)):
            if t >= T: R[t - T] = rows; C[t - T] = cols
        D = np.abs(R[:, :, None] - C[:, None, :])
        bl = np.where(D > 0, np.floor(np.log2(np.maximum(D, 1))).astype(np.int64) + 1, 0)
        norm = np.where(D > 0, D << np.maximum(32 - bl, 0), 0)
        streams = {'fold': (((norm >> 15) ^ (norm >> 23)) & 255).astype(np.uint8),
                   'window': ((D >> 8) & 255).astype(np.uint8),
                   'xor': (((R[:, :, None] ^ C[:, None, :]) >> 8) & 255).astype(np.uint8),
                   'nwin': ((norm >> 15) & 255).astype(np.uint8)}
        # scalar cross-check of the vectorized extraction against plane_ref.ext_byte
        for t in [0, 1, 63, 62499, 62500, 124999]:
            for y in range(N):
                for x in range(N):
                    for e, name in EXTS.items():
                        assert streams[name][t, y, x] == plane_ref.ext_byte(e, int(R[t, y]), int(C[t, x]))
        for name, data in streams.items():
            B = np.ascontiguousarray(data.transpose(1, 2, 0))
            score(B, ki, name); diagnostics(B, ki, name)
        print('key', ki, 'done', round(time.time() - started, 1), 's', flush=True)
    cr = np.random.default_rng(cfg['control_rng_seed'])
    for ki in range(4):
        B = cr.integers(0, 256, (N, N, L), dtype=np.uint8); score(B, ki, 'uniform_control'); diagnostics(B, ki, 'uniform_control')
    summaries = []
    for name in ['fold', 'window', 'xor', 'nwin', 'uniform_control']:
        for ki in range(4):
            rows = [r for r in results if r['extraction'] == name and r['key_index'] == ki]
            worst = max(rows, key=lambda r: r['test_correct'])
            summaries.append({'extraction': name, 'key_index': ki, 'mean_test_percent': 100 * sum(r['test_correct'] for r in rows) / (225 * SPLIT),
                              'worst_test_percent': 100 * worst['test_correct'] / SPLIT, 'worst_rectangle': worst['rectangle'],
                              'mean_train_percent': 100 * sum(r['train_correct'] for r in rows) / (225 * SPLIT)})
    out = {'config_sha256': sha(P / 'config.json'), 'elapsed_seconds': time.time() - started, 'python': platform.python_version(), 'numpy': np.__version__,
           'all_outcomes': results, 'summaries': summaries, 'diagnostics': diag}
    (P / 'results.json').write_text(json.dumps(out) + '\n')
    (P / 'summary.json').write_text(json.dumps({'summaries': summaries, 'diagnostics': diag}, indent=2) + '\n')
    print(json.dumps(summaries, indent=1))

if __name__ == '__main__': main()
