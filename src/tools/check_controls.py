#!/usr/bin/env python3
"""Ciphertext check of the control units (Trivium per tile, ChaCha20 per tile) on the encrypt and decrypt pass.
usage: check_controls.py img.txt run_steps.txt N trivium|chacha"""
import sys, os, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'baseline', 'reference_original'))
sys.path.insert(0, os.path.join(HERE, '..', 'reference'))
import chacha, tile_streams
img_f, steps_f, N, kind = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
img = np.loadtxt(img_f, dtype=np.int64).reshape(120, 120)
hw = np.loadtxt(steps_f, dtype=np.int64).reshape(8, 120, 120)
key, nonce = chacha.TEST_KEY, chacha.frame_nonce(1, 0)
enc = tile_streams.encrypt_image(img, 'triv', key, nonce, N) if kind == 'trivium' else np.array(chacha.encrypt_image(img.tolist(), key, nonce, 20, 1))
e1 = int((hw[1] != enc).sum()); e2 = int((hw[2] != img).sum())
print(f"N={N} {kind} cipher mismatches {e1}, decrypt mismatches {e2}", "MATCH" if e1 == 0 and e2 == 0 else "MISMATCH")
sys.exit(0 if e1 == 0 and e2 == 0 else 1)
