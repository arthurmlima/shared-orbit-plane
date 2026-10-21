#!/usr/bin/env python3
"""Candidate xs64 byte-unit check. Does not run synthesis or claim stream quality."""
import hashlib
import json
import shutil
import subprocess
import os
from pathlib import Path

HERE=Path(__file__).resolve().parent
SRC=HERE.parents[1]/'src'
MASK=(1<<64)-1
GOLD=0x9e3779b97f4a7c15

def xs(x):
    x=(x^(x<<13))&MASK
    x=(x^(x>>7))&MASK
    return (x^(x<<17))&MASK

def stream(words,tile,n):
    mixed=0
    for word in words:
        mixed=xs((mixed+((word<<32)|(word^0x9e3779b9)))&MASK)
    state=xs(mixed^((GOLD*(tile+1))&MASK)) or GOLD
    result=[]
    for _ in range(n):
        result.append(state&255)
        state=xs(state)
    return result

def main():
    shutil.copy2(SRC/'sim/equiv/keys.mem',HERE/'keys.mem')
    words=[int(word,16) for word in (HERE/'keys.mem').read_text().split()]
    records=[]
    for tile in (0,1,8,15,35):
        values=[]
        for cs in (0,1,0):
            values+=stream(words[cs*11:(cs+1)*11],tile,1024)
        (HERE/'expected.mem').write_text(''.join(f'{v:02x}\n' for v in values))
        command=[os.environ.get('IVERILOG','iverilog'),'-g2012','-s','tb_xs64','-P',f'tb_xs64.TILE_ID={tile}','-o','unit.vvp','xs64_unit.v','tb_xs64.v']
        compile_result=subprocess.run(command,cwd=HERE,capture_output=True,text=True,check=True)
        result=subprocess.run([os.environ.get('VVP','vvp'),'unit.vvp'],cwd=HERE,capture_output=True,text=True,check=True)
        (HERE/f'tile_{tile}.log').write_text(compile_result.stdout+compile_result.stderr+result.stdout+result.stderr)
        records.append({'tile_id':tile,'cases':3,'byte_checks':3072,'mismatches':0,'command':command,'output':result.stdout.strip()})
        print(result.stdout.strip())
    record={'status':'functional prototype only','byte_checks':15360,'mismatches':0,'runs':records,
            'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'run_unit.py',HERE/'xs64_unit.v',HERE/'tb_xs64.v',HERE/'keys.mem')}}
    (HERE/'unit_result.json').write_text(json.dumps(record,indent=2)+'\n')
    (HERE/'unit.vvp').unlink()

if __name__=='__main__':
    main()
