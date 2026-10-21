#!/usr/bin/env python3
"""Fused Sobel + encrypt-on-write-back with extractor EXT: steps 1..6 == golden, step 7 == Enc(golden step 7).
usage: check_sobel_ext.py img.txt run_steps.txt N W H EXT [--pert p]"""
import sys, os, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'scripts'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'reference'))
import plane_ref
from golden import pipeline
from chacha import TEST_KEY, frame_nonce
pert = 8
if '--pert' in sys.argv:
    i = sys.argv.index('--pert'); pert = int(sys.argv[i + 1]); del sys.argv[i:i + 2]
img_f, steps_f, n, W, H, EXT = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
img = np.loadtxt(img_f, dtype=int).reshape(H, W)
hw = np.loadtxt(steps_f, dtype=np.int64).reshape(8, H, W)
g, t = pipeline(img, n)
bad = 0
for s in range(1, 7):
    gs = ((g[s].astype(np.int64) + 32768) % 65536) - 32768
    bad += int((hw[s] != gs).sum())
enc = plane_ref.encrypt_image(g[7].astype(int), TEST_KEY, frame_nonce(1, 0), n, EXT, T=64, lean=6, pert=pert)
e = int((hw[7] != enc).sum())
print(f"N={n} EXT={EXT} pipeline mismatches {bad}, ciphertext mismatches {e}", "MATCH" if bad == 0 and e == 0 else "MISMATCH")
sys.exit(0 if bad == 0 and e == 0 else 1)
