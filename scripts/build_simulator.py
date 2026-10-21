#!/usr/bin/env python3
"""Build a complete-mesh simulator without executing any workload."""
import argparse
import importlib.util
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ("plane", "trivium", "chacha", "none", "staged", "xs64", "local_logistic", "tent_stride4")


def build(variant, n, ext, dry_run):
    work = ROOT / "build/simulators" / f"{variant}_E{ext}_N{n}"
    mode = variant if variant in ("plane", "trivium", "chacha", "none") else "plane"
    command = ["bash", "sim/build.sh", str(n), mode, "_" + variant]
    print(f"{work}: LBE_EXT={ext} " + " ".join(command), flush=True)
    if dry_run:
        return
    path = ROOT / "experiments/full_system/common.py"
    spec = importlib.util.spec_from_file_location("source_full_mesh_builder", path)
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)
    common.prepare(variant, work=work, build_inputs=False)
    subprocess.run(command, cwd=work, check=True,
                   env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", LBE_EXT=str(ext)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=VARIANTS, default="plane")
    parser.add_argument("--n", type=int, choices=(3, 4, 6), default=3)
    parser.add_argument("--ext", type=int, choices=range(4), default=0)
    parser.add_argument("--matrix", action="store_true", help="Build the existing application matrix without running it")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.matrix:
        selected = [("plane", n, ext) for n in (3, 4, 6) for ext in range(4)]
        selected += [(v, n, 0) for n in (3, 4, 6) for v in ("trivium", "chacha", "none")]
        selected += [(v, 3, 0) for v in ("staged", "xs64", "local_logistic", "tent_stride4")]
    else:
        selected = [(args.variant, args.n, args.ext)]
    for variant, n, ext in selected:
        build(variant, n, ext, args.dry_run)


if __name__ == "__main__":
    main()
