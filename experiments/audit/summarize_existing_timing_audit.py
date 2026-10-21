#!/usr/bin/env python3
"""Summarize read-only checkpoint timing coverage, keeping OOC/model scope explicit."""
import csv
import hashlib
import json
import os
import shutil
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE/'timing_audit'

def installed_model(name):
    root = os.environ.get('VIVADO_ROOT')
    if root is None:
        executable = shutil.which(os.environ.get('VIVADO', 'vivado'))
        if executable is None:
            raise SystemExit('Set VIVADO_ROOT to the Vivado installation when summarizing the installed DSP model.')
        root = str(Path(executable).absolute().parent.parent)
    path = Path(root)/'data/verilog/src/unisims'/name
    if not path.is_file():
        raise SystemExit(f'Installed model missing: {path}; set VIVADO_ROOT explicitly.')
    return path

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def tsv(path):
    return list(csv.DictReader(Path(path).read_text().splitlines(), delimiter='\t'))

def first_path(path):
    text = Path(path).read_text()
    slack = re.search(r'Slack \(\w+\)\s*:\s*([\d.-]+)ns', text)
    source = re.search(r'^\s*Source:\s*(\S+)', text, re.M)
    end = re.search(r'^\s*Destination:\s*(\S+)', text, re.M)
    return {'slack_ns': float(slack[1]) if slack else None,
            'source': source[1] if source else None, 'endpoint': end[1] if end else None}

constant_operand=tsv(BASE/'dsp_static_N6/static_operand.tsv')
constant_b=[r for r in constant_operand if re.search(r'/B\[\d+\]$',r['object'])]
assert len(constant_b)==18 and all(r['value']=='zero' for r in constant_b)
assert any(r['object'].endswith('/DSP_MULTIPLIER_INST') and r['property']=='BMULTSEL' and r['value']=='B' for r in constant_operand)
results=[]
for n in (3,4,6):
    directory=BASE/f'N{n}'
    execution=json.loads((directory/'audit_execution.json').read_text())
    text=(directory/'timing_summary_unconstrained.txt').read_text()
    lines=text.splitlines()
    line=next(i for i,l in enumerate(lines) if l.startswith('    WNS(ns)'))
    values=lines[line+2].split()
    timing=dict(zip(('WNS_ns','TNS_ns','setup_failing_endpoints','setup_total_endpoints',
                     'WHS_ns','THS_ns','hold_failing_endpoints','hold_total_endpoints',
                     'WPWS_ns','TPWS_ns','pulse_failing_endpoints','pulse_total_endpoints'),
                    map(float,values)))
    checks={name:int(count) for name,count in re.findall(r'checking (\w+) \((\d+)\)',(directory/'check_timing.txt').read_text())}
    registers=tsv(directory/'register_coverage.tsv')
    bad=[r for r in registers if r['clock_names']!='clk' or r['setup_path_present']!='1' or r['setup_slack'] in ('NA','inf','-inf')]
    classes={name:sum(r['class']==name for r in registers) for name in sorted({r['class'] for r in registers})}
    paths={name:first_path(directory/f'{name}_paths.txt') for name in ('recurrence','distribution','readiness_reduction','initialization_reduction','advance_to_source')}
    sampled_dir=BASE/f'dsp_sampled_N{n}'
    dsp=tsv(sampled_dir/'sampled_dsp.tsv')
    active=tsv(sampled_dir/'active_bit_paths.tsv')
    assert len(dsp)==len((directory/'sampled_dsp_starts.txt').read_text().splitlines())
    assert all(r['BREG']=='0' and r['B_INPUT']=='DIRECT' and r['B_input_logic']=='zero' and r['INMODE_4_to_0']=='zero,zero,zero,zero,zero' for r in dsp), dsp
    assert len(active)==len(dsp)
    active_finite=[r for r in active if r['slack'] not in ('NA','inf','-inf')]
    assert active_finite, active
    assert not bad and all(p['slack_ns'] is not None for p in paths.values())
    assert checks['no_clock']==0 and checks['unconstrained_internal_endpoints']==0
    assert 'No valid timing exceptions found.' in (directory/'exceptions.txt').read_text()
    current_hash=sha(execution['checkpoint'])
    assert current_hash==execution['checkpoint_sha256']
    results.append({'N':n,'timing':timing,'checks':checks,'register_class_counts':classes,
                    'all_inventoried_registers_clocked_with_finite_setup_path':not bad,
                    'path_class_representatives':paths,'clock':'clk','period_ns':14.286,
                    'no_valid_timing_exceptions':True,
                    'checkpoint_sha256':current_hash,'checkpoint_unchanged':True,
                    'sampled_split_model_starts':dsp,'adjacent_active_bit_paths':active,
                    'adjacent_finite_B_path_count':len(active_finite),
                    'report_limit_per_path_group':20,
                    'scope':'OOC internal clk timing; external AXI I/O has no delay constraints.'})

summary={
 'assessment':'INTENDED_REGISTERED_PATHS_CONSTRAINED_WITH_OOC_SCOPE',
 'scope':'Existing Shared A* routed N3/N4/N6 checkpoints. No original source, constraint, route or DCP changes.',
 'findings':results,
 'interpretation':{
  'registered_architecture':'Global check_timing reports zero no_clock and unconstrained_internal_endpoints findings. Every inventoried source, receiver, readiness/initialization state and collective-control register has clk and a finite setup path; each requested path class has a finite clk-to-clk report.',
  'split_model_entries':'The capped unconstrained reports contain internal B2_DATA[17] starts. Every unique start sampled in those reports was checked: BREG=0, B_INPUT=DIRECT, parent B[17]=constant zero and INMODE=00000. The installed AMD model routes B2_DATA from B in this configuration. Nine of these ten cells have a finite orbit-register-to-orbit-register setup path through an adjacent nonconstant B-side bit. The remaining N6 cell has all eighteen B operand bits constant zero and BMULTSEL=B, explaining the absence of a dynamic B-side feedback path. This is a constant multiplier-operand case, not a claim that every DSP ALU/cascade input is constant. These constant-input split-model entries are distinguished from active unclocked state; the capped path list is not exhaustive.',
  'external_io':'50 AXI input ports and 37 AXI output ports lack external delays in each original common-flow checkpoint. These interfaces are outside this internal timing scope.',
  'physical_clock':'HD.CLK_SRC is absent. Vivado warns that OOC clock delay/skew cannot be estimated without the enclosing top-level clock-buffer location. Reported slack therefore belongs to the existing OOC clock model and is not a board-level maximum-frequency measurement.',
  'limitations':'This is a scoped intended-path audit, not proof of every possible split-model arc. The max20 unconstrained listings are sampled and no constraints were added to suppress them.'},
 'installed_model_sources':[
  {'path':str(installed_model('DSP_A_B_DATA.v')),'lines':'500-502','sha256':sha(installed_model('DSP_A_B_DATA.v')),'fact':'BREG=0 and B_INPUT=DIRECT routes B2_DATA from B.'},
  {'path':str(installed_model('DSP_PREADD_DATA.v')),'lines':'425-428','sha256':sha(installed_model('DSP_PREADD_DATA.v')),'fact':'INMODE[4]=0 selects B2_DATA for B2B1.'}],
 'remaining_N6_constant_B_operand':{'cell':'u_mesh/g_row[5].g_col[5].u_tile/g_dist.u_ks/t0__1','B_bits_constant_zero':18,'BMULTSEL':'B','source':str(BASE/'dsp_static_N6/static_operand.tsv'),'records':constant_operand},
 'private_functional_or_route_executed':False}
(BASE/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
lines=['Existing Shared A* checkpoint timing audit','',summary['assessment'],'',summary['scope'],'',
       'N   WNS(ns)  WHS(ns)  Setup endpoints  Inventoried registers  Sampled DSP starts']
for r in results:
 lines.append(f"{r['N']}   {r['timing']['WNS_ns']:.3f}    {r['timing']['WHS_ns']:.3f}    {int(r['timing']['setup_total_endpoints']):7d}          {sum(r['register_class_counts'].values()):5d}                    {len(r['sampled_split_model_starts'])}")
lines+=['']+list(summary['interpretation'].values())+['','All DCP hashes rechecked unchanged.']
(BASE/'summary.txt').write_text('\n'.join(lines)+'\n')
print(json.dumps({'assessment':summary['assessment'],'N':[r['N'] for r in results], 'sampled_unique_entries':sum(len(r['sampled_split_model_starts']) for r in results),'summary':str(BASE/'summary.json')},indent=2))
