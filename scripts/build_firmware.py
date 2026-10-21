#!/usr/bin/env python3
"""Build the three RV32IM firmware inputs from the supplied C/assembly sources.

Outputs are generated locally; no prebuilt firmware is distributed. The crypt
image links mpriscv_halo.c, a variant of mpriscv.c with the halo-only PPU helper.
Different GCC releases can change instruction counts and workload cycles even
when functional golden checks continue to pass.
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/sw'
EXPECTED_SHA256 = {
    'crypt_ppu_O2.hex': '6a231712a27d7f9f834dacacb5194caaceefae6bc781c7cd86d2be95e7cefb9f',
    'sobel_ppu_tree_O2.hex': 'a1d812bfb5cf3376eeaa5a88542598ba0161d4cb2b434d0b0b9c2bb0953e0c12',
    'sobel_ppu_fused_O2.hex': 'a18f963f6a65c2edeb8ff5db17e4742651d01f6ec456be82892d570e5afba2be',
}
RECIPES = (
    ('crypt_ppu', '_O2', []),
    ('sobel_ppu', '_tree_O2', ['-DTREE_REDUCE']),
    ('sobel_ppu', '_fused_O2', ['-DTREE_REDUCE', '-DFUSED_ENCRYPT', '-DKS_EARLY']),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_tools(cc=None, objcopy=None):
    prefix = os.environ.get('CROSS_COMPILE', os.environ.get('RISCV_PREFIX', ''))
    cc = cc or os.environ.get('RISCV_CC') or (prefix + 'gcc' if prefix else None)
    if not cc:
        cc = next((tool for tool in ('riscv64-unknown-elf-gcc', 'riscv32-unknown-elf-gcc',
                                    'riscv32-xilinx-elf-gcc') if shutil.which(tool)), None)
    if not cc or not shutil.which(cc):
        raise SystemExit('RISC-V bare-metal GCC not found. Set RISCV_CC and RISCV_OBJCOPY, '
                         'or pass --cc and --objcopy. GCC must support -march=rv32im -mabi=ilp32.')
    objcopy = objcopy or os.environ.get('RISCV_OBJCOPY')
    if not objcopy:
        objcopy = cc[:-3] + 'objcopy' if cc.endswith('gcc') else prefix + 'objcopy'
    if not shutil.which(objcopy):
        raise SystemExit('Matching RISC-V objcopy not found; set RISCV_OBJCOPY or pass --objcopy.')
    return shutil.which(cc), shutil.which(objcopy)


def build(out, work, cc=None, objcopy=None):
    out, work = Path(out).resolve(), Path(work).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    cc, objcopy = find_tools(cc, objcopy)
    version = subprocess.run([cc, '--version'], check=True, capture_output=True,
                             text=True).stdout.splitlines()[0]
    records = []
    for app, suffix, defines in RECIPES:
        stem = app + suffix
        library = 'mpriscv_halo.c' if app == 'crypt_ppu' else 'mpriscv.c'
        elf, binary, hexfile = work/(stem+'.elf'), work/(stem+'.bin'), out/(stem+'.hex')
        command = [cc, '-march=rv32im', '-mabi=ilp32', '-O2', '-ffreestanding',
                   '-nostdlib', '-nostartfiles', '-Wall', '-DSTACK_TOP=8192', *defines,
                   '-Wl,--build-id=none',
                   '-T', str(SOURCE/'link.ld'), '-o', str(elf), str(SOURCE/'crt0.S'),
                   str(SOURCE/library), str(SOURCE/(app+'.c')), '-lgcc']
        subprocess.run(command, check=True)
        subprocess.run([objcopy, '-O', 'binary', str(elf), str(binary)], check=True)
        raw = binary.read_bytes()
        raw += b'\0' * (-len(raw) % 4)
        if len(raw) > 8192:
            raise SystemExit(f'{stem}: firmware exceeds the configured 8192-byte tile RAM')
        hexfile.write_text('\n'.join(f'{word:08x}' for word in
                           struct.unpack('<%dI' % (len(raw)//4), raw)) + '\n')
        digest = sha(hexfile)
        records.append({'firmware': hexfile.name, 'words': len(raw)//4, 'sha256': digest,
                        'expected_sha256': EXPECTED_SHA256[hexfile.name],
                        'matches_expected_firmware': digest == EXPECTED_SHA256[hexfile.name],
                        'command': command})
        print(f'{hexfile.name}: {len(raw)//4} words; expected byte match: '
              f'{records[-1]["matches_expected_firmware"]}', flush=True)
    record = {'compiler': version, 'compiler_path': cc, 'objcopy_path': objcopy,
              'source_sha256': {p.name: sha(p) for p in sorted(SOURCE.iterdir())
                                if p.suffix in ('.c', '.h', '.S', '.ld')},
              'outputs': records,
              'linker_portability_note': 'Disable linker build-id notes so reset address 0 contains '
                                         'the startup instructions on toolchains that enable build IDs by default.',
              'crypt_library': 'crypt_ppu links mpriscv_halo.c, which uses the halo-only PPU helper.',
              'cycle_reproduction_note': 'Exact cycle counts require identical firmware. '
                                         'GCC13.4.0 reproduces all three firmware images; other versions '
                                         'are checked against the expected SHA256 hashes.'}
    (work/'firmware_manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'build/inputs')
    parser.add_argument('--work-dir', type=Path, default=ROOT/'build/firmware')
    parser.add_argument('--cc')
    parser.add_argument('--objcopy')
    args = parser.parse_args()
    build(args.out, args.work_dir, args.cc, args.objcopy)


if __name__ == '__main__':
    main()
