#!/usr/bin/env python3
"""Recreate seed/configuration records with no scientific recurrence iteration."""
import argparse
import csv
import json
from pathlib import Path
from bootstrap_sources import directed_words
from seedlib import seed_record, local_initial, plane_initial

ROOT = Path(__file__).resolve().parents[1]
QUALITY_CONFIG = ROOT / "seeds/quality_config.json"
EXPECTED_POSTMIX = (("0301c31e", "36f34d15024e76d8"),
                   ("c3e49959", "8c52e13880111118"),
                   ("7859f197", "449d482302a17c56"),
                   ("a6abdbba", "0565fab6f9dd4947"))


def jsonbytes(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def csvbytes(rows):
    import io
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def all_records(meshes):
    cfg = json.loads(QUALITY_CONFIG.read_text())
    cases = [seed_record(i, pair["key"], pair["nonce"])
             for i, pair in enumerate(cfg["key_nonce_pairs"])]
    assert tuple((v["derived_mix32_hex"], v["derived_mix64_hex"]) for v in cases) == EXPECTED_POSTMIX
    def scoped(scope, index, words):
        raw = b"".join(w.to_bytes(4, "little") for w in words)
        value = seed_record(index, raw[:32].hex(), raw[32:].hex())
        return {"scope": scope, **value}
    quality = [{"scope": "quality", **v} for v in cases]
    words = directed_words()
    restart = [scoped("directed_restart", i, words[i*11:(i+1)*11]) for i in range(2)]
    application = scoped("complete_mesh_application", 0,
        [int.from_bytes(bytes(range(i, i+4)), "little") for i in range(0,32,4)] + [0,1,0])
    local=[]; plane=[]
    for case in quality + restart + [application]:
        a=int(case["derived_mix32_hex"],16); b=int(case["derived_mix64_hex"],16)
        x0,s0=plane_initial(a,b)
        for n in meshes:
            for y in range(n):
                for x in range(n):
                    local.append({"scope":case["scope"], "case":case["index"], "N":n,
                        "y":y,"x":x,"t":y*n+x+1,**local_initial(a,b,y*n+x+1)})
            for axis in ("row","column"):
                for coordinate in range(n):
                    v=2*coordinate+(axis=="column")
                    plane.append({"scope":case["scope"],"case":case["index"],"N":n,
                        "axis":axis,"coordinate":coordinate,"variant":v,"expression":v%6,"guard_bits":v//6,
                        "x0_hex":f"{x0:08x}","s0_hex":f"{s0:016x}"})
    uniform={"numpy_version":"1.21.5","bit_generator":"PCG64","rng_seed":20271014,
        "factory":"numpy.random.default_rng(20271014)","case_order":[0,1,2,3],
        "calls_per_case":1,"call":"rng.integers(0, 256, (6, 6, 125000), dtype=numpy.uint8)",
        "reseed_between_cases":False,"other_draws":False,"array_order":"C", "index_order":"B[y,x,time]",
        "training_slice":"0:62500","test_slice":"62500:125000","bytes_generated_by_this_script":False}
    return {"postmix_cases.csv":csvbytes(quality),"local_initial_states.csv":csvbytes(local),
        "plane_sources.csv":csvbytes(plane),
        "directed_restart_and_application.json":jsonbytes({"restart_cases":restart,"application":application,
            "delivery_case":"directed_restart case 0","configuration_word_order":"eight key then three nonce uint32 little endian"}),
        "uniform_protocol.json":jsonbytes(uniform)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir",type=Path,default=ROOT/"build/seed_records")
    parser.add_argument("--meshes",nargs="+",type=int,default=[3,4,6,8])
    parser.add_argument("--check",action="store_true",help="Check included deterministic records without writing")
    parser.add_argument("--check-numpy",action="store_true",help="Regenerate only the 176 configuration bytes, never Uniform or orbit bytes")
    args=parser.parse_args()
    assert args.meshes and all(n>0 for n in args.meshes)
    files=all_records(args.meshes)
    if args.check:
        out=ROOT/"seeds"
        for relative,content in files.items():
            assert (out/relative).read_bytes()==content, relative
    else:
        out=args.out_dir
        if out.exists() and any(out.iterdir()):
            raise SystemExit(f"Use a new empty output directory to preserve earlier records: {out}")
        out.mkdir(parents=True,exist_ok=True)
        for relative,content in files.items():
            dest=out/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(content)
    if args.check_numpy:
        from bootstrap_sources import quality_configuration
        assert quality_configuration()==json.loads(QUALITY_CONFIG.read_text())
    print(json.dumps({"status":"PASS","records":len(files),"meshes":args.meshes,
        "scientific_streams_generated":False,"numpy_key_recipe_checked":args.check_numpy,
        "destination":str(out)},indent=2))

if __name__=="__main__": main()
