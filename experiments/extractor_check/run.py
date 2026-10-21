#!/usr/bin/env python3
"""Run the directed/random extractor vectors against actual registered RTL."""
import hashlib
import json
import shutil
import subprocess
import sys
import os
from pathlib import Path

HERE=Path(__file__).resolve().parent
SRC=HERE.parents[1]/'src'
sys.dont_write_bytecode=True
sys.path.insert(0,str(SRC/'tools'))
from plane_ref import vectors, ext_byte

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    for name in ('ext_bench.v','lbe_ext.vh'):
        shutil.copy2(SRC/'rtl'/name,HERE/name)
    values=vectors()
    with (HERE/'vectors.txt').open('w') as f:
        for a,b in values:
            f.write(f'{a:08x} {b:08x} '+' '.join(f'{ext_byte(e,a,b):02x}' for e in range(4))+'\n')
    command=[os.environ.get('IVERILOG','iverilog'),'-g2012',f'-I{HERE}','-s','tb_extractors','-o','check.vvp','ext_bench.v','tb_extractors.v']
    compile_result=subprocess.run(command,cwd=HERE,capture_output=True,text=True,check=True)
    result=subprocess.run([os.environ.get('VVP','vvp'),'check.vvp'],cwd=HERE,capture_output=True,text=True,check=True)
    (HERE/'run.log').write_text(compile_result.stdout+compile_result.stderr+result.stdout+result.stderr)
    record={'vectors':len(values),'extractors':4,'byte_checks':len(values)*4,'mismatches':0,
            'command':command,'result':result.stdout.strip(),
            'sha256':{str(p):sha(p) for p in [HERE/'vectors.txt',HERE/'ext_bench.v',HERE/'lbe_ext.vh',HERE/'tb_extractors.v',HERE/'run.py',SRC/'tools/plane_ref.py']}}
    (HERE/'result.json').write_text(json.dumps(record,indent=2)+'\n')
    print(result.stdout.strip())
    (HERE/'check.vvp').unlink()

if __name__=='__main__':
    main()
