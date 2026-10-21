#!/usr/bin/env python3
"""Generate local job recipes and deterministic test inputs from source.

The delivery contains no JSON, memory images or datasets. This command creates
the small runtime inputs expected by the unchanged reproduction programs.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "src"
COMMON = "IMG_W=120 IMG_H=120 FAST_CORE=1 PM_BYPASS=1 USE_PPU=2"
PLANE = "USE_KS=1 KS_IMPL=5 KS_GEOM=0 LBE_T=64 LBE_PERT={pert} PLANE_REG=1 ORB_REG=1 LBE_LEAN=6 ORB_MID=3 LBE_EXT={ext}"


def job(tag, generics, top=None, freq=70):
    value = {"tag": tag, "freq": freq, "generics": generics}
    if top is not None:
        value["top"] = top
    return value


def recipes():
    result = {}
    result[f"{BASE}/fpga/jobs/extractors.json"] = {"jobs": [
        job(f"levelA_ext{ext}_300", f"EXT={ext}", "ext_bench", 300)
        for ext in range(4)]}
    result[f"{BASE}/fpga/jobs/e8_levelB.json"] = {"jobs": [
        job(f"levelB_N{n}_ext{ext}_{'private' if private else 'shared'}_70",
            f"N={n} TW={120//n} TH={120//n} MODE=3 PRIVATE={private} EXT={ext} LEAN=6 PERT=8 T=64",
            "plane_mesh")
        for n in (3, 4, 6, 8) for ext in range(4) for private in (0, 1)]}
    full = []
    for n in (3, 4, 6):
        for ext in range(4):
            full.append(job(f"levelC_N{n}_plane_ext{ext}_70",
                            f"N={n} {COMMON} " + PLANE.format(pert=8, ext=ext)))
        full.extend((job(f"levelC_N{n}_base_70", f"N={n} {COMMON} USE_KS=0"),
                     job(f"levelC_N{n}_trivium_70", f"N={n} {COMMON} USE_KS=1 KS_IMPL=6 KS_GEOM=0"),
                     job(f"levelC_N{n}_chacha_70", f"N={n} {COMMON} USE_KS=1 KS_IMPL=3 KS_GEOM=1 KS_ROUNDS=20 KS_QR=4")))
    # Preserve the recorded job order: the N=6 extractor-D job was appended.
    last = next(value for value in full if value["tag"] == "levelC_N6_plane_ext3_70")
    full.remove(last)
    full.append(last)
    result[f"{BASE}/fpga/jobs/e9_levelC.json"] = {"jobs": full}
    ablation = [job(f"levelB_N{n}_ext0_pert0_{'private' if private else 'shared'}_70",
                    f"N={n} TW={120//n} TH={120//n} MODE=3 PRIVATE={private} EXT=0 LEAN=6 PERT=0 T=64",
                    "plane_mesh")
                for n in (3, 4, 6, 8) for private in (0, 1)]
    ablation.append(job("levelC_N4_plane_ext0_pert0_70", f"N=4 {COMMON} " + PLANE.format(pert=0, ext=0)))
    result[f"{BASE}/fpga/jobs/e11_pert0.json"] = {"jobs": ablation}
    for name in ("original", "staged"):
        prefix = f"experiments/chaos_local/normalizer_{name}/fpga/jobs"
        result[f"{prefix}/isolated.json"] = {"jobs": [
            job(f"ext_A_{name}_300", "EXT=0", "ext_bench", 300)]}
        result[f"{prefix}/mesh.json"] = {"jobs": [
            job(f"plane_A_{name}_N{n}_70", f"N={n} {COMMON} " + PLANE.format(pert=8, ext=0), "mpriscv_axi")
            for n in (3, 4, 6)]}
    variants = (
        ("experiments/xs64_baseline/prepared", "xs64", "xs64", 8, ""),
        ("experiments/chaos_local/prepared", "local_logistic", "local_logistic", 9,
         " LBE_T=64 LBE_LEAN=6 LBE_PERT=8"),
        ("experiments/quality/nardo2023/prepared", "tent", "tent", 10, ""),
        ("experiments/quality/nardo2023/strided/prepared", "tent", "tent_stride4", 10, ""),
    )
    for prefix, filename, tag, implementation, extra in variants:
        result[f"{prefix}/fpga/jobs/{filename}.json"] = {"jobs": [
            job(f"{tag}_N{n}_70", f"N={n} {COMMON} USE_KS=1 KS_IMPL={implementation} KS_GEOM=0{extra}", "mpriscv_axi")
            for n in (3, 4, 6)]}
        if implementation != 9:
            result[f"{prefix}/fpga/jobs/controls.json"] = {"jobs": [
                job(f"control_{'trivium' if enabled else 'base'}_N{n}_70",
                    f"N={n} {COMMON} USE_KS={enabled} KS_IMPL=6 KS_GEOM=0", "mpriscv_axi")
                for n in (3, 4, 6) for enabled in (1, 0)]}
    return result


def quality_configuration():
    try:
        import numpy as np
    except ImportError as exc:
        raise SystemExit("Install requirements.txt before preparing the quality protocol.") from exc
    rng = np.random.Generator(np.random.PCG64(20271013))
    pairs = [{"key": rng.bytes(32).hex(), "nonce": rng.bytes(12).hex()} for _ in range(4)]
    return {"N": 6, "T": 64, "L": 125000, "train": 62500,
            "fixed_r_shift": 6, "perturbation_bits": 8,
            "key_rng_seed": 20271013, "control_rng_seed": 20271014,
            "key_nonce_pairs": pairs, "rectangle_count": 225}


def directed_words():
    # Two explicit restart/configuration cases, not generated measurement data.
    first = [int.from_bytes(bytes(range(i, i+4)), "little") for i in range(0, 32, 4)]
    first += [0x09000000, 0x4A000000, 0]
    second = [0xDEADBEEF, 0x12345678, 0xA5A5A5A5, 0x01020304, 0xFFEEDDCC,
              0x99887766, 0x0BADF00D, 0xCAFEBABE, 0x89ABCDEF, 0x10203040, 0x76543210]
    return first + second


def generated_files():
    values = {name: (json.dumps(value, indent=2) + "\n").encode()
              for name, value in recipes().items()}
    values[f"{BASE}/quality/heldout/config.json"] = (
        json.dumps(quality_configuration(), indent=2) + "\n").encode()
    memory = "".join(f"{word:08x}\n" for word in directed_words()).encode()
    for name in (f"{BASE}/sim/equiv/keys.mem", "experiments/xs64_baseline/keys.mem",
                 "experiments/chaos_local/keys.mem", "experiments/quality/nardo2023/keys.mem",
                 "experiments/quality/nardo2023/strided/keys.mem"):
        values[name] = memory
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="Destination root; use a temporary directory to inspect generated inputs")
    parser.add_argument("--check", action="store_true", help="Compare existing runtime inputs without writing")
    args = parser.parse_args()
    outputs = generated_files()
    failures = []
    for name, content in outputs.items():
        path = args.root / name
        if args.check:
            if not path.is_file() or path.read_bytes() != content:
                failures.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    if failures:
        raise SystemExit("Missing or changed generated inputs:\n" + "\n".join(failures))
    print(f"{'Checked' if args.check else 'Generated'} {len(outputs)} local job/configuration/test input files.")


if __name__ == "__main__":
    main()
