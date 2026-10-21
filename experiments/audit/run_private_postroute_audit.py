#!/usr/bin/env python3
"""Read-only mapping and scoped timing audit after the one Private A* route."""
import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREPARED = HERE/'private_astar/prepared'
JOB = 'private_A_staged_N6_70'
FPGA = PREPARED/'fpga'
CHECKPOINT = FPGA/f'ooc_{JOB}/routed_{JOB}.dcp'
OUT = HERE/'private_astar/postroute_audit'
VIVADO = os.environ.get('VIVADO', 'vivado')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def strip_tail(text):
    tail = 'close_design\nexit\n'
    assert text.endswith(tail)
    return text[:-len(tail)]

def combined_script():
    mapping = strip_tail((HERE/'private_mapping_audit.tcl').read_text())
    timing = strip_tail((HERE/'existing_timing_audit.tcl').read_text())
    assert timing.count('open_checkpoint $checkpoint\n') == 1
    timing = timing.replace('open_checkpoint $checkpoint\n','',1)
    # Keep one checkpoint open while running the two unchanged query bodies.
    preamble = '''set audit_checkpoint [file normalize [lindex $argv 0]]
set audit_root [file normalize [lindex $argv 1]]
set argv [list $audit_checkpoint "$audit_root/mapping" 6]
'''
    between = '''\nset argv [list $audit_checkpoint "$audit_root/timing"]\n'''
    sampled = r'''
# Classify only the DSP starts actually printed in the max20 unconstrained list.
set sf [open "$out/timing_summary_unconstrained.txt" r]
set summary_text [read $sf]
close $sf
set starts {}
foreach {whole pin} [regexp -all -inline -line {^\s*Source:\s+(\S*/DSP_A_B_DATA_INST/B2_DATA\[[0-9]+\])\s*$} $summary_text] {
    lappend starts $pin
}
set starts [lsort -unique $starts]
set sf [open "$out/sampled_dsp_constants.tsv" w]
puts $sf "start_pin\tBREG\tB_INPUT\tB_input_logic\tINMODE_4_to_0\tCEB2_logic"
foreach start $starts {
    regexp {^(.*)/DSP_A_B_DATA_INST/B2_DATA\[([0-9]+)\]$} $start ignored parent bit
    set cell [get_cells -quiet -hier -filter [format {NAME == "%s"} "$parent/DSP_A_B_DATA_INST"]]
    set bpin [get_pins -quiet -hier -filter [format {NAME == "%s"} [format {%s/B[%d]} $parent $bit]]]
    set mode {}
    foreach b {4 3 2 1 0} {
        lappend mode [get_property LOGIC_VALUE [get_pins -quiet -hier -filter [format {NAME == "%s"} [format {%s/INMODE[%d]} $parent $b]]]]
    }
    set ce [get_pins -quiet -hier -filter [format {NAME == "%s"} "$parent/CEB2"]]
    puts $sf "$start\t[get_property BREG $cell]\t[get_property B_INPUT $cell]\t[get_property LOGIC_VALUE $bpin]\t[join $mode ,]\t[get_property LOGIC_VALUE $ce]"
}
close $sf
close_design
exit
'''
    return preamble+mapping+between+timing+sampled

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    sources={name:sha(HERE/name) for name in ('private_mapping_audit.tcl','existing_timing_audit.tcl')}
    if not args.execute:
        print(json.dumps({'status':'PLANNED_NOT_EXECUTED','checkpoint':str(CHECKPOINT),'output':str(OUT),'query_sources':sources},indent=2));return
    manifest=json.loads((HERE/'private_astar/source_manifest.json').read_text())
    for name,expected in manifest['source_hashes_prepared'].items():
        assert sha(PREPARED/name)==expected,name
    record=json.loads((FPGA/f'work/{JOB}/result.json').read_text())
    assert record['status']=='COMPLETE_AWAITING_HIERARCHY_AND_TIMING_REVIEW'
    assert json.loads((HERE/'private_astar/functional/result.json').read_text())['status']=='PASS'
    assert not OUT.exists(),'Refusing to replace an existing audit'
    OUT.mkdir(parents=True)
    script=OUT/'private_postroute_queries.tcl'
    script.write_text(combined_script())
    dcp_sha=sha(CHECKPOINT)
    command=[VIVADO,'-mode','batch','-nojournal','-nolog','-source',str(script),'-tclargs',str(CHECKPOINT),str(OUT)]
    began=time.monotonic()
    with (OUT/'vivado.log').open('w') as log:
        process=subprocess.run(command,cwd=OUT,stdout=log,stderr=subprocess.STDOUT)
    result={'status':'COMPLETE_AWAITING_INTERPRETATION' if process.returncode==0 else 'FAILED',
            'returncode':process.returncode,'elapsed_seconds':round(time.monotonic()-began,2),
            'command':command,'query_sources':sources,'combined_query_sha256':sha(script),
            'checkpoint_sha256':dcp_sha,'checkpoint_unchanged':sha(CHECKPOINT)==dcp_sha,
            'prepared_sources_unchanged':all(sha(PREPARED/name)==expected for name,expected in manifest['source_hashes_prepared'].items()),
            'scope':'One existing routed checkpoint; read-only queries only, no constraint or checkpoint writes.'}
    (OUT/'execution.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if process.returncode:raise SystemExit(process.returncode)

if __name__=='__main__':main()
