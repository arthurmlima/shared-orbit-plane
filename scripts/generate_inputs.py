#!/usr/bin/env python3
"""Generate the image input from scikit-image's public-domain camera fixture.

This preserves the original make_image.py resize, rounding and text formatting.
The image is input data, not a generated simulation trace. No image pixels are
embedded in this source-only distribution.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_120_SHA256 = '442b34f1fc5a89a5aac39012eb6971bdcf14b8fe1f0b7e326af6a46f764f2661'
EXPECTED_120_BYTES = 52615


def generate(out, width=120, height=120):
    try:
        import numpy as np
        import skimage
        import scipy
        from skimage import data, transform
    except ImportError as exc:
        raise SystemExit('Image generation requires numpy and scikit-image. '
                         'Install the requirements.txt dependencies.') from exc
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    pixels = data.camera()
    pixels = transform.resize(pixels, (height, width), anti_aliasing=True,
                              preserve_range=True)
    pixels = np.clip(np.round(pixels), 0, 255).astype(int)
    path = out/(f'img{width}.txt' if width == height else f'img{width}x{height}.txt')
    np.savetxt(path, pixels.reshape(1, -1), fmt='%d')
    record = {'image': path.name, 'width': width, 'height': height,
              'fixture': 'skimage.data.camera (public domain)',
              'numpy_version': np.__version__, 'scikit_image_version': skimage.__version__,
              'scipy_version': scipy.__version__,
              'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'bytes': path.stat().st_size}
    if (width, height) == (120, 120):
        record['expected_sha256'] = EXPECTED_120_SHA256
        record['expected_bytes'] = EXPECTED_120_BYTES
        record['matches_expected_input'] = (record['sha256'] == EXPECTED_120_SHA256
                                            and record['bytes'] == EXPECTED_120_BYTES)
        if not record['matches_expected_input']:
            print('WARNING: generated image does not match the expected 120x120 input. '
                  'Check the recorded dependency versions before comparing exact results.',
                  file=sys.stderr, flush=True)
    (out/(path.stem+'_manifest.json')).write_text(json.dumps(record, indent=2) + '\n')
    print(f'Generated {path} ({width*height} pixels)', flush=True)
    if record.get('matches_expected_input'):
        print('Expected 120x120 input SHA256 and byte count match exactly.', flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'build/inputs')
    parser.add_argument('--width', type=int, default=120)
    parser.add_argument('--height', type=int, default=120)
    args = parser.parse_args()
    if args.width <= 0 or args.height <= 0:
        parser.error('Image dimensions must be positive')
    generate(args.out, args.width, args.height)


if __name__ == '__main__':
    main()
