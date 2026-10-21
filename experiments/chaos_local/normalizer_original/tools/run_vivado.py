#!/usr/bin/env python3
"""Queue Vivado out-of-context jobs for the v2 flow; never overwrite a finished job.
usage: run_vivado.py JOBS.json [--parallel P]
JOBS.json: {"jobs": [{"tag": str, "freq": MHz, "generics": "K=V ...", "top": "mpriscv_axi", "outroot": "fpga"}, ...]}
Records: fpga/work/<tag>/{command,result}.json, log fpga/logs/vivado_<tag>.log, summary appended to fpga/jobs/<name>.results.json
"""
import concurrent.futures, datetime, json, os, re, subprocess, sys, time
from pathlib import Path
V = Path(__file__).resolve().parents[1]
VIVADO = os.environ.get('VIVADO', 'vivado')
FLOW = V / 'fpga' / 'impl_ooc.tcl'

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()

def run(job):
    tag = job['tag']; top = job.get('top', 'mpriscv_axi'); outroot = V / job.get('outroot', 'fpga')
    out = outroot / f'ooc_{tag}'
    if (out / f'fmax_{tag}.txt').exists():
        return {'tag': tag, 'status': 'exists', 'out': str(out)}
    work = V / 'fpga' / 'work' / tag; work.mkdir(parents=True, exist_ok=True)
    log = V / 'fpga' / 'logs' / f'vivado_{tag}.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [VIVADO, '-mode', 'batch', '-nojournal', '-nolog', '-source', str(FLOW), '-tclargs', tag, str(job['freq']), job['generics'], top, str(outroot)]
    rec = {'tag': tag, 'command': cmd, 'started_utc': now(), 'flow_sha256': __import__('hashlib').sha256(FLOW.read_bytes()).hexdigest()}
    (work / 'command.json').write_text(json.dumps(rec, indent=2) + '\n')
    t0 = time.monotonic()
    with log.open('w') as f:
        p = subprocess.run(cmd, cwd=work, stdout=f, stderr=subprocess.STDOUT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    rec.update(returncode=p.returncode, elapsed_seconds=round(time.monotonic() - t0, 1), finished_utc=now(), log=str(log))
    fm = out / f'fmax_{tag}.txt'
    rec['fmax_line'] = fm.read_text().strip() if fm.exists() else None
    rec['status'] = 'complete' if p.returncode == 0 and fm.exists() else 'failed'
    (work / 'result.json').write_text(json.dumps(rec, indent=2) + '\n')
    return rec

def main():
    jobs_file = Path(sys.argv[1]); par = int(sys.argv[sys.argv.index('--parallel') + 1]) if '--parallel' in sys.argv else 2
    jobs = json.loads(jobs_file.read_text())['jobs']
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=par) as pool:
        for r in pool.map(run, jobs):
            results.append(r); print(json.dumps({k: r.get(k) for k in ['tag', 'status', 'elapsed_seconds', 'fmax_line']}), flush=True)
            jobs_file.with_suffix('.results.json').write_text(json.dumps(results, indent=2) + '\n')
    return 0 if all(r['status'] in ('complete', 'exists') for r in results) else 1

if __name__ == '__main__': sys.exit(main())
