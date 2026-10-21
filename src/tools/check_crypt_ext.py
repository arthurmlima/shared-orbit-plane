#!/usr/bin/env python3
"""Check an encrypt/decrypt run of the orbit plane with extractor EXT: step1 == img ^ keystream, step2 == img.
usage: check_crypt_ext.py img.txt run_steps.txt W H N EXT [--pert p]"""
import sys, os, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'scripts'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'reference'))
import plane_ref
from chacha import TEST_KEY, frame_nonce
pert = 8
if '--pert' in sys.argv:
    i = sys.argv.index('--pert'); pert = int(sys.argv[i + 1]); del sys.argv[i:i + 2]
img_f, steps_f, W, H, N, EXT = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
img = np.loadtxt(img_f, dtype=int).reshape(H, W)
hw = np.loadtxt(steps_f, dtype=np.int64).reshape(8, H, W)
gold = plane_ref.encrypt_image(img, TEST_KEY, frame_nonce(1, 0), N, EXT, T=64, lean=6, pert=pert)
e1 = int((hw[1] != gold).sum()); e2 = int((hw[2] != img).sum())
print(f"N={N} EXT={EXT} cipher mismatches {e1}, decrypt mismatches {e2}", "MATCH" if e1 == 0 and e2 == 0 else "MISMATCH")
sys.exit(0 if e1 == 0 and e2 == 0 else 1)
