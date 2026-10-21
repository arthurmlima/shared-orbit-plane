#!/usr/bin/env python3
"""Plan the N=6 Private A* common-flow implementation; explicit execution only."""
import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREPARED = HERE/"private_astar/prepared"
VIVADO = os.environ.get("VIVADO", "vivado")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute",action="store_true",help="Route after the functional checks pass")
    args = parser.parse_args()
    manifest = json.loads((HERE/"private_astar/source_manifest.json").read_text())
    for name,expected in manifest["source_hashes_prepared"].items():
        assert sha(PREPARED/name)==expected,name
    job = json.loads((PREPARED/"fpga/private_job.json").read_text())["jobs"][0]
    outroot = PREPARED/"fpga"
    work = outroot/"work"/job["tag"]
    command = [VIVADO,"-mode","batch","-nojournal","-nolog","-source",str(outroot/"impl_ooc.tcl"),
               "-tclargs",job["tag"],str(job["freq"]),job["generics"],job["top"],str(outroot)]
    record = {"status":"PLANNED_NOT_EXECUTED","job":job,"command":command,
              "flow_sha256":sha(outroot/"impl_ooc.tcl"),"source_manifest_sha256":sha(HERE/"private_astar/source_manifest.json")}
    if not args.execute:
        print(json.dumps(record,indent=2));return
    functional = json.loads((HERE/"private_astar/functional/result.json").read_text())
    assert functional["status"]=="PASS"
    assert functional["source_manifest_sha256"]==record["source_manifest_sha256"]
    assert not work.exists(),"Do not replace a prior implementation run"
    work.mkdir(parents=True)
    record["status"]="RUNNING"
    (work/"command.json").write_text(json.dumps(record,indent=2)+"\n")
    began=time.monotonic()
    with (work/"vivado.log").open("w") as stream:
        process=subprocess.run(command,cwd=work,stdout=stream,stderr=subprocess.STDOUT)
    record.update(returncode=process.returncode,elapsed_seconds=round(time.monotonic()-began,2))
    final=outroot/("ooc_"+job["tag"])/("fmax_"+job["tag"]+".txt")
    record["status"]="COMPLETE_AWAITING_HIERARCHY_AND_TIMING_REVIEW" if process.returncode==0 and final.is_file() else "FAILED"
    if final.is_file():record["flow_final_record"]=final.read_text().strip()
    (work/"result.json").write_text(json.dumps(record,indent=2)+"\n")
    print(json.dumps(record,indent=2))
    if process.returncode:raise SystemExit(process.returncode)


if __name__=="__main__":
    main()
