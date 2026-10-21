#!/usr/bin/env python3
"""Build and check staged-A full meshes with locally compiled firmware inputs."""
import argparse
from common import add_arguments, run

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument('--ext', type=int, choices=range(4), default=0)
    args = parser.parse_args()
    run('staged', args.n, args.ext, args.work_dir, args.inputs_dir,
        args.skip_build, args.keep_traces)
