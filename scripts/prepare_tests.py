#!/usr/bin/env python3
"""Generate test vectors and expected streams from source; no stored data needed."""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'src'


def main():
    for name in ('original', 'staged'):
        verify = ROOT / f'experiments/chaos_local/normalizer_{name}/verify'
        verify.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'experiments/extractor_check/tb_extractors.v', verify / 'tb_extractors.v')
        subprocess.run([sys.executable, str(BASE / 'tools/plane_ref.py'), 'vectors', str(verify / 'vectors.txt')], check=True)
    equiv = BASE / 'sim/equiv'
    for n in (3, 4, 6, 8):
        for ext in range(4):
            subprocess.run([sys.executable, str(BASE / 'tools/plane_ref.py'), 'expected', str(n),
                            str(equiv / f'expected_N{n}_E{ext}.mem'), str(equiv / 'keys.mem'), str(ext)], check=True)
    print('Directed/random extractor vectors and all subsystem reference streams regenerated.')


if __name__ == '__main__':
    main()
