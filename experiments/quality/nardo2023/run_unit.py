#!/usr/bin/env python3
"""Nardo2023 clean-room byte-unit check; does not run synthesis or claim stream quality."""
import hashlib
import json
import shutil
import subprocess
import os
from pathlib import Path

HERE=Path(__file__).resolve().parent
SRC=HERE.parents[2]/'src'
from tent_ref import stream, step, step_fast

def main():
    import random
    directed=[0,1,2,3,0xffffffff,0x80000000,0x7fffffff]+[1<<b for b in range(32)]
    rng=random.Random(20271020)
    for value in directed+[rng.getrandbits(32) for _ in range(100000)]:
        assert step(value)==step_fast(value)
    shutil.copy2(SRC/'sim/equiv/keys.mem',HERE/'keys.mem')
    words=[int(word,16) for word in (HERE/'keys.mem').read_text().split()]
    records=[]
    for tile in (0,1,8,15,35):
        values=[]
        for cs in (0,1,0):
            values+=stream(words[cs*11:(cs+1)*11],tile,1024)
        (HERE/'expected.mem').write_text(''.join(f'{v:02x}\n' for v in values))
        command=[os.environ.get('IVERILOG','iverilog'),'-g2012','-s','tb_tent','-P',f'tb_tent.TILE_ID={tile}','-o','unit.vvp','tent_unit.v','tb_tent.v']
        compile_result=subprocess.run(command,cwd=HERE,capture_output=True,text=True,check=True)
        result=subprocess.run([os.environ.get('VVP','vvp'),'unit.vvp'],cwd=HERE,capture_output=True,text=True,check=True)
        (HERE/f'tile_{tile}.log').write_text(compile_result.stdout+compile_result.stderr+result.stdout+result.stderr)
        records.append({'tile_id':tile,'cases':3,'byte_checks':3072,'mismatches':0,'command':command,'output':result.stdout.strip()})
        print(result.stdout.strip())
    record={'bit_index_transition_checks':100039,'bit_index_transition_mismatches':0,'published_recurrence':'Nardo et al.2023 Figure2 K32; own seed+lowbyte adapters','status':'functional prototype only','byte_checks':15360,'mismatches':0,'runs':records,
            'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'run_unit.py',HERE/'tent_unit.v',HERE/'tb_tent.v',HERE/'keys.mem',HERE/'tent_ref.py')}}
    (HERE/'unit_result.json').write_text(json.dumps(record,indent=2)+'\n')
    (HERE/'unit.vvp').unlink()

if __name__=='__main__':
    main()
