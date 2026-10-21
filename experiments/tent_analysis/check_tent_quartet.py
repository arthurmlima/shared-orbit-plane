"""Exact diagnostic of the largest measured strided-tent rectangle outlier.
This uses the explicit adapter and seeds of this experiment, not a seed
scheme from the published design. No experiment files are modified.
"""
from pathlib import Path
import hashlib,importlib.util,json,struct
HERE=Path(__file__).parent
ROOT=HERE.parents[1]
source=ROOT/'experiments/quality/results.json'
r=json.loads(source.read_text())
ref=ROOT/'experiments/quality/nardo2023/strided/tent_ref.py'
spec=importlib.util.spec_from_file_location('tent_quartet_ref',ref)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ids=[0,3,24,27]
initial=[]
for pair in r['configuration']['key_nonce_pairs']:
    words=struct.unpack('<11I',bytes.fromhex(pair['key'])+bytes.fromhex(pair['nonce']))
    seeds=[m.seed(words,i) for i in ids]
    q=0
    for seed in seeds:q^=seed
    initial.append({'seeds':[hex(s) for s in seeds],'quartet_xor':hex(q)})
assert len({x['quartet_xor'] for x in initial})==1
seed=int(initial[0]['quartet_xor'],16)
# Independent expression of the published transition.
def step(x):
    y=x^(0xffffffff if x&0x80000000 else 0)
    return ((y<<1)&0xffffffff)|(((x>>1)^x)&1)
def output(x):
    v=0
    for bit in [30,26,22,18,14,10,6,2]:v=(v<<1)|((x>>bit)&1)
    return v
start=step(seed)
x=start
n=0
hist=[0]*256
while True:
    hist[output(x)]+=1
    x=step(x)
    n+=1
    if x==start:break
    assert n<=2097151
assert n==2097151
observed=[x for x in r['outcomes'] if x['design']=='tent2023_stride4' and x['rectangle']==[0,4,0,3]]
assert len(observed)==4
assert all(x['predictor_index']==0 and x['test_correct']==475 for x in observed)
report={'scope':'Specific experimental seed-family and output-projection diagnostic; not a general conclusion about the published word source','rectangle':[0,4,0,3],'tile_ids':ids,'key_seed_checks':initial,'quartet_state_period':n,'byte_histogram':hist,'all_byte_values_seen':sum(v>0 for v in hist),'full_cycle_xor_predictor_success_percent':100*hist[0]/n,'full_cycle_zero_byte_count':hist[0],'heldout_outcomes':observed,'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,ref,Path(__file__)]}}
(HERE/'tent_quartet_audit.json').write_text(json.dumps(report,indent=2)+'\n')
print('Quartet',hex(seed),'period',n,'zero bytes',hist[0],'success%',100*hist[0]/n)
