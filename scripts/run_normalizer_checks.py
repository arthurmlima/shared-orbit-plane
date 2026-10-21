#!/usr/bin/env python3
"""Check both normalizers on identical generated pairs and optionally prove A/EXT0."""
import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / 'experiments/chaos_local'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formal', action='store_true', help='Run the three-step Yosys SAT equivalence proof only.')
    args = parser.parse_args()
    out = ROOT / 'build/normalizer'
    out.mkdir(parents=True, exist_ok=True)
    if args.formal:
        command = [os.environ.get('YOSYS', 'yosys'), '-s', 'normalizer_equivalence.ys']
        with (out / 'formal.log').open('w') as log:
            subprocess.run(command, cwd=EXP, stdout=log, stderr=subprocess.STDOUT, check=True)
        print('SAT equivalence passed: A/EXT0, arbitrary inputs, three steps, common zero initialization.')
        return
    records = []
    for kind in ('original', 'staged'):
        root = EXP / f'normalizer_{kind}'
        work = root / 'verify'
        if not (work / 'vectors.txt').exists():
            raise SystemExit('Generate test inputs first: python3 scripts/prepare_tests.py')
        binary = out / f'{kind}.vvp'
        command = [os.environ.get('IVERILOG', 'iverilog'), '-g2012', f'-I{root / "rtl"}',
                   '-s', 'tb_extractors', '-o', str(binary), str(root / 'rtl/ext_bench.v'),
                   str(work / 'tb_extractors.v')]
        subprocess.run(command, cwd=work, check=True)
        result = subprocess.run([os.environ.get('VVP', 'vvp'), str(binary)], cwd=work,
                                capture_output=True, text=True, check=True)
        (out / f'{kind}.log').write_text(result.stdout + result.stderr)
        records.append({'variant': kind, 'stdout': result.stdout.strip(), 'command': command})
        print(kind + ': ' + result.stdout.strip(), flush=True)
    (out / 'checks.json').write_text(json.dumps(records, indent=2) + '\n')


if __name__ == '__main__':
    main()
