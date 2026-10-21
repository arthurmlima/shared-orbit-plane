#!/usr/bin/env python3
"""Clock-driven four-requestor arbiter checks on fixed held-out byte streams."""
from pathlib import Path
import csv,ctypes,hashlib,importlib.util,json,os,re,shutil,struct,subprocess,sys,time
import numpy as np
P=Path(__file__).resolve().parent;Q=P.parent;ROOT=Q.parents[1]
sys.path.insert(0,str(Q));import run_quality as q
R=json.loads((Q/'results.json').read_text());CFG=R['configuration']
N=6;L=125000;SPLIT=62500;CYCLES=62500
IVERILOG=os.environ.get('IVERILOG','iverilog')
VVP=os.environ.get('VVP','vvp')
shutil.copy2(Q/'generate_fast.cpp',P/'generate_fast.cpp')
subprocess.run([os.environ.get('CXX','g++'),'-O3','-shared','-fPIC','generate_fast.cpp','-o','generate_fast.so'],cwd=P,check=True)
compile_command=[IVERILOG,'-g2012','-s','tb_arbiter','-o','arbiter.vvp','round_robin4.v','tb_arbiter.v']
compiled=subprocess.run(compile_command,cwd=P,capture_output=True,text=True,check=True)
(P/'compile.log').write_text(compiled.stdout+compiled.stderr)
lib=ctypes.CDLL(str(P/'generate_fast.so'));p64=ctypes.POINTER(ctypes.c_uint64);p8=ctypes.POINTER(ctypes.c_uint8)
lib.generate.argtypes=[p64,p8,ctypes.c_int,ctypes.c_int,ctypes.c_int]
lib.generate_logistic.argtypes=[p64,p64,p8,ctypes.c_int,ctypes.c_int]
def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
local=module('arbiter_logistic_ref',ROOT/'experiments/chaos_local/local_logistic_ref.py')
tent=module('arbiter_tent_ref',Q/'nardo2023/strided/tent_ref.py')
def gen(seeds,mode):
 a=np.ascontiguousarray(seeds,dtype=np.uint64);B=np.empty((36,L),np.uint8)
 lib.generate(a.ctypes.data_as(p64),B.ctypes.data_as(p8),36,L,mode)
 return B.reshape(N,N,L)
def genlog(words):
 seeds=[local.seeds(words,tile) for tile in range(36)]
 a=np.ascontiguousarray([s[0] for s in seeds],dtype=np.uint64);b=np.ascontiguousarray([s[1] for s in seeds],dtype=np.uint64);B=np.empty((36,L),np.uint8)
 lib.generate_logistic(a.ctypes.data_as(p64),b.ctypes.data_as(p64),B.ctypes.data_as(p8),36,L)
 return B.reshape(N,N,L)
hashes={(s['design'],s['key_index']):s['sha256_tile_major'] for s in R['stream_hashes']}
records=[];traces=[];started=time.time()
def run_case(B,ki,name):
 full_sha=hashlib.sha256(B.tobytes()).hexdigest();assert full_sha==hashes[name,ki],(name,ki)
 masks=((B[0,0,SPLIT:]>>7)<<3)|((B[0,1,SPLIT:]>>7)<<2)|((B[1,0,SPLIT:]>>7)<<1)|(B[1,1,SPLIT:]>>7)
 counts=np.bincount(masks,minlength=16);support=int((counts>0).sum())
 expected=np.empty(CYCLES,np.uint8);head=0;grant_counts=[0]*4;accepted=0
 for cycle,mask in enumerate(map(int,masks)):
  before=head
  if mask:
   rotated=((mask>>head)|(mask<<(4-head)))&15
   winner=((rotated&-rotated).bit_length()-1+head)&3
   grant=1<<winner;head=(winner+1)&3;grant_counts[winner]+=1;accepted+=1
  else:grant=0
  expected[cycle]=(before<<6)|(head<<4)|grant
  if cycle<16 or cycle>=CYCLES-16:
   traces.append({'design':name,'key_index':ki,'cycle':cycle,'mask':mask,'head_before':before,'grant':grant,'head_after':head})
 (P/'masks.mem').write_text(''.join(f'{int(x):x}\n' for x in masks))
 (P/'expected.mem').write_text(''.join(f'{int(x):02x}\n' for x in expected))
 mask_sha=hashlib.sha256((P/'masks.mem').read_bytes()).hexdigest();gold_sha=hashlib.sha256((P/'expected.mem').read_bytes()).hexdigest()
 run=subprocess.run([VVP,'arbiter.vvp'],cwd=P,capture_output=True,text=True,timeout=30)
 log=run.stdout+run.stderr;(P/f'{name}_key{ki}.log').write_text(log)
 if run.returncode:raise RuntimeError(log)
 match=re.search(r'PASS cycles=(\d+) golden_grant_checks=(\d+) golden_state_checks=(\d+) mask_support=(\d+) accepted_grants=(\d+)',log)
 assert match,log
 assert list(map(int,match.groups()))==[CYCLES,CYCLES,2*CYCLES,support,accepted]
 gh=re.search(r'GRANTS (\d+) (\d+) (\d+) (\d+)',log);assert list(map(int,gh.groups()))==grant_counts
 record={'design':name,'key_index':ki,'cycles':CYCLES,'full_stream_bytes_hash_checked':36*L,'full_stream_sha256_tile_major':full_sha,'masks_mem_sha256':mask_sha,'golden_mem_sha256':gold_sha,'mask_support':support,'mask_requirement_met':support==16,'mask_histogram':counts.tolist(),'accepted_grants':accepted,'grant_histogram':grant_counts,'dut_mismatches':0}
 records.append(record);print(name,ki,'PASS',support,'masks',accepted,'grants',flush=True)
cr=np.random.default_rng(20271014)
for ki,pair in enumerate(CFG['key_nonce_pairs']):
 key=bytes.fromhex(pair['key']);nonce=bytes.fromhex(pair['nonce']);words=struct.unpack('<11I',key+nonce)
 for name,B in q.plane_streams(key,nonce).items():run_case(B,ki,name)
 mixed=0
 for word in words:mixed=q.xs((mixed+((word<<32)|(word^0x9e3779b9)))&q.MASK)
 seeds=[q.xs(mixed^((q.GOLD*(tile+1))&q.MASK)) or q.GOLD for tile in range(36)]
 run_case(gen(seeds,0),ki,'xs64_local')
 run_case(genlog(words),ki,'logistic_local')
 run_case(gen([tent.seed(words,tile) for tile in range(36)],4),ki,'tent2023_stride4')
 run_case(cr.integers(0,256,(N,N,L),dtype=np.uint8),ki,'uniform_control')
files=[Path(__file__),P/'round_robin4.v',P/'tb_arbiter.v',P/'generate_fast.cpp',ROOT/'src/quality/heldout/config.json',Q/'run_quality.py',ROOT/'experiments/chaos_local/local_logistic_ref.py',Q/'nardo2023/strided/tent_ref.py']
manifest={'status':'all DUT checks pass','scope':'reference-generated stream masks driving a four-requestor HDL arbiter; no integrated generator hardware, firmware, fault coverage or speed claim','configuration':{'N':N,'rectangle':[0,1,0,1],'L':L,'split':SPLIT,'cycles_per_case':CYCLES,'key_nonce_pairs':CFG['key_nonce_pairs'],'initial_head':0,'every_nonzero_grant_accepted':True},'elapsed_seconds':time.time()-started,'cases':len(records),'hdl_cycles':sum(r['cycles'] for r in records),'golden_grant_comparisons':sum(r['cycles'] for r in records),'golden_state_comparisons':sum(2*r['cycles'] for r in records),'full_stream_bytes_hash_checked':sum(r['full_stream_bytes_hash_checked'] for r in records),'cases_meeting_16mask_requirement':sum(r['mask_requirement_met'] for r in records),'mismatches':0,'compile_command':compile_command,'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'records':records}
(P/'results.json').write_text(json.dumps(manifest,indent=2)+'\n')
with (P/'results.csv').open('w') as f:
 fields=['design','key_index','cycles','mask_support','mask_requirement_met','accepted_grants','dut_mismatches'];w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(records)
with (P/'trace_excerpt.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(traces[0]));w.writeheader();w.writerows(traces)
for name in ['masks.mem','expected.mem','arbiter.vvp','generate_fast.so']:(P/name).unlink()
print('DONE',manifest['hdl_cycles'],'HDL cycles',manifest['cases_meeting_16mask_requirement'],'of',manifest['cases'],'mask requirements met',round(time.time()-started,2),'seconds')
