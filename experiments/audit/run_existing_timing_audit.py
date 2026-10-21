#!/usr/bin/env python3
"""Plan the routed-checkpoint timing audit; --execute runs it."""
import argparse
import csv
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
SOURCE = PROJECT / "experiments/chaos_local/normalizer_staged/fpga"
VIVADO = os.environ.get("VIVADO", "vivado")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Run the audit against rebuilt checkpoints")
    parser.add_argument("--sizes", type=int, nargs="+", choices=(3, 4, 6), default=[3, 4, 6])
    args = parser.parse_args()
    plans = []
    for n in args.sizes:
        tag = f"plane_A_staged_N{n}_70"
        checkpoint = SOURCE / f"ooc_{tag}/routed_{tag}.dcp"
        if args.execute:
            assert checkpoint.is_file(), f"Rebuild original Shared A* route first: {checkpoint}"
        output = HERE / f"timing_audit/N{n}"
        plans.append({"N": n, "checkpoint": str(checkpoint), "checkpoint_sha256": sha(checkpoint) if checkpoint.is_file() else None,
                      "output": str(output), "command": [VIVADO, "-mode", "batch", "-nojournal", "-nolog", "-source",
                                                        str(HERE/"existing_timing_audit.tcl"), "-tclargs", str(checkpoint), str(output)]})
    if not args.execute:
        print(json.dumps({"status": "PLANNED_NOT_EXECUTED", "plans": plans}, indent=2))
        return
    for row in plans:
        output = Path(row["output"])
        assert not output.exists(), f"Refusing to replace an earlier audit: {output}"
        output.mkdir(parents=True)
        began = time.monotonic()
        with (output / "vivado.log").open("w") as stream:
            result = subprocess.run(row["command"], cwd=output, stdout=stream, stderr=subprocess.STDOUT)
        row.update(returncode=result.returncode, elapsed_seconds=round(time.monotonic()-began, 2))
        assert sha(Path(row["checkpoint"])) == row["checkpoint_sha256"]
        row["checkpoint_unchanged"] = True
        if result.returncode:
            row["status"] = "TOOL_ERROR"
        else:
            with (output/"register_coverage.tsv").open() as stream:
                registers = list(csv.DictReader(stream, delimiter="\t"))
            required = {"recurrence", "receivers", "readiness_state", "initialization_state", "advance_register", "initialization_register"}
            row["register_classes"] = {name: sum(r["class"] == name for r in registers) for name in sorted(required)}
            row["endpoint_review_needed"] = [r for r in registers if not r["clock_names"] or r["setup_path_present"] != "1"]
            row["status"] = "AWAITING_INTERNAL_VS_EXTERNAL_TIMING_REVIEW"
            row["all_register_classes_found"] = set(row["register_classes"]) == required and all(row["register_classes"].values())
        (output/"audit_execution.json").write_text(json.dumps(row, indent=2) + "\n")
        print(json.dumps(row, indent=2), flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
