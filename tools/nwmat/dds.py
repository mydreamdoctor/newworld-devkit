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


def _a_block(data, off):
    """8-byte BC4/BC3-alpha block -> 16 alpha values."""
    a0, a1 = data[off], data[off + 1]
    bits = int.from_bytes(data[off + 2:off + 8], 'little')
    if a0 > a1:
        lut = [a0, a1] + [(a0 * (7 - i) + a1 * i) // 7 for i in range(1, 7)]
    else:
        lut = ([a0, a1]
               + [(a0 * (5 - i) + a1 * i) // 5 for i in range(1, 5)]
               + [0, 255])
    return [lut[(bits >> (3 * i)) & 7] for i in range(16)]


def _c_block(data, off):
    """8-byte BC1/BC3-color block -> 16 (r,g,b) tuples."""
    c0, c1 = struct.unpack_from('<HH', data, off)
    bits = int.from_bytes(data[off + 4:off + 8], 'little')
    r0, g0, b0 = ((c0 >> 11) * 255 // 31, ((c0 >> 5) & 63) * 255 // 63,
                  (c0 & 31) * 255 // 31)
    r1, g1, b1 = ((c1 >> 11) * 255 // 31, ((c1 >> 5) & 63) * 255 // 63,
                  (c1 & 31) * 255 // 31)
    if c0 > c1:
        lut = [(r0, g0, b0), (r1, g1, b1),
               ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3),
               ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3)]
    else:
        lut = [(r0, g0, b0), (r1, g1, b1),
               ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2), (0, 0, 0)]
    return [lut[(bits >> (2 * i)) & 3] for i in range(16)]


def decode_mip0(data):
    """Decode mip0 of a complete BC1/BC2/BC3/BC4 DDS -> (w, h, rgba bytes)."""
    h = struct.unpack_from('<I', data, 12)[0]
    w = struct.unpack_from('<I', data, 16)[0]
    dxgi = struct.unpack_from('<I', data, 128)[0]
    if dxgi in (80, 81, 82):          # BC4: single-channel alpha block
        bpb, has_col = 8, False
    elif dxgi in (71, 72, 73):        # BC1
        bpb, has_col, bc3a = 8, True, False
    elif dxgi in (74, 75, 76):        # BC2 (alpha block 8B explicit)
        bpb, has_col, bc3a = 16, True, 'bc2'
    elif dxgi in (77, 78, 79):        # BC3
        bpb, has_col, bc3a = 16, True, True
    else:
        raise ValueError('decode_mip0: unsupported dxgi %d' % dxgi)
    out = bytearray(w * h * 4)
    bw, bh = (w + 3) // 4, (h + 3) // 4
    for byi in range(bh):
        for bxi in range(bw):
            off = HDR + (byi * bw + bxi) * bpb
            if dxgi in (80, 81, 82):
                px = [(0, 0, 0)] * 16
                al = _a_block(data, off)
            else:
                if bc3a is True:
                    al = _a_block(data, off)
                    coff = off + 8
                elif bc3a == 'bc2':
                    abits = int.from_bytes(data[off:off + 8], 'little')
                    al = [((abits >> (4 * i)) & 15) * 17 for i in range(16)]
                    coff = off + 8
                else:
                    al = [255] * 16
                    coff = off
                px = _c_block(data, coff)
            for i, (r, g, b) in enumerate(px):
                x, y = bxi * 4 + i % 4, byi * 4 + i // 4
                if x < w and y < h:
                    o = (y * w + x) * 4
                    out[o] = r
                    out[o + 1] = g
                    out[o + 2] = b
                    out[o + 3] = al[i]
    return w, h, out


def _rgba_dds(w, h, rgba):
    """Minimal uncompressed RGBA32 DDS (bytes stored R,G,B,A).

    Uses a DX10 header with DXGI_FORMAT_R8G8B8A8_UNORM_SRGB so downstream
    image compilers tag the data sRGB; a legacy RGBA-mask header reads as
    linear and washes out authored sRGB pixels."""
    hdr = struct.pack(
        '<4s I I I I I I I 44s I I I I 4I I 4I',
        b'DDS ',
        124,          # header size
        0x100F,       # DDSD_CAPS|HEIGHT|WIDTH|PIXELFORMAT|PITCH
        h, w, w * 4,  # height, width, pitch
        0,            # depth
        1,            # mipMapCount
        b'\0' * 44,   # reserved1
        32,           # pf size
        0x4,          # DDPF_FOURCC
        0x30315844,   # 'DX10'
        0,            # bitcount
        0, 0, 0, 0,   # RGBA masks (unused for DX10)
        0x1000,       # DDSCAPS_TEXTURE
        0, 0, 0, 0)   # caps2,3,4,reserved2
    ext = struct.pack('<5I', 29, 3, 0, 1, 0)  # R8G8B8A8_UNORM_SRGB, 2D
    return hdr + ext + bytes(rgba)


def _orient_mask(mask):
    """Return (mask, inverted). NW ships opacity maps in both conventions:
    some store the leaf/cluster texels bright (alpha = coverage), others
    store the *fill* bright and the leaves dark. A usable cutout mask has
    the minority of atlas texels above the threshold, so a fill-dominant
    map (median > 0.5) is treated as inverted and flipped. Uniform masks
    (no texels at/below 0.5) are left alone — there is nothing to cut."""
    s = sorted(mask)
    med = s[len(s) // 2]
    if med > 0x80 and s[0] <= 0x80:
        return bytes(255 - v for v in mask), True
    return bytes(mask), False


def merge_opacity_alpha(diff_path, opacity_path):
    """Reassemble+decode both DDS, return (RGBA32 DDS bytes, inverted) of
    diff's RGB with opacity's channel as alpha. NW ships opacity maps at
    a lower resolution than the diffuse; resample to the diffuse size.
    Inverted-convention maps (fill bright, leaves dark) are flipped so
    alpha always means coverage."""
    dw, dh, drgba = decode_mip0(reassemble(diff_path))
    ow, oh, orgba = decode_mip0(reassemble(opacity_path))
    if all(v == 255 for v in orgba[3::4]):
        # Opacity stored as a grayscale RGB mask (e.g. BC1) rather than in
        # an alpha channel: decoded alpha is all-opaque, so take the mask
        # from luminance instead.
        mask = bytes(max(orgba[i], orgba[i + 1], orgba[i + 2])
                     for i in range(0, len(orgba), 4))
    else:
        mask = bytes(orgba[3::4])
    mask, inverted = _orient_mask(mask)
    if (ow, oh) != (dw, dh):
        # bilinear resample of the alpha channel
        resampled = bytearray(dw * dh)
        for y in range(dh):
            sy = (y + 0.5) * oh / dh - 0.5
            y0 = int(sy)
            fy = sy - y0
            y1 = y0 + 1
            if y0 < 0:
                y0 = 0
                fy = 0.0
            if y1 >= oh:
                y1 = oh - 1
                fy = 1.0
            for x in range(dw):
                sx = (x + 0.5) * ow / dw - 0.5
                x0 = int(sx)
                fx = sx - x0
                x1 = x0 + 1
                if x0 < 0:
                    x0 = 0
                    fx = 0.0
                if x1 >= ow:
                    x1 = ow - 1
                    fx = 1.0
                a = mask[y0 * ow + x0] * (1 - fx) + mask[y0 * ow + x1] * fx
                b = mask[y1 * ow + x0] * (1 - fx) + mask[y1 * ow + x1] * fx
                resampled[y * dw + x] = int(a * (1 - fy) + b * fy + 0.5)
        drgba[3::4] = resampled
    else:
        drgba[3::4] = mask
    return _rgba_dds(dw, dh, drgba), inverted


def reassemble_mask(path):
    """Reassemble a diffuse DDS for an alpha-tested material and normalize
    the alpha channel's orientation (same convention as
    merge_opacity_alpha). Returns (DDS bytes, inverted) — the original
    reassembled bytes when the alpha was already coverage-oriented."""
    data = reassemble(path)
    w, h, rgba = decode_mip0(data)
    mask, inverted = _orient_mask(rgba[3::4])
    if not inverted:
        return data, False
    rgba[3::4] = mask
    return _rgba_dds(w, h, rgba), True
