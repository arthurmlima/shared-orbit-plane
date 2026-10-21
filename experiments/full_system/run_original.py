#!/usr/bin/env python3
"""Rebuild and functionally check plane/Trivium/ChaCha/no-generator meshes.

Plane EXT0..3 is selected with --ext. Mesh sizes 3, 4 and 6 use the
120x120 configuration. All results are regenerated with locally compiled firmware;
exact cycle identity depends on compiler/firmware identity.
"""
import argparse
from common import add_arguments, run

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variant', choices=('plane', 'trivium', 'chacha', 'none'))
    add_arguments(parser)
    parser.add_argument('--ext', type=int, choices=range(4), default=0)
    args = parser.parse_args()
    run(args.variant, args.n, args.ext, args.work_dir, args.inputs_dir,
        args.skip_build, args.keep_traces)
