#!/usr/bin/env python3
"""Prepare staged-A complete-mesh inputs using only files in this distribution."""
import argparse
from common import prepare

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir')
    parser.add_argument('--inputs-dir')
    parser.add_argument('--no-inputs', action='store_true', help='Copy source only; skip input generation')
    args = parser.parse_args()
    work, inputs = prepare('staged', args.work_dir, args.inputs_dir, not args.no_inputs)
    print(f'Prepared sources: {work}; generated inputs: {inputs}')
