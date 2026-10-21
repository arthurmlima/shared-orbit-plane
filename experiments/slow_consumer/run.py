#!/usr/bin/env python3
"""Bounded RTL experiment; never edits the source experiment tree."""
import csv
import hashlib
import json
import re
import shutil
import subprocess
import struct
import sys
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / 'src'


def main():
    rtl = HERE / 'rtl'
    rtl.mkdir(exist_ok=True)
    manifest = {}
    for name in ('lbe_dist.v', 'lbe_ext.vh', 'mpriscv_defs.vh', 'matched_tile.v', 'plane_mesh.v'):
        original = (SRC / 'rtl' / name).read_text()
        text = original
        if name == 'matched_tile.v':
            text = text.replace('parameter TW=30, TH=30, T=64, LEAN=6, PERT=8',
                                'parameter TW=30, TH=30, T=64, LEAN=6, PERT=8, DEPTH=32')
            text = text.replace('.DEPTH(32)', '.DEPTH(DEPTH)')
        elif name == 'plane_mesh.v':
            text = text.replace('parameter N = 4, TW = 30, TH = 30, MODE = 3, PRIVATE = 0, EXT = 0, LEAN = 6, PERT = 8, T = 64,',
                                'parameter N = 4, TW = 30, TH = 30, MODE = 3, PRIVATE = 0, EXT = 0, LEAN = 6, PERT = 8, T = 64, DEPTH = 32,')
            text = text.replace('.LEAN(LEAN), .PERT(PERT)) u', '.LEAN(LEAN), .PERT(PERT), .DEPTH(DEPTH)) u')
        (rtl / name).write_text(text)
        manifest[name] = {'expected_sha256': hashlib.sha256(original.encode()).hexdigest(),
                          'experiment_sha256': hashlib.sha256(text.encode()).hexdigest()}
    (HERE / 'source_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    shutil.copy2(SRC / 'sim/equiv/keys.mem', HERE / 'keys.mem')
    rows = []
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(SRC / 'tools'))
    from plane_ref import tile_streams
    words = [int(word, 16) for word in (HERE / 'keys.mem').read_text().split()[:11]]
    key, nonce = struct.pack('<8I', *words[:8]), struct.pack('<3I', *words[8:])
    jobs = [(3, ext, depth, slow, 0) for ext in (0, 2) for depth in (4, 8, 32, 64) for slow in (1, 2, 4, 8)]
    jobs += [(n, 0, 32, slow, 0) for n in (4, 6) for slow in (1, 2, 4, 8)]
    jobs += [(n, 0, 32, 1, 1) for n in (3, 4, 6)]
    jobs += [(3, 2, 32, 1, 1)]
    previous = None
    for n, ext, depth, slow, coordinated in jobs:
        if previous != (n, ext):
            values = tile_streams(key, nonce, n, 1600, ext).flatten()
            (HERE / 'expected.mem').write_text(''.join(f'{int(v):02x}\n' for v in values))
            previous = (n, ext)
        name = f'n{n}_e{ext}_d{depth}_s{slow}_c{coordinated}'
        executable = HERE / f'{name}.vvp'
        command = [os.environ.get('IVERILOG','iverilog'), '-g2012', f'-I{rtl}', '-s', 'tb_slow',
                   '-P', f'tb_slow.N={n}', '-P', f'tb_slow.PATTERN={coordinated}',
                   '-P', f'tb_slow.EXT={ext}', '-P', f'tb_slow.DEPTH={depth}',
                   '-P', f'tb_slow.SLOW={slow}', '-o', str(executable),
                   str(rtl / 'lbe_dist.v'), str(rtl / 'matched_tile.v'),
                   str(rtl / 'plane_mesh.v'), str(HERE / 'tb_slow.v')]
        compiled = subprocess.run(command, cwd=HERE, capture_output=True, text=True, check=True)
        completed = subprocess.run([os.environ.get('VVP','vvp'), str(executable)], cwd=HERE,
                                   capture_output=True, text=True, check=True)
        (HERE / f'{name}.log').write_text(compiled.stdout + compiled.stderr + completed.stdout + completed.stderr)
        line = next(line for line in completed.stdout.splitlines() if line.startswith('RESULT '))
        row = {key: int(value) for key, value in re.findall(r'(\w+)=(-?\d+)', line)}
        rows.append(row)
        print(line, flush=True)
        executable.unlink()
    with (HERE / 'results.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    (HERE / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')


if __name__ == '__main__':
    main()
