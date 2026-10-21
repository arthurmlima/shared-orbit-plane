#!/usr/bin/env python3
"""Collect regenerated common-flow implementation runs without waiting.

Usage: python3 experiments/collect_comparisons.py [--outdir DIRECTORY]
Writes comparison_routed.json/.csv. Missing
runs stay explicitly pending; synthesis-only files never become routed results.
"""
import argparse
import csv
import datetime
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
REV=HERE.parent
ARCH=REV/'src'
METRICS=('LUT','LUT_logic','LUT_memory','FF','BRAM_tiles','DSP','URAM')
COMMON={'IMG_W':'120','IMG_H':'120','FAST_CORE':'1','PM_BYPASS':'1','USE_PPU':'2'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_original_collector():
    spec=importlib.util.spec_from_file_location('routed_collect',ARCH/'tools/collect.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def definitions():
    arch=ARCH/'fpga'
    return [
        ('base','Base mesh',arch,'levelC_N{N}_base_70'),
        ('plane_A_original','Shared A, original',arch,'levelC_N{N}_plane_ext0_70'),
        ('plane_A_staged','Shared A, staged',HERE/'chaos_local/normalizer_staged/fpga','plane_A_staged_N{N}_70'),
        ('plane_B','Shared B',arch,'levelC_N{N}_plane_ext1_70'),
        ('plane_C','Shared C',arch,'levelC_N{N}_plane_ext2_70'),
        ('plane_D','Shared D',arch,'levelC_N{N}_plane_ext3_70'),
        ('local_logistic','Local logistic',HERE/'chaos_local/prepared/fpga','local_logistic_N{N}_70'),
        ('tent_stride4','Local tent, stride 4',HERE/'quality/nardo2023/strided/prepared/fpga','tent_stride4_N{N}_70'),
        ('xs64','Local xorshift64',HERE/'xs64_baseline/prepared/fpga','xs64_N{N}_70'),
        ('trivium','Local Trivium',arch,'levelC_N{N}_trivium_70'),
        ('chacha','Local ChaCha20',arch,'levelC_N{N}_chacha_70'),
    ]


def read_run(identifier,label,fpga,template,n,collector):
    tag=template.format(N=n)
    out=fpga/f'ooc_{tag}'
    required=[out/f'{stem}_{tag}.txt' for stem in ('fmax','util','timing')]
    result={'id':identifier,'label':label,'N':n,'tag':tag,'report_directory':str(out),
            'status':'pending','missing_reports':[str(path) for path in required if not path.is_file()],
            'provenance':{},'warnings':[]}
    command_file=fpga/'work'/tag/'command.json'
    result_file=fpga/'work'/tag/'result.json'
    if command_file.is_file():
        result['command']=json.loads(command_file.read_text())
        result['provenance'][str(command_file)]=sha(command_file)
    if result_file.is_file():
        result['process_result']=json.loads(result_file.read_text())
        result['provenance'][str(result_file)]=sha(result_file)
        if result['process_result'].get('returncode') not in (None,0):
            result['status']='failed'
    if result['missing_reports'] or result['status']=='failed':
        return result
    # fmax is the original flow's final report, written after routing, timing,
    # power and checkpoint export. Only these completed flows are collected.
    fm=collector.fmax(required[0])
    result.update(status='complete',resources=collector.util_metrics(required[1]),
                  resource_table=collector.util_table(required[1]),
                  timing=collector.timing_summary(required[2]),fmax=fm)
    for path in sorted(out.glob('*.txt')):
        result['provenance'][str(path)]=sha(path)
    p=out/f'power_{tag}.txt'
    result['power_vectorless_estimate']=collector.power(p) if p.is_file() else None
    util_text=required[1].read_text()
    for key,pattern in (
        ('tool_version',r'^\| Tool Version\s*:\s*(.+)$'),
        ('device',r'^\| Device\s*:\s*(\S+)'),
        ('design_state',r'^\| Design State\s*:\s*(\S+)')):
        match=re.search(pattern,util_text,re.M)
        result[key]=match.group(1).strip() if match else None
    generics=dict(re.findall(r'(\w+)=(\S+)',fm.get('generics') or ''))
    result['generics']=generics
    checks={
        '70_MHz':fm.get('target_MHz')==70,
        'top_mpriscv_axi':fm.get('top')=='mpriscv_axi',
        'N_matches':generics.get('N')==str(n),
        'common_mesh_configuration':all(generics.get(k)==v for k,v in COMMON.items()),
        'same_device':result['device']=='xczu7ev-ffvc1156-2-e',
        'routed_state':result['design_state']=='Routed',
    }
    flow=fpga/'impl_ooc.tcl'
    checks['unmodified_common_flow']=flow.is_file() and sha(flow)==sha(ARCH/'fpga/impl_ooc.tcl')
    result['comparison_checks']=checks
    result['comparable']=all(checks.values())
    timing=result['timing']
    result['timing_met']=bool(timing and all(timing.get(k,float('-inf'))>=0 for k in ('WNS','WHS','WPWS')))
    if not result['comparable']:
        result['warnings'].append('Common-flow check failed: '+', '.join(k for k,v in checks.items() if not v))
    if not result['timing_met']:
        result['warnings'].append('The 70 MHz constraint is not met for all reported timing categories.')
    return result


def delta(value,base):
    return value-base if value is not None and base is not None else None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outdir',type=Path,default=HERE/'comparison_collection')
    args=parser.parse_args()
    outdir=args.outdir.resolve()
    outdir.mkdir(parents=True,exist_ok=True)
    collector=load_original_collector()
    records=[read_run(identifier,label,fpga,template,n,collector)
             for identifier,label,fpga,template in definitions() for n in (3,4,6)]
    bases={row['N']:row for row in records if row['id']=='base'}
    for row in records:
        if row['status']!='complete':
            continue
        base=bases[row['N']]
        if base['status']=='complete':
            row['base_tag']=base['tag']
            row['added_over_same_N_base']={key:delta(row['resources'][key],base['resources'][key]) for key in METRICS}
    payload={'collected_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'collector_sha256':sha(Path(__file__)),'parser_sha256':sha(ARCH/'tools/collect.py'),
             'scope':'Completed routed whole-mesh runs, common 70 MHz flow. Superseded low-byte tent prototype excluded.',
             'note':'Added resources are complete-mesh differences over the same-N base; they include integration/optimization effects. Vectorless power and slack-derived Fmax are estimates.',
             'complete_count':sum(row['status']=='complete' for row in records),
             'pending_count':sum(row['status']=='pending' for row in records),
             'failed_count':sum(row['status']=='failed' for row in records),
             'records':records}
    (outdir/'comparison_routed.json').write_text(json.dumps(payload,indent=2)+'\n')
    columns=['id','label','N','tag','status','comparable','timing_met']+list(METRICS)+['added_'+key for key in METRICS]+['WNS_ns','WHS_ns','WPWS_ns','Fmax_MHz_estimate','report_directory']
    with (outdir/'comparison_routed.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=columns)
        writer.writeheader()
        for row in records:
            flat={key:row.get(key) for key in columns}
            flat.update(row.get('resources',{}))
            flat.update({'added_'+key:value for key,value in row.get('added_over_same_N_base',{}).items()})
            flat.update({key+'_ns':row.get('timing',{}).get(key) for key in ('WNS','WHS','WPWS')})
            flat['Fmax_MHz_estimate']=row.get('fmax',{}).get('Fmax_MHz')
            writer.writerow(flat)
    print(json.dumps({key:payload[key] for key in ('complete_count','pending_count','failed_count')},indent=2))


if __name__=='__main__':
    main()
