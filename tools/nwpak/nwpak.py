#!/usr/bin/env python3
"""nwpak: client pak tooling for the NW dev kit.

The NW client mounts every *.pak under assets/ in filename order; a later
pak wins on duplicate entry paths (the lockstep harness uses the same
convention: assets/zz_nwtest.pak). So write-back ships as an OVERLAY pak
named to sort after the stock paks — the original paks are never touched.

Commands:
  nwpak.py list <pak>                         list entries
  nwpak.py extract <pak> <entry> <out>        extract one entry
  nwpak.py build <out.pak> <src[:entry]>...   write an overlay pak

Entry paths are the pak-internal paths (e.g.
slices/pois/territories/r_+03_+01_pois.dynamicslice); when omitted the
source file's basename is used. Entries are stored uncompressed — the
same method the stock lockstep override pak uses.
"""
import os
import struct
import subprocess
import sys
import tempfile
import zlib
import zipfile

# ooz CLI for Oodle (zip method 15) entries; NW_OOZ overrides the search.
_OOZ_CANDIDATES = [
    os.environ.get('NW_OOZ', ''),
    '/mnt/dev_scratch/newworld/tools/ooz/build/ooz',
]


def build(out, pairs):
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED,
                         allowZip64=False) as z:
        for src, entry in pairs:
            zi = zipfile.ZipInfo(entry, (2020, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_STORED
            zi.external_attr = 0o644 << 16
            with open(src, 'rb') as f:
                z.writestr(zi, f.read())
    with zipfile.ZipFile(out) as z:
        for i in z.infolist():
            print('%s %d' % (i.filename, i.file_size))


def list_pak(pak):
    with zipfile.ZipFile(pak) as z:
        for i in z.infolist():
            print('%s %d' % (i.filename, i.file_size))


def _read_entry(pak, name):
    """Read one pak entry: methods 0 stored, 8 deflate, 15 Oodle via ooz."""
    with zipfile.ZipFile(pak) as z:
        info = next((i for i in z.infolist()
                     if i.filename.lower() == name.lower()), None)
        if info is None:
            raise KeyError('%s not in %s' % (name, pak))
        with open(pak, 'rb') as f:
            f.seek(info.header_offset)
            h = f.read(30)
            n, e = struct.unpack_from('<HH', h, 26)
            f.seek(info.header_offset + 30 + n + e)
            raw = f.read(info.compress_size)
    if info.compress_type == 0:
        return raw
    if info.compress_type == 8:
        return zlib.decompress(raw, -15)
    if info.compress_type == 15:
        ooz = next((p for p in _OOZ_CANDIDATES
                    if p and os.path.isfile(p)), None)
        if ooz is None:
            raise RuntimeError('Oodle entry %s needs an ooz binary (NW_OOZ)'
                               % name)
        with tempfile.NamedTemporaryFile(delete=False) as t:
            t.write(struct.pack('<Q', info.file_size) + raw)
        try:
            return subprocess.run([ooz, '-c', '-q', t.name],
                                  check=True, capture_output=True).stdout
        finally:
            os.unlink(t.name)
    raise ValueError('unsupported pak method %d for %s'
                     % (info.compress_type, name))


def extract(pak, entry, out):
    data = _read_entry(pak, entry)
    with open(out, 'wb') as f:
        f.write(data)
    print('%s -> %s (%d bytes)' % (entry, out, len(data)))


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    cmd = argv[1]
    if cmd == 'list':
        list_pak(argv[2])
    elif cmd == 'extract':
        if len(argv) != 5:
            sys.exit(__doc__)
        extract(argv[2], argv[3], argv[4])
    elif cmd == 'build':
        pairs = []
        for a in argv[3:]:
            src, _, entry = a.partition(':')
            pairs.append((src, entry.replace('\\', '/') or
                          os.path.basename(src)))
        build(argv[2], pairs)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv)
