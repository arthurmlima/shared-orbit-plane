#!/usr/bin/env python3
"""Plan Private A* functional validation; --execute runs it."""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
PREPARED = HERE / "private_astar/prepared"
FUNCTIONAL = HERE / "private_astar/functional"
ORIGINAL = PROJECT / "src"
PORTABLE = ORIGINAL
IVERILOG = os.environ.get("IVERILOG", "iverilog")
VVP = os.environ.get("VVP", "vvp")
VERILATOR = os.environ.get("VERILATOR", "verilator")
INPUTS = PROJECT / "build/inputs"
EXPECTED_INPUT_HASHES = {
    "img120.txt": "442b34f1fc5a89a5aac39012eb6971bdcf14b8fe1f0b7e326af6a46f764f2661",
    "crypt_ppu_O2.hex": "6a231712a27d7f9f834dacacb5194caaceefae6bc781c7cd86d2be95e7cefb9f",
    "sobel_ppu_fused_O2.hex": "a18f963f6a65c2edeb8ff5db17e4742651d01f6ec456be82892d570e5afba2be",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(command, cwd, log, env=None, timeout=None):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=cwd, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, env=env, timeout=timeout)


def verify_sources():
    manifest = json.loads((HERE / "private_astar/source_manifest.json").read_text())
    for name, expected in manifest["source_hashes_prepared"].items():
        assert sha(PREPARED/name) == expected, name
    return manifest


def prepare_application(name, private):
    work = FUNCTIONAL / name
    for folder in ("rtl", "sim", "results"):
        (work/folder).mkdir(parents=True)
    for source in (PREPARED/"rtl").iterdir():
        shutil.copy2(source, work/"rtl"/source.name)
    mesh = (work/"rtl/mpriscv.v").read_text()
    marker = ".orb_all_armed(orb_all_armed), .orb_go(orb_go));"
    assert mesh.count(marker) == 1
    monitor = marker + "\n`ifdef ACCEPTED_BYTE_CHECK\n            if (USE_KS == 1 && KS_IMPL == 5) begin : g_accepted_byte_monitor\n                `include \"accepted_byte_monitor.vh\"\n            end\n`endif"
    (work/"rtl/mpriscv.v").write_text(mesh.replace(marker, monitor))
    shutil.copy2(HERE/"accepted_byte_monitor.vh", work/"rtl/accepted_byte_monitor.vh")
    shutil.copy2(PORTABLE/"sim/tb.cpp", work/"sim/tb.cpp")
    script = (PORTABLE/"sim/build.sh").read_text()
    assert script.count("+define+PROFILE") == 1
    script = script.replace("+define+PROFILE", "+define+PROFILE +define+ACCEPTED_BYTE_CHECK")
    marker = '-GLBE_EXT=${LBE_EXT:-0}'
    assert script.count(marker) == 1
    script = script.replace(marker, marker + " -GORB_PRIVATE=${ORB_PRIVATE:-0}")
    (work/"sim/build.sh").write_text(script)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", VERILATOR=VERILATOR,
               LBE_EXT="0", ORB_PRIVATE=str(private), JOBS="2")
    run(["bash", "sim/build.sh", "3", "plane", "_"+name], work, work/"build.log", env)
    return work, work/f"sim/obj_plane_{name}_N3/Vmpriscv", env


def byte_records(directory, expected, expected_passes):
    result = {}
    for tile in range(9):
        path = directory/f"tile_{tile}.accepted.tsv"
        passes = {}
        for line in path.read_text().splitlines():
            fields = line.split("\t")
            if fields[0] == "START":
                passes[int(fields[1])] = []
            elif fields[0] == "BYTE":
                pass_id, index, cycle = map(int, fields[1:4])
                value = int(fields[4], 16)
                assert pass_id in passes and index == len(passes[pass_id]), (tile, fields)
                assert index < expected.shape[-1], (tile, pass_id, index)
                reference = int(expected[tile//3, tile%3, index])
                assert value == reference, (tile, pass_id, index, value, reference)
                passes[pass_id].append((cycle, value))
            else:
                raise AssertionError((path, fields))
        assert set(passes) == set(range(1, expected_passes+1)), (tile, passes.keys())
        # N=3 partitions the 120x120 raster into 40x40 tiles.  Both XORKS
        # passes and the fused pointwise threshold consume once per pixel.
        assert all(len(values) == 1600 for values in passes.values()), (
            tile, {p: len(values) for p, values in passes.items()},
            "Each configured pass must consume the complete 40x40 tile")
        result[tile] = passes
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Run the functional checks")
    args = parser.parse_args()
    manifest = verify_sources()
    plan = {"N_application": 3, "generator_stall_restart_sizes": [3, 6], "extractor": "A*",
            "private_advance": "collective", "workloads": ["crypt", "fused"],
            "accepted_byte_check": "Every take && hit compared with its tile/pass software-reference prefix and with shared A*.",
            "crypt_first_xor_interval": "max(mark 2) - max(mark 1)",
            "crypt_table_interval": "Second XOR pass after restart: max(mark 3) - max(mark 2)",
            "fused_table_interval": "t_run: processor reset release (cpu_resetn asserted) to all_done",
            "input_directory": str(INPUTS), "new_route_executed_by_this_runner": False}
    if not args.execute:
        print(json.dumps({"status": "PLANNED_NOT_EXECUTED", **plan}, indent=2))
        return
    for name, expected_hash in EXPECTED_INPUT_HASHES.items():
        assert sha(INPUTS/name) == expected_hash, (name, "Input identity changed")
    assert not FUNCTIONAL.exists(), "Do not overwrite a previous validation run"
    FUNCTIONAL.mkdir(parents=True)
    began = time.monotonic()
    result = {"status": "RUNNING", "plan": plan, "source_manifest_sha256": sha(HERE/"private_astar/source_manifest.json")}
    (FUNCTIONAL/"result.json").write_text(json.dumps(result, indent=2)+"\n")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    unit = FUNCTIONAL/"stall_restart"
    unit.mkdir()
    shutil.copy2(ORIGINAL/"sim/equiv/tb_equiv.v", unit/"tb_equiv.v")
    shutil.copy2(ORIGINAL/"sim/equiv/keys.mem", unit/"keys.mem")
    checks = []
    for n in (3, 6):
        expected_file = unit/f"expected_N{n}.mem"
        run([sys.executable, ORIGINAL/"tools/plane_ref.py", "expected", n, expected_file, unit/"keys.mem", 0],
            unit, unit/f"reference_N{n}.log", env)
        command = [IVERILOG, "-g2012", "-I"+str(PREPARED/"rtl"), "-s", "tb_equiv",
                   "-P", f"tb_equiv.N={n}", "-P", "tb_equiv.EXT=0", "-P", "tb_equiv.MODE=3",
                   "-o", unit/f"check_N{n}.vvp", PREPARED/"rtl/lbe_dist.v", PREPARED/"rtl/matched_tile.v",
                   PREPARED/"rtl/plane_mesh.v", unit/"tb_equiv.v"]
        run(command, unit, unit/f"compile_N{n}.log", env)
        run([VVP, unit/f"check_N{n}.vvp", "+EXPECTED="+str(expected_file)], unit, unit/f"run_N{n}.log", env)
        text = (unit/f"run_N{n}.log").read_text()
        assert f"PASS N={n} EXT=0" in text and "mismatches=0" in text
        checks.append({"N": n, "log": str(unit/f"run_N{n}.log"), "log_sha256": sha(unit/f"run_N{n}.log")})
    import numpy as np
    plane = load("private_astar_plane_reference", ORIGINAL/"tools/plane_ref.py")
    public = load("private_astar_public_configuration", PORTABLE/"reference/chacha.py")
    golden = load("private_astar_image_reference", PORTABLE/"reference/golden.py")
    expected = plane.tile_streams(public.TEST_KEY, public.frame_nonce(1, 0), 3, 1600, 0, 64, 6, 8)
    image = np.loadtxt(INPUTS/"img120.txt", dtype=np.int64).reshape(120,120)
    stream_image = plane.keystream_image(public.TEST_KEY, public.frame_nonce(1,0),120,120,3,0,64,6,8)
    pipeline, _ = golden.pipeline(image,3)
    records = {}
    accepted = {}
    readbacks = {}
    for name, private in (("shared",0),("private",1)):
        work, binary, app_env = prepare_application(name, private)
        records[name] = []
        for kind, firmware, pass_count in (("crypt","crypt_ppu_O2.hex",2),("fused","sobel_ppu_fused_O2.hex",1)):
            output = work/"results"/kind
            (output/"bytes").mkdir(parents=True)
            command = [binary,"3","120","120",INPUTS/firmware,INPUTS/"img120.txt",kind,
                       "+BYTE_TRACE_DIR="+str(output/"bytes")]
            run(command, output, output/"run.log", app_env, timeout=600)
            timing = json.loads((output/(kind+"_timing.json")).read_text())
            assert timing["readback_ok"]
            hw = np.loadtxt(output/(kind+"_steps.txt"),dtype=np.int64).reshape(8,120,120)
            if kind == "crypt":
                mismatches = {"cipher":int(np.count_nonzero(hw[1] != (image^stream_image))),
                              "decrypt":int(np.count_nonzero(hw[2] != image))}
            else:
                mismatches = {"pipeline_steps_1_to_6":sum(int(np.count_nonzero(hw[step] != ((pipeline[step]+32768)%65536-32768))) for step in range(1,7)),
                              "ciphertext":int(np.count_nonzero(hw[7] != (pipeline[7]^stream_image)))}
            assert not any(mismatches.values()), mismatches
            accepted[name,kind] = byte_records(output/"bytes", expected, pass_count)
            readbacks[name,kind] = hw
            records[name].append({"workload":kind,"timing":timing,"golden_mismatches":mismatches,
                                  "firmware_sha256":sha(INPUTS/firmware),"image_sha256":sha(INPUTS/"img120.txt"),
                                  "readback_sha256":sha(output/(kind+"_steps.txt")),
                                  "accepted_counts":{str(tile):{str(p):len(values) for p,values in passes.items()} for tile,passes in accepted[name,kind].items()},
                                  "accepted_byte_sha256":{str(tile):{str(p):hashlib.sha256(bytes(v for _,v in values)).hexdigest() for p,values in passes.items()} for tile,passes in accepted[name,kind].items()}})
            if kind == "crypt":
                markers = {key:max(timing["marks"][key]) for key in ("1","2","3")}
                records[name][-1]["xor_intervals"] = {
                    "first_pass":{"from_marker":"1","to_marker":"2","start_cycle":markers["1"],
                                  "end_cycle":markers["2"],"cycles":markers["2"]-markers["1"]},
                    "second_pass_table_interval":{"from_marker":"2","to_marker":"3","start_cycle":markers["2"],
                                                  "end_cycle":markers["3"],"cycles":markers["3"]-markers["2"]},
                    "aggregation":"Difference between the maximum recorded tile cycles at the two markers"}
            else:
                records[name][-1]["completion_interval"] = {
                    "from_event":"cpu_resetn asserted (processor reset released)","to_event":"all_done",
                    "field":"t_run","cycles":timing["t_run"]}
    comparisons = {}
    for kind in ("crypt","fused"):
        left,right = accepted["shared",kind],accepted["private",kind]
        for tile in left:
            for pass_id in left[tile]:
                assert [v for _,v in left[tile][pass_id]] == [v for _,v in right[tile][pass_id]]
        assert np.array_equal(readbacks["shared",kind],readbacks["private",kind])
        a = next(r["timing"] for r in records["shared"] if r["workload"]==kind)
        b = next(r["timing"] for r in records["private"] if r["workload"]==kind)
        comparisons[kind] = {"accepted_bytes_identical":True,"complete_readback_identical":True,
                             "timing_identical":a==b,"shared_t_run":a["t_run"],"private_t_run":b["t_run"]}
        if kind == "crypt":
            comparisons[kind]["shared_first_xor_interval"] = max(a["marks"]["2"])-max(a["marks"]["1"])
            comparisons[kind]["private_first_xor_interval"] = max(b["marks"]["2"])-max(b["marks"]["1"])
            comparisons[kind]["shared_second_xor_table_interval"] = max(a["marks"]["3"])-max(a["marks"]["2"])
            comparisons[kind]["private_second_xor_table_interval"] = max(b["marks"]["3"])-max(b["marks"]["2"])
            comparisons[kind]["table_endpoint_definition"] = "max(mark 3) - max(mark 2), second XOR pass after restart"
        else:
            comparisons[kind]["table_endpoint_definition"] = "t_run, processor reset release (cpu_resetn asserted) to all_done"
    verify_sources()
    result.update(status="PASS",elapsed_seconds=round(time.monotonic()-began,2),
                  stall_restart=checks,applications=records,comparisons=comparisons,
                  prepared_sources_unchanged=True,route_executed=False)
    (FUNCTIONAL/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
