#!/usr/bin/env python3
"""Collect regenerated routed reports as JSON/CSV, including shared/private savings."""
import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'src'


def main():
    out = ROOT / 'build/metrics'
    out.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('routed_collector', BASE / 'tools/collect.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    records = []
    for path in sorted(ROOT.glob('**/fpga/ooc_*')):
        if path.is_dir():
            row = module.routed(path)
            row['report_directory'] = str(path.relative_to(ROOT))
            records.append(row)
    (out / 'all_routed.json').write_text(json.dumps(records, indent=2) + '\n')
    by_tag = {r['tag']: r for r in records if r.get('status') == 'complete'}
    rows = []
    for n in (3, 4, 6, 8):
        for ext in range(4):
            sh = by_tag.get(f'levelB_N{n}_ext{ext}_shared_70')
            pr = by_tag.get(f'levelB_N{n}_ext{ext}_private_70')
            if sh and pr:
                a, b = sh['routed']['LUT'], pr['routed']['LUT']
                rows.append({'N': n, 'extractor': ext, 'shared_LUT': a, 'private_LUT': b,
                             'saved_percent': 100 * (b - a) / b})
    with (out / 'subsystem_savings.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['N', 'extractor', 'shared_LUT', 'private_LUT', 'saved_percent'])
        writer.writeheader()
        writer.writerows(rows)
    subprocess.run([sys.executable, str(ROOT / 'experiments/collect_comparisons.py'), '--outdir', str(out)], check=True)
    print(f'Collected {len(records)} routed reports into {out}; incomplete work remains explicit.')


if __name__ == '__main__':
    main()
