#!/usr/bin/env python3
"""Exact GF(2) projection ranks; no empirical independence claim."""
from pathlib import Path
import importlib.util,json
P=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('tent_rank_ref',P/'nardo2023/tent_ref.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
M64=(1<<64)-1

def xs(x):
 x=(x^(x<<13))&M64;x=(x^(x>>7))&M64;return (x^(x<<17))&M64

def rank(columns):
 piv={}
 for v in columns:
  while v:
   b=v.bit_length()-1
   if b in piv:v^=piv[b]
   else:piv[b]=v;break
 return len(piv)

def project(x,bits):
 y=0
 for b in bits:y=(y<<1)|((x>>b)&1)
 return y

rows=[]
for name,width,step,bits in [('xs64_low8',64,xs,list(range(7,-1,-1))),('xs64_stride8_software',64,xs,[56,48,40,32,24,16,8,0]),('tent32_low8',32,m.step_fast,list(range(7,-1,-1))),('tent32_middle8',32,m.step_fast,list(range(15,7,-1))),('tent32_stride4',32,m.step_fast,[30,26,22,18,14,10,6,2])]:
 # Use states after a native step, so the tent's stable rank31 subspace is respected.
 old=[step(1<<j) for j in range(width)]
 a=[project(x,bits) for x in old]
 one={'name':name,'bits_msb_first':bits,'stable_single_output_rank':rank(a),'joint_rank_by_lag':{}}
 for lag in range(1,9):
  nxt=old[:]
  for _ in range(lag):nxt=[step(x) for x in nxt]
  one['joint_rank_by_lag'][str(lag)]=rank([(v<<8)|project(x,bits) for v,x in zip(a,nxt)])
 rows.append(one)
(P/'adapter_rank.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))
