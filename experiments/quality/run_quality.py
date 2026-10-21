#!/usr/bin/env python3
"""Matched held-out rectangle predictor and bounded simultaneous-stimulus coverage.

No random-stream independence or security claim is inferred from these tests.
The four-bit consumer uses bit 7 of four simultaneous rectangle-corner bytes.
Each possible four-bit value is one of 16 four-requestor enable masks. The explicit coverage
requirement is all 16 minterms at each rectangle during the held-out half only.
This is a software reference experiment, not a processor/FPGA application run.
"""
from pathlib import Path
import ctypes, csv, hashlib, importlib.util, itertools, json, os, platform, shutil, struct, subprocess, sys, time
import numpy as np
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SRC=ROOT/'src'
OLD=SRC/'quality/heldout'
N=6; L=125000; SPLIT=62500; T=64
MASK=(1<<64)-1; GOLD=0x9e3779b97f4a7c15
RECTS=list(itertools.product(itertools.combinations(range(N),2),repeat=2))

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def xs(x):
    x=(x^(x<<13))&MASK; x=(x^(x>>7))&MASK
    return (x^(x<<17))&MASK

def xs_streams(key,nonce,adapter='low8'):
    # Exact seed and no warmup, matching the unit-test reference and RTL.
    words=struct.unpack('<11I',key+nonce)
    mix=0
    for word in words: mix=xs((mix+((word<<32)|(word^0x9e3779b9)))&MASK)
    state=np.array([xs(mix^((GOLD*(i+1))&MASK)) or GOLD for i in range(N*N)],dtype=np.uint64)
    out=np.empty((N*N,L),np.uint8)
    for t in range(L):
        if adapter=='low8': out[:,t]=state&np.uint64(255)
        elif adapter=='stride8':
            byte=np.zeros(N*N,np.uint64)
            for bit in [56,48,40,32,24,16,8,0]:byte=(byte<<np.uint64(1))|((state>>np.uint64(bit))&np.uint64(1))
            out[:,t]=byte
        else: raise ValueError(adapter)
        state^=state<<np.uint64(13); state^=state>>np.uint64(7); state^=state<<np.uint64(17)
    return out.reshape(N,N,L)

def plane_streams(key,nonce):
    sys.path.insert(0,str(SRC/'tools'))
    import plane_ref
    R=np.empty((L,N),np.int64); C=np.empty_like(R)
    for t,(rows,cols) in enumerate(plane_ref.ref.plane_iter(key,nonce,N,L+T,6,8)):
        if t>=T: R[t-T]=rows; C[t-T]=cols
    D=np.abs(R[:,:,None]-C[:,None,:])
    bl=np.where(D>0,np.floor(np.log2(np.maximum(D,1))).astype(np.int64)+1,0)
    norm=np.where(D>0,D<<np.maximum(32-bl,0),0)
    streams={'fold':(((norm>>15)^(norm>>23))&255).astype(np.uint8),
             'window':((D>>8)&255).astype(np.uint8),
             'xor':(((R[:,:,None]^C[:,None,:])>>8)&255).astype(np.uint8),
             'nwin':((norm>>15)&255).astype(np.uint8)}
    for t in [0,1,63,62499,62500,124999]:
        for y,x,e in itertools.product(range(N),range(N),range(4)):
            assert streams[list(streams)[e]][t,y,x]==plane_ref.ext_byte(e,int(R[t,y]),int(C[t,x]))
    return {k:np.ascontiguousarray(v.transpose(1,2,0)) for k,v in streams.items()}

def main():
    began=time.time()
    cfg=json.loads((OLD/'config.json').read_text())
    shutil.copy2(OLD/'predict.cpp',HERE/'predict.cpp')
    subprocess.run([os.environ.get('CXX','g++'),'-O3','-shared','-fPIC','predict.cpp','-o','predict.so'],cwd=HERE,check=True)
    lib=ctypes.CDLL(str(HERE/'predict.so')); ptr=ctypes.POINTER(ctypes.c_uint8)
    lib.evaluate.argtypes=[ptr]*4+[ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_int)]
    outcomes=[]; summaries=[]; coverage=[]; histograms=[]; exact_hashes=[]; xs_sequences=[]; xs_seed_nonzero=[]; temporal=[]
    def score(B,ki,name):
        assert B.shape==(N,N,L) and B.dtype==np.uint8
        hist=np.stack([np.bincount(s,minlength=256) for s in B.reshape(N*N,L)])
        chi=((hist-L/256)**2/(L/256)).sum(axis=1)
        rowout=[]; rowcov=[]; rowtemp=[]
        for tile,seq in enumerate(B.reshape(N*N,L)):
            a=seq[:SPLIT-1].astype(np.int64); b=seq[1:SPLIT].astype(np.int64)
            counts=np.bincount(a*256+b,minlength=65536).reshape(256,256)
            best=counts.argmax(axis=1).astype(np.uint8)
            correct=int(np.count_nonzero(best[seq[SPLIT:-1]]==seq[SPLIT+1:]))
            constant=int(np.bincount(seq[:SPLIT],minlength=256).argmax())
            cr=int(np.count_nonzero(seq[SPLIT+1:]==constant))
            rowtemp.append({'design':name,'key_index':ki,'tile_id':tile,'test_pairs':L-SPLIT-1,'test_correct':correct,'constant_test_correct':cr})
        temporal.extend(rowtemp)
        for (y,y2),(x,x2) in RECTS:
            vals=[np.ascontiguousarray(B[yy,xx]) for yy,xx in [(y,x),(y,x2),(y2,x),(y2,x2)]]
            out=(ctypes.c_int*3)()
            lib.evaluate(*(v.ctypes.data_as(ptr) for v in vals),L,SPLIT,out)
            o={'design':name,'key_index':ki,'rectangle':[y,y2,x,x2],'predictor_index':int(out[0]),'train_correct':int(out[1]),'test_correct':int(out[2])}
            rowout.append(o)
            # Four requestors use the MSB of their four corner bytes as enable bits.
            # First corner is bit 3, then top-right bit 2,bottom-left bit1,bottom-right bit0.
            patterns=((vals[0][SPLIT:]>>7)<<3)|((vals[1][SPLIT:]>>7)<<2)|((vals[2][SPLIT:]>>7)<<1)|(vals[3][SPLIT:]>>7)
            counts=np.bincount(patterns,minlength=16)
            tv=float(np.abs(counts/SPLIT-1/16).sum()/2)
            c={'design':name,'key_index':ki,'rectangle':[y,y2,x,x2],'patterns_seen':int((counts>0).sum()),'total_variation_from_uniform16':tv,'counts':counts.tolist()}
            rowcov.append(c)
        outcomes.extend(rowout); coverage.extend(rowcov)
        summaries.append({'design':name,'key_index':ki,
                         'mean_test_percent':100*sum(o['test_correct'] for o in rowout)/(len(RECTS)*SPLIT),
                         'worst_test_percent':100*max(o['test_correct'] for o in rowout)/SPLIT,
                         'rectangle_patterns_min':min(c['patterns_seen'] for c in rowcov),
                         'rectangles_meeting_all16':sum(c['patterns_seen']==16 for c in rowcov),
                         'mean_TV16':float(np.mean([c['total_variation_from_uniform16'] for c in rowcov])),
                         'max_TV16':max(c['total_variation_from_uniform16'] for c in rowcov),
                         'chi2_255_mean':float(chi.mean()),'chi2_255_max':float(chi.max()),'temporal_mean_test_percent':100*sum(o['test_correct'] for o in rowtemp)/(N*N*(L-SPLIT-1)),'temporal_worst_test_percent':100*max(o['test_correct'] for o in rowtemp)/(L-SPLIT-1),'constant_mean_test_percent':100*sum(o['constant_test_correct'] for o in rowtemp)/(N*N*(L-SPLIT-1))})
        exact_hashes.append({'design':name,'key_index':ki,'shape':[N,N,L],'dtype':'uint8','sha256_tile_major':hashlib.sha256(B.tobytes()).hexdigest()})
        print(name,ki,summaries[-1],flush=True)
    # Regenerate every stream and predictor outcome from the fixed configuration.
    controls=np.random.default_rng(cfg['control_rng_seed'])
    for ki,pair in enumerate(cfg['key_nonce_pairs']):
        key=bytes.fromhex(pair['key']); nonce=bytes.fromhex(pair['nonce'])
        for name,B in plane_streams(key,nonce).items(): score(B,ki,name)
        xsB=xs_streams(key,nonce)
        # Independent scalar reference for vectorized generation: all36tiles,1024bytes/key.
        unit_spec=importlib.util.spec_from_file_location('xs64_unit_ref',ROOT/'experiments/xs64_baseline/run_unit.py')
        unit_module=importlib.util.module_from_spec(unit_spec); unit_spec.loader.exec_module(unit_module)
        words=struct.unpack('<11I',key+nonce)
        for tile in range(N*N):
            assert np.array_equal(xsB.reshape(N*N,L)[tile,:1024],np.array(unit_module.stream(words,tile,1024),dtype=np.uint8))
        xs_sequences.append(xsB)
        mixed=0
        for word in words: mixed=xs((mixed+((word<<32)|(word^0x9e3779b9)))&MASK)
        xs_seed_nonzero.append(all(xs(mixed^((GOLD*(tile+1))&MASK))!=0 for tile in range(N*N)))
        score(xsB,ki,'xs64_local')
        score(xs_streams(key,nonce,'stride8'),ki,'xs64_stride8_software')
        score(controls.integers(0,256,(N,N,L),dtype=np.uint8),ki,'uniform_control')
    # Local chaos extension uses the matched scalar reference.
    local_path=ROOT/'experiments/chaos_local/local_logistic_ref.py'
    if local_path.exists():
        spec=importlib.util.spec_from_file_location('local_chaos_ref',local_path)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        for ki,pair in enumerate(cfg['key_nonce_pairs']):
            words=struct.unpack('<11I',bytes.fromhex(pair['key'])+bytes.fromhex(pair['nonce']))
            B=np.array([np.frombuffer(module.stream(words,tile,L),dtype=np.uint8) for tile in range(N*N)]).reshape(N,N,L)
            score(B,ki,'logistic_local')
    # Published Nardo2023 Figure2 recurrence with explicit study-specific adapters.
    tent_path=HERE/'nardo2023/tent_ref.py'
    tent_spec=importlib.util.spec_from_file_location('tent_ref',tent_path)
    tent_module=importlib.util.module_from_spec(tent_spec);tent_spec.loader.exec_module(tent_module)
    tent_special_seeds=[]
    for ki,pair in enumerate(cfg['key_nonce_pairs']):
        words=struct.unpack('<11I',bytes.fromhex(pair['key'])+bytes.fromhex(pair['nonce']))
        B=np.array([np.frombuffer(tent_module.stream(words,tile,L),dtype=np.uint8) for tile in range(N*N)]).reshape(N,N,L)
        tent_special_seeds.append(any(tent_module.seed(words,tile) in [0,0xffffffff] for tile in range(N*N)))
        score(B,ki,'tent2023_low8')
        for adapter in ['middle8','stride4']:
            data=np.empty((N*N,L),np.uint8)
            for tile in range(N*N):
                value=tent_module.seed(words,tile)
                for t in range(L):
                    if adapter=='middle8': data[tile,t]=(value>>8)&255
                    else:
                        byte=0
                        for bit in [30,26,22,18,14,10,6,2]:byte=(byte<<1)|((value>>bit)&1)
                        data[tile,t]=byte
                    value=tent_module.step_fast(value)
            score(data.reshape(N,N,L),ki,'tent2023_'+adapter)
    # Verify the seeding limitation rather than silently treating salts as independent streams.
    # Since xs64 is GF(2)-linear, a change of key contributes the same bytewise
    # XOR difference on every tile. All tested seeds are nonzero (no fallback).
    cross_key_checks=0
    for ki in range(1,len(xs_sequences)):
        delta=xs_sequences[ki]^xs_sequences[0]
        assert np.all(delta==delta[0,0][None,None,:])
        cross_key_checks+=N*N*L
    files=[Path(__file__),HERE/'predict.cpp',OLD/'config.json',SRC/'tools/plane_ref.py',SRC/'baseline/reference_original/lbe_dist_ref.py',SRC/'baseline/reference_original/lbe_ref.py',ROOT/'experiments/xs64_baseline/xs64_unit.v',ROOT/'experiments/xs64_baseline/run_unit.py']
    if local_path.exists(): files.append(local_path)
    files.extend([tent_path,HERE/'nardo2023/tent_unit.v',HERE/'nardo2023/strided/tent_unit.v',HERE/'nardo2023/strided/tent_ref.py'])
    config={'N':N,'L':L,'split':SPLIT,'warmup_plane':T,'warmup_xs64':0,'rectangles_per_key':len(RECTS),'consumer_bit':7,'consumer_requirement':'All 16 simultaneous bit patterns from each rectangle corner during held-out half','uniform_reference':'numpy.default_rng seed 20271014, same full-shape order as seeds/uniform_protocol.json','key_nonce_pairs':cfg['key_nonce_pairs'],'python':platform.python_version(),'numpy':np.__version__,'tent2023_width':32,'tent2023_seed_adapter':'xs64 salted config mix low32,zero becomes1','tent2023_output_adapters':{'tent2023_low8':'word[7:0]','tent2023_middle8':'word[15:8]','tent2023_stride4':'concatenated word bits[30,26,22,18,14,10,6,2]'},'tent2023_advance':'once per byte,no warmup','xs64_output_adapters':{'xs64_local':'state[7:0],hardware-matched','xs64_stride8_software':'concatenated state bits[56,48,40,32,24,16,8,0],software-only ablation'},'tent2023_any_zero_or_allones_seed':any(tent_special_seeds),'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in files}}
    out={'configuration':config,'elapsed_seconds':time.time()-began,'xs64_scalar_reference_bytes_checked':4*N*N*1024,'xs64_all_seeds_nonzero':all(xs_seed_nonzero),'xs64_cross_key_common_delta_bytes_checked':cross_key_checks,'summaries':summaries,'outcomes':outcomes,'consumer_coverage':coverage,'temporal_outcomes':temporal,'stream_hashes':exact_hashes}
    (HERE/'results.json').write_text(json.dumps(out,indent=2)+'\n')
    (HERE/'summary.json').write_text(json.dumps({'configuration':config,'elapsed_seconds':time.time()-began,'xs64_scalar_reference_bytes_checked':4*N*N*1024,'xs64_all_seeds_nonzero':all(xs_seed_nonzero),'xs64_cross_key_common_delta_bytes_checked':cross_key_checks,'summaries':summaries},indent=2)+'\n')
    with (HERE/'summary.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(summaries[0]));w.writeheader();w.writerows(summaries)
    designs=list(dict.fromkeys(s['design'] for s in summaries))
    aggregate=[]
    for design in designs:
        v=[s for s in summaries if s['design']==design]
        aggregate.append({'design':design,'predictor_mean_percent':sum(s['mean_test_percent'] for s in v)/4,'predictor_mean_per_key_min':min(s['mean_test_percent'] for s in v),'predictor_mean_per_key_max':max(s['mean_test_percent'] for s in v),'predictor_worst_rectangle_percent':max(s['worst_test_percent'] for s in v),'all16_scenarios':sum(s['rectangles_meeting_all16'] for s in v),'total_scenarios':900,'minimum_masks':min(s['rectangle_patterns_min'] for s in v),'mean_TV16':sum(s['mean_TV16'] for s in v)/4,'max_TV16':max(s['max_TV16'] for s in v),'temporal_mean_test_percent':sum(s['temporal_mean_test_percent'] for s in v)/4,'temporal_worst_test_percent':max(s['temporal_worst_test_percent'] for s in v),'constant_mean_test_percent':sum(s['constant_mean_test_percent'] for s in v)/4})
    with (HERE/'aggregate.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(aggregate[0]));w.writeheader();w.writerows(aggregate)
    (HERE/'aggregate.json').write_text(json.dumps(aggregate,indent=2)+'\n')
    print('DONE',round(time.time()-began,2),'seconds',len(outcomes),'held-out predictor outcomes generated')
if __name__=='__main__': main()
