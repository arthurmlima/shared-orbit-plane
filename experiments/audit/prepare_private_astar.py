#!/usr/bin/env python3
"""Prepare isolated Private A* sources; never run checks or implementation."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
ORIGINAL = PROJECT / "experiments/chaos_local/normalizer_staged"
TARGET = HERE / "private_astar/prepared"


def sha(value):
    return hashlib.sha256(value).hexdigest()


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def main():
    # Prepared RTL is versioned; generated JSON job recipes are recreated here.
    sources = {str(p.relative_to(ORIGINAL)): p.read_bytes()
               for p in (ORIGINAL / "rtl").iterdir() if p.suffix in (".v", ".vh")}
    sources["fpga/impl_ooc.tcl"] = (ORIGINAL / "fpga/impl_ooc.tcl").read_bytes()
    before = {name: sha(value) for name, value in sources.items()}
    mesh = sources["rtl/mpriscv.v"].decode()
    mesh = replace_once(mesh, "    parameter ORB_MID = 0,", "    parameter ORB_PRIVATE = 0,              // collective-advance byte-identical private source copies\n    parameter ORB_MID = 0,")
    mesh = replace_once(mesh,
                        ".ORB_ROW_SRC(x == ROW_SRC_X), .ORB_COL_SRC(y == COL_SRC_Y),",
                        ".ORB_ROW_SRC(ORB_PRIVATE || x == ROW_SRC_X), .ORB_COL_SRC(ORB_PRIVATE || y == COL_SRC_Y),")
    mesh = replace_once(mesh, ".orb_row_in(orb_row_src[y * N + ROW_SRC_X]),",
                        ".orb_row_in(ORB_PRIVATE ? orb_row_src[T] : orb_row_src[y * N + ROW_SRC_X]),")
    mesh = replace_once(mesh, ".orb_col_in(orb_col_src[COL_SRC_Y * N + x]),",
                        ".orb_col_in(ORB_PRIVATE ? orb_col_src[T] : orb_col_src[COL_SRC_Y * N + x]),")
    sources["rtl/mpriscv.v"] = mesh.encode()
    axi = sources["rtl/mpriscv_axi.v"].decode()
    axi = replace_once(axi, "    parameter LBE_EXT = 0,", "    parameter ORB_PRIVATE = 0,            // retains the mesh's collective advance\n    parameter LBE_EXT = 0,")
    axi = replace_once(axi, ".ORB_MID(ORB_MID), .LBE_EXT(LBE_EXT)) u_mesh (",
                       ".ORB_MID(ORB_MID), .ORB_PRIVATE(ORB_PRIVATE), .LBE_EXT(LBE_EXT)) u_mesh (")
    sources["rtl/mpriscv_axi.v"] = axi.encode()
    for name, value in sources.items():
        path = TARGET / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            assert path.read_bytes() == value, f"Prepared source differs from deterministic recipe: {path}"
        else:
            path.write_bytes(value)
    changed = [name for name in sources if sha(sources[name]) != before[name]]
    assert set(changed) == {"rtl/mpriscv.v", "rtl/mpriscv_axi.v"}
    assert sources["rtl/lbe_dist.v"] == (ORIGINAL / "rtl/lbe_dist.v").read_bytes()
    assert sources["rtl/lbe_ext.vh"] == (ORIGINAL / "rtl/lbe_ext.vh").read_bytes()
    report = {"status": "PREPARED_NOT_EXECUTED", "origin": str(ORIGINAL),
              "source_hashes_before": before,
              "source_hashes_prepared": {name: sha(value) for name, value in sources.items()},
              "changed_files": changed, "private_policy": "Two coordinate-specific sources per tile, local receiver inputs, unchanged collective initialization/advance.",
              "flow_byte_identical": True, "normalizer_and_generator_byte_identical": True,
              "no_preservation_attributes_added": True,
              "simulation_synthesis_implementation_runs": 0}
    (HERE / "private_astar/source_manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    existing = json.loads((ORIGINAL / "fpga/jobs/mesh.json").read_text())["jobs"]
    n6 = next(value for value in existing if value["tag"] == "plane_A_staged_N6_70")
    private = dict(n6, tag="private_A_staged_N6_70", generics=n6["generics"] + " ORB_PRIVATE=1")
    (TARGET / "fpga/private_job.json").write_text(json.dumps({"jobs": [private]}, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "prepared": str(TARGET), "changed_files": changed}, indent=2))


if __name__ == "__main__":
    main()
