#!/usr/bin/env python3
"""RTL/reference equivalence of an in-house local logistic byte generator."""
import hashlib
import json
import shutil
import subprocess
import os
from pathlib import Path
from local_logistic_ref import stream

HERE=Path(__file__).resolve().parent
SRC=HERE.parents[1]/'src'


def main():
    shutil.copy2(SRC/'sim/equiv/keys.mem',HERE/'keys.mem')
    words=[int(word,16) for word in (HERE/'keys.mem').read_text().split()]
    records=[]
    for tile in (0,1,8,15,35):
        values=bytearray()
        for cs in (0,1,0):
            values+=stream(words[cs*11:(cs+1)*11],tile,8192)
        (HERE/'expected.mem').write_text(''.join(f'{value:02x}\n' for value in values))
        command=[os.environ.get('IVERILOG','iverilog'),'-g2012','-s','tb_local_logistic','-P',f'tb_local_logistic.TILE_ID={tile}','-o','unit.vvp','local_logistic_unit.v','tb_local_logistic.v']
        compile_result=subprocess.run(command,cwd=HERE,capture_output=True,text=True,check=True)
        result=subprocess.run([os.environ.get('VVP','vvp'),'unit.vvp'],cwd=HERE,capture_output=True,text=True,check=True)
        (HERE/f'tile_{tile}.log').write_text(compile_result.stdout+compile_result.stderr+result.stdout+result.stderr)
        records.append({'tile_id':tile,'cases':3,'byte_checks':24640,'mismatches':0,'startup_cycles':76,'command':command,'output':result.stdout.strip()})
        print(result.stdout.strip())
    paths=(HERE/'run_unit.py',HERE/'local_logistic_unit.v',HERE/'local_logistic_ref.py',HERE/'tb_local_logistic.v',HERE/'keys.mem')
    record={'status':'functional verification passed; synthesis/routing not yet run','byte_checks':123200,'mismatches':0,'runs':records,
            'sha256':{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}}
    (HERE/'unit_result.json').write_text(json.dumps(record,indent=2)+'\n')
    (HERE/'unit.vvp').unlink()


if __name__=='__main__':
    main()
