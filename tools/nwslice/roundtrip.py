#!/usr/bin/env python3
"""Round-trip harness: decode -> re-encode -> byte compare for ObjectStream v3 files.

Usage: roundtrip.py FILE [FILE...] | --dir DIR
Reports per file: EXACT / DIFFERS (with first-diff offset and element path when
locatable) / DECODE-FAIL. Exit 0 iff every file round-trips byte-exact.
"""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from osv3 import parse_objectstream, encode_objectstream


def first_diff(a, b):
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n if len(a) != len(b) else -1


def check(path):
    src = open(path, 'rb').read()
    try:
        ver, root = parse_objectstream(src)
    except ValueError as e:
        return 'DECODE-FAIL', str(e)
    try:
        out = encode_objectstream(root, ver)
    except Exception as e:
        return 'ENCODE-FAIL', str(e)
    if out == src:
        return 'EXACT', ''
    i = first_diff(src, out)
    return 'DIFFERS', 'first diff @%d, len %d vs %d (src[%d]=%02x out[%d]=%02x)' % (
        i, len(src), len(out), i, src[i] if i < len(src) else -1, i, out[i] if i < len(out) else -1)


def main(argv):
    files = []
    for a in argv[1:]:
        if a == '--dir':
            continue
        if os.path.isdir(a):
            files += sorted(glob.glob(os.path.join(a, '**', '*.*'), recursive=True))
        else:
            files.append(a)
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        print(__doc__); return 2
    fails = 0
    for f in files:
        st, msg = check(f)
        print('%-12s %s %s' % (st, f, msg))
        if st != 'EXACT':
            fails += 1
    print('---\n%d/%d byte-exact' % (len(files) - fails, len(files)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
