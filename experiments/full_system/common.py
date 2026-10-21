#!/usr/bin/env python3
"""Local-only preparation and functional checks for complete processor meshes."""
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT/'src'
VARIANTS = {
    'plane': (SRC, None, None),
    'trivium': (SRC, None, None),
    'chacha': (SRC, None, None),
    'none': (SRC, None, None),
    'staged': (SRC, None, None),
    'xs64': (ROOT/'experiments/xs64_baseline/prepared', 'xs64_unit',
             '-GUSE_KS=1 -GKS_IMPL=8 -GKS_GEOM=0'),
    'local_logistic': (ROOT/'experiments/chaos_local/prepared', 'local_logistic_unit',
                       '-GUSE_KS=1 -GKS_IMPL=9 -GKS_GEOM=0 -GLBE_T=64 -GLBE_LEAN=6 -GLBE_PERT=8'),
    'tent_stride4': (ROOT/'experiments/quality/nardo2023/strided/prepared',
                     'tent_unit', '-GUSE_KS=1 -GKS_IMPL=10 -GKS_GEOM=0'),
}
REFS = {
    'xs64': ROOT/'experiments/xs64_baseline/run_unit.py',
    'local_logistic': ROOT/'experiments/chaos_local/local_logistic_ref.py',
    'tent_stride4': ROOT/'experiments/quality/nardo2023/strided/tent_ref.py',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_inputs(inputs):
    inputs = Path(inputs).resolve()
    firmware = load('source_firmware_builder', ROOT/'scripts/build_firmware.py')
    if not all((inputs/name).is_file() for name in firmware.EXPECTED_SHA256):
        firmware.build(inputs, inputs.parent/'firmware')
    if not (inputs/'img120.txt').is_file():
        image = load('source_image_builder', ROOT/'scripts/generate_inputs.py')
        image.generate(inputs)
    return inputs


def prepare(variant, work=None, inputs=None, build_inputs=True):
    if variant not in VARIANTS:
        raise ValueError(variant)
    work = Path(work or ROOT/'build/full_system'/variant).resolve()
    inputs = Path(inputs or ROOT/'build/inputs').resolve()
    origin, module, flags = VARIANTS[variant]
    for folder in ('rtl', 'sim', 'results'):
        (work/folder).mkdir(parents=True, exist_ok=True)
    for path in sorted((origin/'rtl').iterdir()):
        if path.suffix in ('.v', '.vh'):
            shutil.copy2(path, work/'rtl'/path.name)
    if variant == 'staged':
        shutil.copy2(ROOT/'experiments/chaos_local/normalizer_staged/rtl/lbe_ext.vh',
                     work/'rtl/lbe_ext.vh')
    shutil.copy2(SRC/'sim/tb.cpp', work/'sim/tb.cpp')
    script = (SRC/'sim/build.sh').read_text()
    if flags:
        lines = script.splitlines()
        found = 0
        for index, line in enumerate(lines):
            if line.strip().startswith('plane)'):
                lines[index] = f'  plane) G="{flags}";;'
                found += 1
            elif line.startswith('SRC='):
                lines[index] = line.replace(' picorv32"', f' {module} picorv32"')
        if found != 1:
            raise RuntimeError('Unexpected base simulator build script')
        script = '\n'.join(lines) + '\n'
    (work/'sim/build.sh').write_text(script)
    (work/'sim/build.sh').chmod(0o755)
    if build_inputs:
        ensure_inputs(inputs)
    return work, inputs


def run(variant, n=3, ext=0, work=None, inputs=None, skip_build=False, keep_traces=False):
    import numpy as np
    work, inputs = prepare(variant, work, inputs)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', LBE_EXT=str(ext))
    verilator = env.get('VERILATOR', 'verilator')
    if not shutil.which(verilator):
        raise SystemExit('Verilator not found. Set VERILATOR or add verilator to PATH.')
    mode = variant if variant in ('plane', 'trivium', 'chacha', 'none') else 'plane'
    build_command = ['bash', 'sim/build.sh', str(n), mode, '_'+variant]
    if not skip_build:
        built = subprocess.run(build_command, cwd=work, capture_output=True, text=True,
                               check=True, env=env)
        (work/'results/build_stdout.log').write_text(built.stdout+built.stderr)
    binary = work/f'sim/obj_{mode}_{variant}_N{n}/Vmpriscv'
    if not binary.is_file():
        raise SystemExit(f'Simulator is missing: {binary}')
    public = load('full_mesh_public_configuration', SRC/'reference/chacha.py')
    golden = load('full_mesh_image_reference', SRC/'reference/golden.py')
    words = list(struct.unpack('<11I', public.TEST_KEY+public.frame_nonce(1, 0)))
    image = inputs/'img120.txt'
    img = np.loadtxt(image, dtype=np.int64).reshape(120, 120)
    if variant in ('staged', 'plane'):
        sys.path.insert(0, str(SRC/'tools'))
        plane = load('full_mesh_plane_reference', SRC/'tools/plane_ref.py')
        stream_image = plane.encrypt_image(np.zeros_like(img), public.TEST_KEY,
                                          public.frame_nonce(1, 0), n, ext,
                                          T=64, lean=6, pert=8)
    elif variant == 'chacha':
        stream_image = np.asarray([list(row) for row in public.keystream_image(public.TEST_KEY,
                                  public.frame_nonce(1, 0), 120, 120, 20, 1)], dtype=np.int64)
    elif variant == 'trivium':
        baseline = load('full_mesh_trivium_reference',
                        SRC/'baseline/reference_original/tile_streams.py')
        stream_image = baseline.keystream_image('triv', public.TEST_KEY,
                        public.frame_nonce(1, 0), 120, 120, n).astype(np.int64)
    elif variant == 'none':
        stream_image = np.zeros_like(img)
    else:
        ref = load('full_mesh_native_reference_'+variant, REFS[variant])
        stream_image = np.zeros_like(img)
        for ty in range(n):
            y0, y1 = ty*120//n, (ty+1)*120//n
            for tx in range(n):
                x0, x1 = tx*120//n, (tx+1)*120//n
                values = list(ref.stream(words, ty*n+tx, (y1-y0)*(x1-x0)))
                stream_image[y0:y1, x0:x1] = np.asarray(values).reshape(y1-y0, x1-x0)
    pipeline, _ = golden.pipeline(img, n)
    expected = load('full_mesh_expected_firmware_hashes', ROOT/'scripts/build_firmware.py')
    records = []
    out = work/'results'
    workloads = [('tree', 'sobel_ppu_tree_O2.hex')] if variant == 'none' else [
                  ('crypt', 'crypt_ppu_O2.hex'), ('fused', 'sobel_ppu_fused_O2.hex')]
    for kind, firmware in workloads:
        hexfile = inputs/firmware
        command = [str(binary), str(n), '120', '120', str(hexfile), str(image), kind]
        sim = subprocess.run(command, cwd=out, capture_output=True, text=True,
                             check=True, env=env, timeout=300)
        (out/(kind+'.log')).write_text(sim.stdout+sim.stderr)
        timing = json.loads((out/(kind+'_timing.json')).read_text())
        trace = out/(kind+'_steps.txt')
        hw = np.loadtxt(trace, dtype=np.int64).reshape(8, 120, 120)
        if kind == 'crypt':
            errors = {'cipher': int(np.count_nonzero(hw[1] != (img ^ stream_image))),
                      'decrypt': int(np.count_nonzero(hw[2] != img))}
            comparisons = 28800
        elif kind == 'fused':
            errors = {'pipeline_steps_1_to_6': sum(int(np.count_nonzero(hw[step] !=
                      ((pipeline[step]+32768) % 65536-32768))) for step in range(1, 7)),
                      'ciphertext': int(np.count_nonzero(hw[7] != (pipeline[7] ^ stream_image)))}
            comparisons = 100800
        else:
            errors = {'pipeline_steps_1_to_7': sum(int(np.count_nonzero(hw[step] !=
                      ((pipeline[step]+32768) % 65536-32768))) for step in range(1, 8))}
            comparisons = 100800
        if not timing['readback_ok'] or any(errors.values()):
            raise RuntimeError(f'{variant}/{kind}: failed readback or golden check: {errors}')
        record = {'workload': kind, 'command': command, 'timing': timing,
                  'golden_mismatches': errors, 'golden_compared_values': comparisons,
                  'firmware_sha256': sha(hexfile), 'image_sha256': sha(image),
                  'matches_expected_firmware': sha(hexfile) == expected.EXPECTED_SHA256[firmware],
                  'output_sha256': sha(trace)}
        records.append(record)
        print(json.dumps({'variant': variant, 'N': n, 'workload': kind,
                          'run_cycles': timing['t_run'], 'mismatches': errors}), flush=True)
        if not keep_traces:
            trace.unlink()
    payload = {'status': 'passed', 'variant': variant, 'N': n, 'extractor': ext,
               'configuration_words': words, 'build_command': build_command,
               'verilator_version': subprocess.run([verilator, '--version'], check=True,
                                    capture_output=True, text=True).stdout.strip(),
               'rtl_sha256': {p.name: sha(p) for p in sorted((work/'rtl').iterdir())},
               'results': records,
               'cycle_reproduction_note': 'Firmware rebuilt with compilers other than GCC 13.4 may differ '
                                          'from the expected images. Exact cycle counts are only '
                                          'comparable when firmware hashes match.'}
    (out/'full_system_result.json').write_text(json.dumps(payload, indent=2)+'\n')
    return payload


def add_arguments(parser):
    parser.add_argument('--work-dir', type=Path, help='Generated simulator/results directory')
    parser.add_argument('--inputs-dir', type=Path, help='Generated image/firmware directory')
    parser.add_argument('--n', type=int, choices=(3, 4, 6), default=3)
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--keep-traces', action='store_true',
                        help='Keep the large readback text traces after successful checks')
