#!/usr/bin/env python3
"""Export an O3DE-generated level's terrain back to NW layout.

Reads <level_dir>/heightmaps/<region>.tif (the gradient image O3DE samples —
edits made in O3DE terrain painting write back to this source asset) and
<level_dir>/terrain.json, and writes:

  <out>/regions/<r_+xx_+yy>/region.heightmap   NW 16-bit LZW TIFF, rows in
                                              NW order (row 0 = highest y)
  <out>/terrain.json                          verbatim copy

No row flip anywhere: O3DE's image-gradient uv.y already matches NW's row
order, so TIFF row r == NW row r (verified in-editor, step 3.1).
"""
import argparse, json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from heightmap import decode, encode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('level_dir', help='O3DE level dir containing heightmaps/ and terrain.json')
    ap.add_argument('out', help='NW output root (gets regions/<r>/region.heightmap + terrain.json)')
    args = ap.parse_args()

    img_dir = os.path.join(args.level_dir, 'heightmaps')
    n = 0
    for fn in sorted(os.listdir(img_dir)):
        if not fn.endswith('.tif'):
            continue
        rname = fn[:-4]
        hm = decode(open(os.path.join(img_dir, fn), 'rb').read())
        rdir = os.path.join(args.out, 'regions', rname)
        os.makedirs(rdir, exist_ok=True)
        with open(os.path.join(rdir, 'region.heightmap'), 'wb') as f:
            f.write(encode(hm, lzw=True))
        n += 1
        print('  %s: %dx%d -> %s' % (rname, hm.w, hm.h, rdir))

    tj = os.path.join(args.level_dir, 'terrain.json')
    if os.path.isfile(tj):
        shutil.copyfile(tj, os.path.join(args.out, 'terrain.json'))
    print('exported %d region(s) -> %s' % (n, args.out))


if __name__ == '__main__':
    main()
