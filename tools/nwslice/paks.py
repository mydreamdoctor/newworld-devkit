#!/usr/bin/env python3
"""Read access to New World .pak archives (plain zips; stored/deflate/Kraken-ooz).

Usage:
    paks.py PAK [--list PATTERN]          # list entries (fnmatch pattern)
    paks.py PAK OUTDIR PATTERN [PATTERN]  # extract matching entries to OUTDIR
Multiple paks may be indexed through the Paks class for name->entry lookup.
"""
import glob, os, struct, subprocess, sys, tempfile, zipfile, zlib, fnmatch

OOZ_CANDIDATES = [
    os.environ.get('OOZ', ''),
    '/mnt/dev_scratch/newworld/tools/ooz/build/ooz',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ooz'),
]
_OOZ = next((c for c in OOZ_CANDIDATES if c and os.path.isfile(c)), None)


def _decompress(i, raw):
    if i.compress_type == 0:
        return raw
    if i.compress_type == 8:
        return zlib.decompress(raw, -15)
    if i.compress_type == 15:
        if not _OOZ:
            raise ValueError('Kraken (ooz) entry but no ooz binary found')
        with tempfile.NamedTemporaryFile(delete=False) as t:
            t.write(struct.pack('<Q', i.file_size) + raw)
        try:
            return subprocess.run([_OOZ, '-c', '-q', t.name], check=True,
                                  capture_output=True).stdout
        finally:
            os.unlink(t.name)
    raise ValueError('unsupported pak method %d' % i.compress_type)


class Paks:
    """Index a set of .pak files by lowercase member name."""

    def __init__(self, pak_globs):
        self.idx = {}
        for g in pak_globs:
            for p in sorted(glob.glob(g)):
                with zipfile.ZipFile(p) as z:
                    for i in z.infolist():
                        self.idx[i.filename.lower()] = (p, i)

    def has(self, name):
        return name.lower() in self.idx

    def read(self, name):
        pak, i = self.idx[name.lower()]
        with open(pak, 'rb') as f:
            f.seek(i.header_offset)
            h = f.read(30)
            n, e = struct.unpack_from('<HH', h, 26)
            f.seek(i.header_offset + 30 + n + e)
            raw = f.read(i.compress_size)
        return _decompress(i, raw)

    def split_siblings(self, name):
        """Every pak member belonging to a (possibly split) texture `name`.

        NW streams big files as `x.dds` + `x.dds.1`..`.N` mip chunks, and
        some textures ship a second stream `x.dds.a` + `x.dds.1a`..`.Na`.
        The chunks live scattered across many part-paks, so a pull must
        gather them from the whole index — same-pak siblings are NOT the
        complete set. Returns member names present in the index."""
        base = name.lower()
        if base.endswith('.a'):
            stem = base[:-2]
            want = lambda n: n == base or (
                n.startswith(stem + '.')
                and n[len(stem) + 1:-1].isdigit() and n.endswith('a'))
        else:
            want = lambda n: n == base or (
                n.startswith(base + '.')
                and (n[len(base) + 1:].isdigit()
                     or n[len(base) + 1:] == 'a'
                     or (n[len(base) + 1:-1].isdigit()
                         and n.endswith('a'))))
        return sorted(n for n in self.idx if want(n))


def _extract(pak_path, outdir, patterns):
    made = 0
    with zipfile.ZipFile(pak_path) as z, open(pak_path, 'rb') as f:
        for i in z.infolist():
            if not any(fnmatch.fnmatch(i.filename.lower(), p.lower()) for p in patterns):
                continue
            f.seek(i.header_offset)
            h = f.read(30)
            n, e = struct.unpack_from('<HH', h, 26)
            f.seek(i.header_offset + 30 + n + e)
            raw = f.read(i.compress_size)
            dst = os.path.join(outdir, i.filename)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as o:
                o.write(_decompress(i, raw))
            made += 1
    print('%d extracted from %s' % (made, pak_path))


if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) >= 3 and args[1] == '--list':
        with zipfile.ZipFile(args[0]) as z:
            for n in z.namelist():
                if fnmatch.fnmatch(n.lower(), args[2].lower()):
                    print(n)
    elif len(args) >= 3:
        _extract(args[0], args[1], args[2:])
    else:
        print(__doc__)
        sys.exit(2)
