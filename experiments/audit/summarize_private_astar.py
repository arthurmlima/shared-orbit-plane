#!/usr/bin/env python3
"""Summarize the Private A* comparison against its routed and mapped results."""
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[1]
PRIVATE=HERE/'private_astar'
JOB='private_A_staged_N6_70'
PRIVATE_REPORT=PRIVATE/f'prepared/fpga/ooc_{JOB}/util_{JOB}.txt'
SHARED_REPORT=PROJECT/'experiments/chaos_local/normalizer_staged/fpga/ooc_plane_A_staged_N6_70/util_plane_A_staged_N6_70.txt'
BASE_REPORT=PROJECT/'src/fpga/ooc_levelC_N6_base_70/util_levelC_N6_base_70.txt'
AUDIT=PRIVATE/'postroute_audit'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def rows(path):
    return list(csv.DictReader(Path(path).read_text().splitlines(),delimiter='\t'))

def resources(path):
    text=Path(path).read_text()
    result={}
    for key,label in (('LUT','CLB LUTs'),('FF','CLB Registers'),('DSP','DSPs'),('BRAM36_tile','Block RAM Tile')):
        found=re.search(r'^\|\s*'+re.escape(label)+r'\s*\|\s*([\d.]+)\s*\|',text,re.M)
        assert found,(path,label)
        number=float(found[1]);result[key]=int(number) if number.is_integer() else number
    return result

def difference(left,right):
    return {key:left[key]-right[key] for key in left}

def timing(path):
    text=Path(path).read_text();lines=text.splitlines()
    i=next(i for i,line in enumerate(lines) if line.startswith('    WNS(ns)'))
    values=list(map(float,lines[i+2].split()))
    keys=('WNS_ns','TNS_ns','setup_failing_endpoints','setup_total_endpoints','WHS_ns','THS_ns','hold_failing_endpoints','hold_total_endpoints','WPWS_ns','TPWS_ns','pulse_failing_endpoints','pulse_total_endpoints')
    return dict(zip(keys,values))

def main():
    functional=json.loads((PRIVATE/'functional/result.json').read_text())
    assert functional['status']=='PASS'
    route=json.loads((PRIVATE/f'prepared/fpga/work/{JOB}/result.json').read_text())
    assert route['status']=='COMPLETE_AWAITING_HIERARCHY_AND_TIMING_REVIEW'
    execution=json.loads((AUDIT/'execution.json').read_text())
    assert execution['status']=='COMPLETE_AWAITING_INTERPRETATION' and execution['checkpoint_unchanged']
    banks=rows(AUDIT/'mapping/bank_summary.tsv')
    inventory=rows(AUDIT/'mapping/register_inventory.tsv')
    receivers=rows(AUDIT/'mapping/receiver_drivers.tsv')
    signatures=rows(AUDIT/'mapping/receiver_bus_signatures.tsv')
    aliases=rows(AUDIT/'mapping/identical_driver_signatures.tsv')
    unparsed=rows(AUDIT/'mapping/unparsed_registers.tsv')
    sources=[r for r in banks if r['bank'] in ('xr','xc')]
    source_inventory=[r for r in inventory if r['bank'] in ('xr','xc')]
    source_sites=Counter((r['LOC'],r['BEL']) for r in source_inventory)
    source_site_collisions={str(k):v for k,v in source_sites.items() if v>1 and 'NA' not in k}
    driver_classes=Counter(r['driver_classes'] for r in receivers)
    fanin_statuses=Counter(r['fanin_status'] for r in receivers)
    fanin_driver_mismatches=[]
    for receiver in receivers:
        direct_parents={p.rsplit('/',1)[0] for p in receiver['direct_driver_pins'].split(',') if p}
        fanin_parents={p.rsplit('/',1)[0] for p in receiver['fanin_startpoints'].split(',') if p}
        if direct_parents!=fanin_parents:fanin_driver_mismatches.append(receiver)
    mapping_findings={
        'expected_logical_source_banks':72,'observed_named_source_banks':len(sources),
        'observed_source_FD_LD_cells':len(source_inventory),
        'source_bits_by_bank':{f"{r['y']},{r['x']},{r['bank']}":int(r['mapped_FD_LD_cells']) for r in sources},
        'source_banks_with_missing_bits':[r for r in sources if r['missing_bits']],
        'source_banks_with_unused_or_replicated_state':[r for r in sources if 'REVIEW_UNUSED_OR_REPLICATED_STATE' in r['status']],
        'source_clock_names':dict(Counter(r['clock_names'] for r in source_inventory)),
        'source_site_collisions':source_site_collisions,
        'source_cells_without_placement':[r['cell'] for r in source_inventory if r['LOC']=='NA' or r['BEL']=='NA'],
        'mapped_receiver_FD_LD_cells':len(receivers),'receiver_direct_driver_classes':dict(driver_classes),
        'fanin_query_statuses':dict(fanin_statuses),'fanin_direct_driver_parent_mismatches':fanin_driver_mismatches,
        'receiver_buses_checked':len(signatures),
        'receiver_buses_with_incomplete_or_nonlocal_driver_signature':[r for r in signatures if r['complete_named_bits']!='1' or r['all_bits_have_one_same_tile_source']!='1'],
        'identical_driver_signature_aliases':aliases,'unparsed_named_registers':unparsed,
        'source_count_is_not_DSP_count':True}
    totals={'base':resources(BASE_REPORT),'shared_astar':resources(SHARED_REPORT),'private_astar':resources(PRIVATE_REPORT)}
    increments={name:difference(totals[name],totals['base']) for name in ('shared_astar','private_astar')}
    direct=difference(totals['private_astar'],totals['shared_astar'])
    t=timing(AUDIT/'timing/timing_summary_unconstrained.txt')
    checks={name:int(value) for name,value in re.findall(r'checking (\w+) \((\d+)\)',(AUDIT/'timing/check_timing.txt').read_text())}
    dsp=rows(AUDIT/'timing/sampled_dsp_constants.tsv')
    timing_text=(AUDIT/'timing/timing_summary_unconstrained.txt').read_text()
    sampled_internal=set()
    for block in re.split(r'(?=Slack\s*[:(])',timing_text):
        if re.match(r'Slack\s*:\s*inf',block):
            found=re.search(r'^\s*Source:\s*(\S+)\s*\n\s*\(internal pin\)',block,re.M)
            if found:sampled_internal.add(found[1])
    unclassified_internal=sorted(sampled_internal-{r['start_pin'] for r in dsp})
    dsp_constants=all(r['BREG']=='0' and r['B_INPUT']=='DIRECT' and r['B_input_logic']=='zero' and r['INMODE_4_to_0']=='zero,zero,zero,zero,zero' for r in dsp)
    coverage=rows(AUDIT/'timing/register_coverage.tsv')
    bad_timing_endpoints=[r for r in coverage if r['clock_names']!='clk' or r['setup_path_present']!='1' or r['setup_slack'] in ('NA','inf','-inf')]
    except_none='No valid timing exceptions found.' in (AUDIT/'timing/exceptions.txt').read_text()
    mapping_pass=(len(sources)==72 and len(source_inventory)==2304 and len(receivers)==2304 and not source_site_collisions and not mapping_findings['source_cells_without_placement'] and not mapping_findings['source_banks_with_missing_bits'] and not mapping_findings['source_banks_with_unused_or_replicated_state'] and len(signatures)==72 and not mapping_findings['receiver_buses_with_incomplete_or_nonlocal_driver_signature'] and not aliases and not unparsed and driver_classes=={'SAME_TILE_SOURCE':2304} and fanin_statuses=={'OK':2304} and not fanin_driver_mismatches)
    criteria={'functional_byte_and_application_reference':True,'positive_sharing_LUT_saving':direct['LUT']>0,
              'common70MHz_internal_setup':t['WNS_ns']>=0,'common_internal_hold':t['WHS_ns']>=0,
              'mapped_local_source_evidence':mapping_pass,
              'intended_registered_timing_coverage':not bad_timing_endpoints and checks['no_clock']==0 and checks['unconstrained_internal_endpoints']==0 and except_none,
              'sampled_unconstrained_DSP_starts_constant_bypass':dsp_constants and not unclassified_internal}
    result={'status':'PASS' if all(criteria.values()) else 'FAIL',
            'criteria':criteria,'complete_N6_resources':totals,'complete_configuration_increments_over_base':increments,
            'private_minus_shared_N6_resources':direct,
            'sharing_LUT_saving_fraction_of_private_total':direct['LUT']/totals['private_astar']['LUT'],
            'sharing_LUT_saving_fraction_of_private_added_configuration':direct['LUT']/increments['private_astar']['LUT'],
            'N6_private_timing':t,'timing_checks':checks,'inventoried_timing_endpoints':len(coverage),
            'timing_endpoint_findings':bad_timing_endpoints,'no_valid_timing_exceptions':except_none,
            'sampled_unconstrained_DSP_unique_starts':len(dsp),'sampled_DSP_constants':dsp,
            'sampled_internal_unconstrained_starts':sorted(sampled_internal),'unclassified_sampled_internal_starts':unclassified_internal,
            'mapping':mapping_findings,'N3_functional_comparisons':functional['comparisons'],
            'functional_result':str(PRIVATE/'functional/result.json'),
            'provenance':{'functional_result_sha256':sha(PRIVATE/'functional/result.json'),
                          'route_result_sha256':sha(PRIVATE/f'prepared/fpga/work/{JOB}/result.json'),
                          'audit_execution_sha256':sha(AUDIT/'execution.json'),
                          'base_report_sha256':sha(BASE_REPORT),'shared_report_sha256':sha(SHARED_REPORT),'private_report_sha256':sha(PRIVATE_REPORT),
                          'source_manifest_sha256':sha(PRIVATE/'source_manifest.json'),'private_routed_DCP_sha256':execution['checkpoint_sha256']},
            'limits':[
                'The direct Shared A* versus Private A* comparison changes only source ownership/input selection. Both retain collective advance; this does not measure independent private delivery.',
                'Base-normalized values are complete-configuration increments. The Base configuration uses the common flow without a full RTL hash manifest; its disabled-generator geometry is elaborated differently and any residual area effect is unmeasured.',
                'The clock is introduced after synthesis. Timing refers to the original70MHz internal out-of-context model. External AXI input/output delays and enclosing clock-buffer delay/skew remain outside scope.',
                'The unconstrained report is capped at20paths per group. Printed internal DSP starts are classified from actual static settings; the listing is not exhaustive.',
                'No private-only preservation attributes or additional route for preferred values were used.'
            ]}
    (PRIVATE/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['Complete-mesh Private A* evaluation','',result['status'],'',
           'N6 routed totals and complete-configuration increments over the published base:',
           'Configuration        LUT      FF   DSP  BRAM36']
    for name,data in totals.items():lines.append(f"{name:18s} {data['LUT']:7d} {data['FF']:7d} {data['DSP']:5d} {data['BRAM36_tile']:7g}")
    lines+=['','Private minus Shared A*: '+str(direct),'',
            'Private internal timing: WNS='+str(t['WNS_ns'])+'ns; WHS='+str(t['WHS_ns'])+'ns.',
            f"Mapped source banks: {len(sources)}; source FD/LD cells: {len(source_inventory)}; receiver FD/LD cells: {len(receivers)}.",
            'Receiver direct-driver classes: '+str(dict(driver_classes)),
            f"Source placement collisions: {len(source_site_collisions)}; identical receiver-bus driver signatures: {len(aliases)}.",'',
            'N3 shared/private application comparisons: '+str(functional['comparisons']),'']+result['limits']
    (PRIVATE/'summary.txt').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:result[k] for k in ('status','criteria','complete_N6_resources','complete_configuration_increments_over_base','private_minus_shared_N6_resources','N6_private_timing')},indent=2))

if __name__=='__main__':main()
