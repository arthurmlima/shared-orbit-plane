#!/usr/bin/env python3
"""Fixed lag4 lookup extension, exact stream-hash checked against quality run."""
from pathlib import Path
import ctypes,csv,hashlib,importlib.util,json,os,struct,subprocess,time
import numpy as np
import run_quality as q
P=Path(__file__).resolve().parent
R=json.loads((P/'results.json').read_text())
CFG=R['configuration'];L=CFG['L'];S=CFG['split'];N=CFG['N']
def module(name,path):
 sp=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);return m
local=module('logistic_fast_seed',P.parents[0]/'chaos_local/local_logistic_ref.py')
tent=module('tent_fast_seed',P/'nardo2023/tent_ref.py')
subprocess.run([os.environ.get('CXX','g++'),'-O3','-shared','-fPIC','generate_fast.cpp','-o','generate_fast.so'],cwd=P,check=True)
lib=ctypes.CDLL(str(P/'generate_fast.so'))
p64=ctypes.POINTER(ctypes.c_uint64);p8=ctypes.POINTER(ctypes.c_uint8)
lib.generate.argtypes=[p64,p8,ctypes.c_int,ctypes.c_int,ctypes.c_int]
lib.generate_logistic.argtypes=[p64,p64,p8,ctypes.c_int,ctypes.c_int]
def gen(seeds,mode):
 a=np.ascontiguousarray(seeds,dtype=np.uint64);B=np.empty((N*N,L),np.uint8)
 lib.generate(a.ctypes.data_as(p64),B.ctypes.data_as(p8),N*N,L,mode)
 return B.reshape(N,N,L)
def genlog(words):
 seeds=[local.seeds(words,tile) for tile in range(N*N)]
 a=np.ascontiguousarray([s[0] for s in seeds],dtype=np.uint64);b=np.ascontiguousarray([s[1] for s in seeds],dtype=np.uint64);B=np.empty((N*N,L),np.uint8)
 lib.generate_logistic(a.ctypes.data_as(p64),b.ctypes.data_as(p64),B.ctypes.data_as(p8),N*N,L)
 return B.reshape(N,N,L)
hashes={(r['design'],r['key_index']):r['sha256_tile_major'] for r in R['stream_hashes']}
old={(r['design'],r['key_index'],r['tile_id']):r for r in R['temporal_outcomes']}
rows=[];summaries=[];validated=[]
def score(B,ki,name):
 hashed=hashlib.sha256(B.tobytes()).hexdigest();assert hashed==hashes[name,ki],(name,ki)
 validated.append({'design':name,'key_index':ki,'bytes_checked':N*N*L,'sha256_tile_major':hashed})
 for lag in [1,4]:
  tr=[]
  for tile,seq in enumerate(B.reshape(N*N,L)):
   a=seq[:S-lag].astype(np.int64);b=seq[lag:S].astype(np.int64)
   hist=np.bincount(a*256+b,minlength=65536).reshape(256,256)
   mode=hist.argmax(axis=1).astype(np.uint8)
   correct=int(np.count_nonzero(mode[seq[S:-lag]]==seq[S+lag:]))
   if lag==1:assert correct==old[name,ki,tile]['test_correct']
   tr.append({'design':name,'key_index':ki,'lag':lag,'tile_id':tile,'train_pairs':S-lag,'test_pairs':L-S-lag,'test_correct':correct})
  rows.extend(tr)
  summaries.append({'design':name,'key_index':ki,'lag':lag,'mean_test_percent':100*sum(r['test_correct'] for r in tr)/(N*N*(L-S-lag)),'max_test_percent':100*max(r['test_correct'] for r in tr)/(L-S-lag)})
 print(name,ki,flush=True)
start=time.time();cr=np.random.default_rng(20271014)
for ki,pair in enumerate(CFG['key_nonce_pairs']):
 key=bytes.fromhex(pair['key']);nonce=bytes.fromhex(pair['nonce']);words=struct.unpack('<11I',key+nonce)
 for name,B in q.plane_streams(key,nonce).items():score(B,ki,name)
 mixed=0
 for word in words:mixed=q.xs((mixed+((word<<32)|(word^0x9e3779b9)))&q.MASK)
 seeds=[q.xs(mixed^((q.GOLD*(tile+1))&q.MASK)) or q.GOLD for tile in range(N*N)]
 for mode,name in [(0,'xs64_local'),(1,'xs64_stride8_software')]:score(gen(seeds,mode),ki,name)
 score(cr.integers(0,256,(N,N,L),dtype=np.uint8),ki,'uniform_control')
 score(genlog(words),ki,'logistic_local')
 seeds=[tent.seed(words,tile) for tile in range(N*N)]
 for mode,name in [(2,'tent2023_low8'),(3,'tent2023_middle8'),(4,'tent2023_stride4')]:score(gen(seeds,mode),ki,name)
aggregate=[]
for design in dict.fromkeys(s['design'] for s in summaries):
 for lag in [1,4]:
  ss=[s for s in summaries if s['design']==design and s['lag']==lag]
  aggregate.append({'design':design,'lag':lag,'mean_test_percent':sum(s['mean_test_percent'] for s in ss)/4,'max_test_percent':max(s['max_test_percent'] for s in ss)})
files=[Path(__file__),P/'run_quality.py',P/'generate_fast.cpp',P/'check_adapter_rank.py',P.parents[1]/'src/quality/heldout/config.json']
out={'configuration':{'N':N,'L':L,'split':S,'lags':[1,4],'train_pairs':{'1':S-1,'4':S-4},'test_pairs':{'1':L-S-1,'4':L-S-4},'key_nonce_pairs':CFG['key_nonce_pairs']},'elapsed_seconds':time.time()-start,'validated_stream_bytes':sum(r['bytes_checked'] for r in validated),'lag1_per_tile_outcomes_reproduced':4*N*N*11,'source_sha256':{str(p.relative_to(P.parents[1])):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'validated_streams':validated,'aggregate':aggregate,'summaries':summaries,'outcomes':rows}
(P/'lag4_results.json').write_text(json.dumps(out,indent=2)+'\n')
with (P/'lag4_aggregate.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(aggregate[0]));w.writeheader();w.writerows(aggregate)
print(json.dumps(aggregate,indent=2))
print('DONE',round(time.time()-start,2),'seconds',out['validated_stream_bytes'],'fullbyteschecked')
