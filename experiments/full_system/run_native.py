#!/usr/bin/env python3
"""Build and check native-control full meshes against their own byte models."""
import argparse
from common import add_arguments, run

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variant', choices=('xs64', 'local_logistic', 'tent_stride4'))
    add_arguments(parser)
    args = parser.parse_args()
    run(args.variant, args.n, 0, args.work_dir, args.inputs_dir,
        args.skip_build, args.keep_traces)
