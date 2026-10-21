#!/usr/bin/env python3
"""Run implementation checks, analyses, application simulations and FPGA jobs from source."""
import argparse
import ast
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / 'src'
PYTHON = sys.executable


def run(relative, *args, cwd=ROOT):
    path = ROOT / relative
    command = ['bash' if path.suffix == '.sh' else PYTHON, str(path), *map(str, args)]
    print('+ ' + ' '.join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))


def check():
    paths = sorted(p for p in ROOT.rglob('*.py') if not any(s.startswith('obj_') or s in ('build', '__pycache__') for s in p.relative_to(ROOT).parts))
    for path in paths:
        ast.parse(path.read_text(), filename=str(path.relative_to(ROOT)))
    jobs = sorted(p for p in ROOT.glob('**/fpga/jobs/*.json') if not p.name.endswith('.results.json'))
    count = 0
    for path in jobs:
        for job in json.loads(path.read_text())['jobs']:
            assert job['tag'] and job['generics'] and float(job['freq']) > 0, path
            count += 1
    print(f'Parsed {len(paths)} Python sources and {count} input FPGA jobs.')
    for name in ('numpy', 'sympy', 'scikit-image'):
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = 'not installed'
        print(f'{name}: {version}')
    for name in ('gcc', 'g++', 'make', 'iverilog', 'vvp', 'yosys', 'verilator', 'vivado'):
        value = os.environ.get(name.upper(), name)
        print(f'{name}: {shutil.which(value) or "not installed / not on PATH"}')


def unit():
    run('scripts/prepare_tests.py')
    run('experiments/extractor_check/run.py')
    run('src/sim/equiv/run_all.sh')
    for relative in ('experiments/xs64_baseline/run_unit.py', 'experiments/chaos_local/run_unit.py',
                     'experiments/quality/nardo2023/run_unit.py',
                     'experiments/quality/nardo2023/strided/run_unit.py'):
        run(relative)
    run('scripts/run_normalizer_checks.py')
    run('experiments/chaos_local/check_normalizer_subsystem.py')
    run('experiments/slow_consumer/run.py')


def quality():
    for relative in ('run_quality.py', 'check_adapter_rank.py', 'run_lag4.py', 'validate_quality.py', 'arbiter_consumer/run.py'):
        run('experiments/quality/' + relative)


def recurrence():
    run('experiments/tent_analysis/check_tent_period.py')
    run('src/quality/pert0_recurrence.py')
    run('src/quality/check_window_across.py')
    if (ROOT / 'experiments/quality/results.json').exists():
        run('experiments/tent_analysis/check_tent_quartet.py')
    else:
        raise SystemExit('Quartet diagnostic needs fresh quality results. Run the quality stage, then recurrence again.')


def firmware():
    run('scripts/build_firmware.py')
    run('scripts/generate_inputs.py')


def full_system():
    run('experiments/full_system/run_staged.py')
    for variant in ('xs64', 'local_logistic', 'tent_stride4'):
        run('experiments/full_system/run_native.py', variant)
    for n in (3, 4, 6):
        for ext in range(4):
            run('experiments/full_system/run_original.py', 'plane', '--n', n, '--ext', ext)
        for variant in ('trivium', 'chacha', 'none'):
            run('experiments/full_system/run_original.py', variant, '--n', n)


def fpga(parallel):
    jobs = [
        ('src', 'extractors.json'),
        ('src', 'e8_levelB.json'),
        ('src', 'e9_levelC.json'),
        ('src', 'e11_pert0.json'),
        ('experiments/chaos_local/normalizer_original', 'isolated.json'),
        ('experiments/chaos_local/normalizer_staged', 'isolated.json'),
        ('experiments/chaos_local/normalizer_staged', 'mesh.json'),
        ('experiments/xs64_baseline/prepared', 'xs64.json'),
        ('experiments/chaos_local/prepared', 'local_logistic.json'),
        ('experiments/quality/nardo2023/strided/prepared', 'tent.json'),
    ]
    for source, config in jobs:
        run(source + '/tools/run_vivado.py', ROOT / source / 'fpga/jobs' / config, '--parallel', parallel)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['check', 'unit', 'formal', 'quality', 'recurrence', 'firmware', 'full-system', 'fpga', 'collect', 'all'])
    parser.add_argument('--parallel', type=int, default=1, help='Concurrent Vivado jobs; default 1 to limit memory.')
    args = parser.parse_args()
    if args.parallel < 1:
        parser.error('--parallel must be positive')
    actions = {'check': check, 'unit': unit, 'formal': lambda: run('scripts/run_normalizer_checks.py', '--formal'),
               'quality': quality, 'recurrence': recurrence, 'firmware': firmware, 'full-system': full_system,
               'fpga': lambda: fpga(args.parallel), 'collect': lambda: run('scripts/collect_results.py')}
    for stage in actions if args.stage == 'all' else (args.stage,):
        print('\nSTAGE: ' + stage, flush=True)
        actions[stage]()


if __name__ == '__main__':
    main()
