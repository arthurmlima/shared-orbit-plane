#!/usr/bin/env python3
"""Sequential full reproduction: core stages, timing audit and Private A*; plan by default."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
AUDIT=ROOT/'experiments/audit'
VIVADO=os.environ.get('VIVADO','vivado')

def plan(through,parallel):
    steps=[]
    def python(label,path,*args):
        steps.append({'stage':label,'command':[sys.executable,str(ROOT/path),*map(str,args)],'cwd':str(ROOT)})
    def tcl(label,script,checkpoint,out,*args):
        steps.append({'stage':label,'command':[VIVADO,'-mode','batch','-nojournal','-nolog','-source',str(AUDIT/script),
                     '-tclargs',str(checkpoint),str(out),*map(str,args)],'cwd':str(ROOT)})
    # The core stages include normalizer_staged/fpga/jobs/mesh.json (N=3/4/6),
    # which provides the Shared A* checkpoints audited below.
    python('core_all','reproduce.py','all','--parallel',parallel)
    python('existing_timing_audit','experiments/audit/run_existing_timing_audit.py','--execute')
    for n in (3,4,6):
        tag=f'plane_A_staged_N{n}_70'
        checkpoint=ROOT/f'experiments/chaos_local/normalizer_staged/fpga/ooc_{tag}/routed_{tag}.dcp'
        # This inspector's middle argument is the starts file, unlike the other
        # Tcl tools. Build its command explicitly to preserve the interface.
        steps.append({'stage':f'sampled_DSP_N{n}',
          'command':[VIVADO,'-mode','batch','-nojournal','-nolog','-source',str(AUDIT/'inspect_sampled_dsp.tcl'),
                     '-tclargs',str(checkpoint),str(AUDIT/f'timing_audit/N{n}/sampled_dsp_starts.txt'),
                     str(AUDIT/f'timing_audit/dsp_sampled_N{n}')],'cwd':str(ROOT)})
    shared_n6=ROOT/'experiments/chaos_local/normalizer_staged/fpga/ooc_plane_A_staged_N6_70/routed_plane_A_staged_N6_70.dcp'
    tcl('constant_DSP_operand_N6','inspect_one_dsp_static.tcl',shared_n6,AUDIT/'timing_audit/dsp_static_N6')
    python('summarize_timing','experiments/audit/summarize_existing_timing_audit.py')
    if through=='private_astar':
        python('prepare_private_metadata','experiments/audit/prepare_private_astar.py')
        python('private_functional','experiments/audit/run_private_functional.py','--execute')
        python('private_route','experiments/audit/run_private_route.py','--execute')
        python('private_postroute_audit','experiments/audit/run_private_postroute_audit.py','--execute')
        python('summarize_private','experiments/audit/summarize_private_astar.py')
    return steps

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--through',choices=('timing','private_astar'),required=True,
                        help='Last stage to include')
    parser.add_argument('--parallel',type=int,default=1)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args();assert args.parallel>0
    steps=plan(args.through,args.parallel)
    record={'status':'PLANNED_NOT_EXECUTED','through':args.through,'steps':steps,
            'requires':'All documented external tools and matching firmware/image hashes.'}
    if not args.execute:
        print(json.dumps(record,indent=2));return
    destination=ROOT/'build/reproduction_execution.json'
    assert not destination.exists(),'Use a fresh checkout to avoid overwriting earlier reproduction records'
    assert not (AUDIT/'timing_audit').exists(),'Use a fresh checkout; do not overwrite earlier timing records'
    if args.through=='private_astar':assert not (AUDIT/'private_astar/functional').exists()
    destination.parent.mkdir(exist_ok=True,parents=True)
    record['status']='RUNNING'
    for step in steps:
        destination.write_text(json.dumps(record,indent=2)+'\n')
        print('Running '+step['stage'],flush=True)
        began=time.monotonic()
        process=subprocess.run(step['command'],cwd=step['cwd'],env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
        step.update(returncode=process.returncode,elapsed_seconds=round(time.monotonic()-began,2))
        if process.returncode:
            record['status']='FAILED';destination.write_text(json.dumps(record,indent=2)+'\n')
            raise SystemExit(process.returncode)
    record['status']='COMPLETED'
    destination.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'status':record['status'],'record':str(destination)},indent=2))

if __name__=='__main__':main()
