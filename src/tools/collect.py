#!/usr/bin/env python3
"""Collect Vivado reports of the v2 flow into JSON (never edited by hand).
usage: collect.py routed <ooc_dir>...            -> JSON on stdout, one entry per tag
       collect.py profiles <profiles_dir> N      -> per-profile metrics and the shared (mode 3) / private aggregates
"""
import json, re, sys
from pathlib import Path

ROW = re.compile(r'^\|\s*(.+?)\s*\|\s*([0-9.]+)\s*\|')

def util_table(path):
    """Top-level utilization rows: name -> used (first table occurrence of each name)."""
    out = {}
    for line in Path(path).read_text().splitlines():
        m = ROW.match(line)
        if m:
            name = m.group(1).strip()
            if name not in out:
                try: out[name] = float(m.group(2)) if '.' in m.group(2) else int(m.group(2))
                except ValueError: pass
    return out

def util_metrics(path):
    t = util_table(path)
    g = lambda *names: next((t[n] for n in names if n in t), None)
    return {'LUT': g('CLB LUTs'), 'LUT_logic': g('LUT as Logic'), 'LUT_memory': g('LUT as Memory'),
            'FF': g('CLB Registers'), 'BRAM_tiles': g('Block RAM Tile'), 'DSP': g('DSPs'), 'URAM': g('URAM')}

def hier_rows(path):
    rows = []
    for line in Path(path).read_text().splitlines():
        if not line.startswith('|') or 'Instance' in line: continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 10: continue
        inst, mod = cells[0], cells[1]
        try: vals = [int(c) for c in cells[2:9]]
        except ValueError: continue
        depth = (len(line) - len(line.lstrip('| '))) // 2
        rows.append({'instance': inst, 'module': re.sub(r'(__parameterized\d+)?(_\d+)?$', '', mod.strip('()')), 'depth': depth,
                     'LUT': vals[0], 'LUT_logic': vals[1], 'LUTRAM': vals[2], 'SRL': vals[3], 'FF': vals[4], 'RAMB36': vals[5], 'RAMB18': vals[6]})
    return rows

def attribution(path, modules=('lbe_dist', 'trivium_unit', 'ks_unit2', 'ppu_stream', 'picorv32', 'router', 'pixel_memory', 'matched_tile', 'tile', 'mpriscv')):
    """Sum of each module's rows that are not nested inside another row of the same module (no double counting).
    Rows are in depth-first order; the ancestor chain is rebuilt from the indentation depth."""
    rows = hier_rows(path)
    out = {m: {'count': 0, 'LUT': 0, 'LUT_logic': 0, 'LUTRAM': 0, 'FF': 0, 'RAMB36': 0} for m in modules}
    anc = []                                   # anc[i] = module of the ancestor at depth i + 1
    for r in rows:
        d = r['depth']
        anc = anc[:d - 1]
        if not r['instance'].startswith('('):   # "(self)" rows are not instances
            for m in modules:
                if r['module'] == m and m not in anc:
                    o = out[m]; o['count'] += 1
                    for k in ('LUT', 'LUT_logic', 'LUTRAM', 'FF', 'RAMB36'): o[k] += r[k]
        anc = anc + [r['module']]
    return {m: v for m, v in out.items() if v['count']}

def timing_summary(path):
    lines = Path(path).read_text().splitlines()
    for i, l in enumerate(lines):
        if l.strip().startswith('WNS(ns)') and i + 2 < len(lines):
            f = lines[i + 2].split()
            if len(f) >= 12:
                return {'WNS': float(f[0]), 'TNS': float(f[1]), 'setup_failing': int(f[2]), 'WHS': float(f[4]), 'hold_failing': int(f[6]), 'WPWS': float(f[8]), 'pw_failing': int(f[10])}
    return None

def power(path):
    t = util_table(path)
    txt = Path(path).read_text()
    conf = re.search(r'\|\s*Confidence Level\s*\|\s*(\w+)', txt)
    act = re.search(r'\|\s*Simulation Activity File\s*\|\s*(\S+)', txt)
    return {'dynamic_W': t.get('Dynamic (W)'), 'static_W': t.get('Device Static (W)'), 'total_W': t.get('Total On-Chip Power (W)'),
            'confidence': conf.group(1) if conf else None, 'activity_file': act.group(1) if act else None}

def fmax(path):
    s = Path(path).read_text().strip()
    d = dict(re.findall(r'(\w+) (\S+)', s.split(' generics')[0]))
    gen = re.search(r'generics \{(.*)\}', s)
    d['generics'] = gen.group(1) if gen else None
    for k in ('target_MHz', 'period_ns', 'WNS_ns', 'Fmax_MHz', 'ks_unit_slack_ns', 'plane_wire_slack_ns', 'synth_s', 'impl_s'):
        if k in d:
            try: d[k] = float(d[k])
            except ValueError: pass
    return d

def routed(d):
    d = Path(d); tag = d.name[4:]
    r = {'tag': tag}
    f = d / f'fmax_{tag}.txt'
    if not f.exists(): r['status'] = 'incomplete'; return r
    r.update(fmax(f))
    r['routed'] = util_metrics(d / f'util_{tag}.txt')
    r['post_synth'] = util_metrics(d / f'util_synth_{tag}.txt')
    if (d / f'util_opt_{tag}.txt').exists(): r['post_opt'] = util_metrics(d / f'util_opt_{tag}.txt')
    r['timing'] = timing_summary(d / f'timing_{tag}.txt')
    r['timing_met'] = bool(r['timing'] and r['timing']['WNS'] >= 0 and r['timing']['WHS'] >= 0 and r['timing']['WPWS'] >= 0)
    r['power'] = power(d / f'power_{tag}.txt')
    r['attribution'] = attribution(d / f'util_hier_{tag}.txt')
    r['status'] = 'complete'
    return r

def profiles(d, N):
    d = Path(d)
    names = [l.split()[0] for l in (d / 'profiles.txt').read_text().splitlines()]
    prof = {n: {'post_synth': util_metrics(d / f'util_synth_{n}.txt'), 'post_opt': util_metrics(d / f'util_opt_{n}.txt')} for n in names}
    def mult(private):
        m = {'control': 1}
        for y in range(N):
            for x in range(N):
                rs = private or x == y; cs = private or y == x
                r, c = 2 * y, 2 * x + 1
                n = f'dual_r{r}_c{c}' if rs and cs else f'row{r}' if rs else f'col{c}' if cs else 'pair'
                m[n] = m.get(n, 0) + 1
        return m
    def agg(m, stage):
        tot = {}
        for n, k in m.items():
            for key, v in prof[n][stage].items():
                if v is not None: tot[key] = tot.get(key, 0) + k * v
        return tot
    out = {'N': N, 'profiles': prof}
    for stage in ('post_synth', 'post_opt'):
        pr, sh = agg(mult(True), stage), agg(mult(False), stage)
        out[stage] = {'private': pr, 'shared_mode3': sh, 'multiplicity_private': mult(True), 'multiplicity_shared': mult(False),
                      'saving_percent': {k: (100 * (pr[k] - sh[k]) / pr[k] if pr.get(k) else None) for k in pr}}
    return out

if __name__ == '__main__':
    if sys.argv[1] == 'routed':
        print(json.dumps({routed(x)['tag']: routed(x) for x in sys.argv[2:]}, indent=1))
    elif sys.argv[1] == 'profiles':
        print(json.dumps(profiles(sys.argv[2], int(sys.argv[3])), indent=1))
