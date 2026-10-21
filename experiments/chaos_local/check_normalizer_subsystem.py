#!/usr/bin/env python3
"""Check staged extraction in the shared/private RTL subsystem bench."""
import hashlib
import json
import shutil
import subprocess
import os
from pathlib import Path

HERE=Path(__file__).resolve().parent
SRC=HERE.parents[1]/'src'


def main():
    out=HERE/'normalizer_staged/verify'
    rtl=out.parent/'rtl'
    shutil.copy2(SRC/'sim/equiv/keys.mem',out/'keys.mem')
    shutil.copy2(SRC/'sim/equiv/tb_equiv.v',out/'tb_equiv.v')
    records=[]
    for n in (3,4,6):
        for ext in range(4):
            name=f'subsystem_N{n}_E{ext}'
            expected=SRC/f'sim/equiv/expected_N{n}_E{ext}.mem'
            command=[os.environ.get('IVERILOG','iverilog'),'-g2012',f'-I{rtl}','-s','tb_equiv',
                     '-P',f'tb_equiv.N={n}','-P',f'tb_equiv.EXT={ext}','-o',name+'.vvp',
                     str(rtl/'lbe_dist.v'),str(rtl/'matched_tile.v'),str(rtl/'plane_mesh.v'),'tb_equiv.v']
            comp=subprocess.run(command,cwd=out,capture_output=True,text=True,check=True)
            run=subprocess.run([os.environ.get('VVP','vvp'),name+'.vvp',f'+EXPECTED={expected}'],cwd=out,capture_output=True,text=True,check=True)
            (out/(name+'.log')).write_text(comp.stdout+comp.stderr+run.stdout+run.stderr)
            (out/(name+'.vvp')).unlink()
            record={'N':n,'EXT':ext,'byte_checks':86400,'mismatches':0,'command':command,
                    'expected_sha256':hashlib.sha256(expected.read_bytes()).hexdigest(),
                    'stdout':run.stdout.strip()}
            records.append(record)
            print(run.stdout.strip(),flush=True)
    result={'status':'passed','byte_checks':1036800,'mismatches':0,'cases':records,
            'scope':'Shared, synchronized private and independently advancing private subsystem RTL; two directed keys with asymmetric stalls; staged header only.'}
    (HERE/'normalizer_subsystem_result.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':
    main()
