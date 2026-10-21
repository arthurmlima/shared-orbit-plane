#!/usr/bin/env python3
"""Independent full strided-stream check against recorded quality-run hashes."""
from pathlib import Path
import hashlib,importlib.util,json,struct
import numpy as np
P=Path(__file__).resolve().parent
r=json.loads((P/'results.json').read_text())
ref=P/'nardo2023/strided/tent_ref.py'
spec=importlib.util.spec_from_file_location('strided_ref_validate',ref);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
words=[struct.unpack('<11I',bytes.fromhex(pair['key'])+bytes.fromhex(pair['nonce'])) for pair in r['configuration']['key_nonce_pairs']]
state=np.array([m.seed(w,tile) for w in words for tile in range(36)],dtype=np.uint64)
L=r['configuration']['L']; data=np.empty((144,L),np.uint8)
mask=np.uint64(0xffffffff)
for t in range(L):
    byte=np.zeros(144,np.uint64)
    for bit in [30,26,22,18,14,10,6,2]:byte=(byte<<np.uint64(1))|((state>>np.uint64(bit))&np.uint64(1))
    data[:,t]=byte
    # Alternative direct complement/shift expression from the published diagram.
    complement=state^np.where((state>>np.uint64(31))!=0,mask,np.uint64(0))
    state=((complement<<np.uint64(1))&mask)|(((state>>np.uint64(1))^state)&np.uint64(1))
common_delta_checks=0
for ki in range(1,4):
    delta=data[ki*36:(ki+1)*36]^data[:36]
    assert np.all(delta==delta[0][None,:])
    common_delta_checks+=36*L
recorded={(s['design'],s['key_index']):s['sha256_tile_major'] for s in r['stream_hashes']}
checks=[]
for ki in range(4):
    B=data[ki*36:(ki+1)*36]
    hashed=hashlib.sha256(B.tobytes()).hexdigest()
    assert hashed==recorded['tent2023_stride4',ki]
    for tile in range(36):assert np.array_equal(B[tile,:1024],np.frombuffer(m.stream(words[ki],tile,1024),dtype=np.uint8))
    checks.append({'key_index':ki,'bytes_checked':36*L,'sha256_tile_major':hashed})
files=[Path(__file__),P/'run_quality.py',P.parents[1]/'src/quality/heldout/config.json',ref,P/'nardo2023/strided/tent_unit.v']
manifest={'status':'pass','tent32_common_key_delta_byte_checks':common_delta_checks,'independent_vectorized_full_stream_bytes_checked':144*L,'scalar_strided_reference_bytes_checked':144*1024,'stream_hash_checks':checks,'source_sha256':{str(f.relative_to(P.parents[1])):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}
(P/'validation_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
