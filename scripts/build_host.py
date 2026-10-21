#!/usr/bin/env python3
"""Compile host analysis helpers without running them or producing results."""
import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def commands(out):
    cxx, cc = os.environ.get("CXX", "g++"), os.environ.get("CC", "gcc")
    pairs = (
        ("src/quality/heldout/predict.cpp", "heldout_predict.so"),
        ("experiments/quality/predict.cpp", "quality_predict.so"),
        ("experiments/quality/generate_fast.cpp", "quality_generate.so"),
        ("experiments/quality/arbiter_consumer/generate_fast.cpp", "arbiter_generate.so"),
    )
    result = [[cxx, "-O3", "-shared", "-fPIC", str(ROOT/source), "-o", str(out/target)]
              for source, target in pairs]
    result.append([cc, "-O2", str(ROOT/"src/quality/lbe_period.c"),
                   "-o", str(out/"lbe_period")])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT/"build/host")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run:
        args.out.mkdir(parents=True, exist_ok=True)
    for command in commands(args.out):
        print("+ " + " ".join(command), flush=True)
        if not args.dry_run:
            subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
