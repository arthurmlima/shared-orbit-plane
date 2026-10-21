#!/usr/bin/env python3
"""Prepare a native-control full mesh using its exact local routed-source RTL."""
import argparse
from pathlib import Path
from common import prepare, ROOT

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variant', nargs='?', choices=('xs64', 'local_logistic', 'tent_stride4'))
    parser.add_argument('--work-dir', type=Path, help='Parent of variant output directories')
    parser.add_argument('--inputs-dir', type=Path)
    parser.add_argument('--no-inputs', action='store_true')
    args = parser.parse_args()
    for variant in ([args.variant] if args.variant else ['xs64', 'local_logistic', 'tent_stride4']):
        work, inputs = prepare(variant, (args.work_dir or ROOT/'build/full_system')/variant,
                               args.inputs_dir, not args.no_inputs)
        print(f'Prepared {variant}: {work}; generated inputs: {inputs}')
