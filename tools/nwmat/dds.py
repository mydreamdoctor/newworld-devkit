"""New World split-DDS reassembly.

NW streams DDS files split across the pak: `x.dds` holds the 148-byte
header (128 DDS + 20 DX10) plus the trailing smallest mips; `x.dds.1`
.. `x.dds.N` hold the larger mips with the highest N = mip 0. A complete
DDS is: header + mips in descending-N order + the base file's tail.

`x.dds.a` is a SECOND split texture (own header, own `.Na` mips) — NW
ships a paired alpha/aux texture for some shaders. reassemble() works
on it unchanged (pass the .a path).
"""
import os
import struct

HDR = 148  # 128-byte DDS header + 20-byte DX10 header


def is_split_stub(data):
    return len(data) >= HDR and data[:4] == b'DDS '


def mip_parts(path):
    """Numbered mip files for `path` sorted high-N (mip0) first.

    For a `x.dds.a` second texture the parts are `x.dds.1a` .. `x.dds.Na`."""
    if path.endswith('.a'):
        stem = path[:-2]
        pat = lambda n: '%s.%da' % (stem, n)
    else:
        pat = lambda n: '%s.%d' % (path, n)
    out = []
    i = 1
    while os.path.isfile(pat(i)):
        i += 1
    for n in range(i - 1, 0, -1):
        out.append(pat(n))
    return out


# DXGI 4x4-block byte counts for the BC formats NW ships.
_BLOCK_BYTES = {71: 8, 72: 8, 73: 8,                 # BC1
                74: 16, 75: 16, 76: 16,              # BC2
                77: 16, 78: 16, 79: 16,              # BC3
                80: 8, 81: 8, 82: 8,                 # BC4
                83: 16, 84: 16, 85: 16,              # BC5
                95: 8, 96: 16,                     # BC6H
                98: 16, 99: 16}                    # BC7


def _payload_size(base):
    """Expected mip-chain byte size from the header, or None."""
    try:
        h = struct.unpack_from('<I', base, 12)[0]
        w = struct.unpack_from('<I', base, 16)[0]
        mips = struct.unpack_from('<I', base, 28)[0]
        dxgi = struct.unpack_from('<I', base, 128)[0]
    except struct.error:
        return None
    bpb = _BLOCK_BYTES.get(dxgi)
    if not w or not h or not mips or bpb is None:
        return None
    return sum(((max(1, w >> i) + 3) // 4) * ((max(1, h >> i) + 3) // 4) * bpb
               for i in range(mips))


def reassemble(path):
    """Read a split DDS (+ mip tails) -> complete DDS bytes.

    A base file that already holds the full mip chain is returned
    unchanged even when `.N` siblings exist."""
    with open(path, 'rb') as f:
        base = f.read()
    if len(base) < HDR:
        raise ValueError('%s: too small for a DDS header' % path)
    want = _payload_size(base)
    if want is not None and len(base) - HDR >= want:
        return base
    parts = mip_parts(path)
    data = bytearray(base[:HDR])
    for p in parts:
        with open(p, 'rb') as f:
            data += f.read()
    data += base[HDR:]
    if not parts:
        return base
    if want is not None and len(data) - HDR != want:
        raise ValueError(
            '%s: incomplete split DDS — header needs %d payload bytes, '
            '%d parts + stub give %d (a mip part is missing, check the paks)'
            % (path, want, len(parts), len(data) - HDR))
    return bytes(data)


def reassemble_tree(src_path, dst_path):
    """Reassemble one texture, or every `.dds` stub under a directory
    (mirroring the tree). Returns list of written files."""
    written = []

    def one(s, d):
        os.makedirs(os.path.dirname(d), exist_ok=True)
        with open(d, 'wb') as f:
            f.write(reassemble(s))
        written.append(d)

    if os.path.isfile(src_path):
        one(src_path, dst_path)
        return written
    for dirpath, _, files in os.walk(src_path):
        for fn in files:
            if not fn.lower().endswith('.dds'):
                continue
            s = os.path.join(dirpath, fn)
            with open(s, 'rb') as f:
                head = f.read(4)
            if head != b'DDS ':
                continue
            one(s, os.path.join(dst_path, os.path.relpath(s, src_path)))
    return written


if __name__ == '__main__':
    import sys
    for w in reassemble_tree(sys.argv[1], sys.argv[2]):
        print(w)
