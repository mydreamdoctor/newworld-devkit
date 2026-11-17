#!/usr/bin/env python3
"""NW region.heightmap codec: baseline little-endian TIFF, 16-bit single-sample,
LZW (compression 5, early-change) with horizontal predictor 2, 4-row strips.
Height in metres = raw * mountainHeight / 65535 (terrain.json).

Decode mirrors the client/server loaders (Lockstep heightmap.go / heightmap_decode.py):
strips are cut to the declared row bytes because some regions end strips with a
stray literal and no EOI. Encode writes native-profile output (LZW + predictor 2,
4-row strips, EOI-terminated) and can also emit uncompressed TIFF.

Grid convention: row 0 = highest world y; world x -> column. 1 m per texel.
Region r_+xx_+yy world origin = (xx*W, yy*H) metres.
"""
import array, struct

__all__ = ['decode', 'encode', 'Heightmap', 'load', 'save']


class Heightmap:
    __slots__ = ('w', 'h', 'raw')

    def __init__(self, w, h, raw=None):
        self.w, self.h = w, h
        self.raw = raw if raw is not None else array.array('H', bytes(w * h * 2))


# ---------- TIFF LZW (MSB-first, early change) ----------

def lzw_decode(data, want):
    table = None
    out = bytearray()
    def reset():
        return [bytes([i]) for i in range(256)] + [b'', b'']
    table = reset()
    bits, buf, nb, prev = 9, 0, 0, None
    for byte in data:
        buf = (buf << 8) | byte
        nb += 8
        while nb >= bits:
            code = (buf >> (nb - bits)) & ((1 << bits) - 1)
            nb -= bits
            buf &= (1 << nb) - 1
            if code == 257:
                return bytes(out)
            if code == 256:
                table = reset(); bits = 9; prev = None; continue
            if prev is None:
                e = table[code]
            else:
                if code < len(table):
                    e = table[code]
                else:
                    e = prev + prev[:1]
                table.append(prev + e[:1])
            out += e
            prev = e
            if len(out) >= want:
                return bytes(out[:want])
            n = len(table)
            bits = 9 if n < 511 else 10 if n < 1023 else 11 if n < 2047 else 12
    return bytes(out)


def lzw_encode(data):
    """Encode one strip. Emits clear code, early-change table growth matching
    the decoder's schedule, and a terminating EOI."""
    out = bytearray()
    bits = 9
    buf = nb = 0
    def put(code):
        nonlocal buf, nb
        buf = (buf << bits) | code
        nb += bits
        while nb >= 8:
            out.append((buf >> (nb - 8)) & 0xff)
            nb -= 8
            buf &= (1 << nb) - 1
    table = {bytes([i]): i for i in range(256)}
    nxt = 258
    put(256)
    w = b''
    for i in range(len(data)):
        k = data[i:i + 1]
        wk = w + k
        if wk in table:
            w = wk
            continue
        put(table[w])
        if nxt < 4096:
            table[wk] = nxt
            nxt += 1
            n = nxt - 1  # decoder sees len(table) before adding next entry
            bits = 9 if n < 511 else 10 if n < 1023 else 11 if n < 2047 else 12
        else:
            put(256)
            table = {bytes([i]): i for i in range(256)}
            nxt = 258
            bits = 9
        w = k
    if w:
        put(table[w])
    put(257)
    if nb:
        out.append((buf << (8 - nb)) & 0xff)
    return bytes(out)


# ---------- TIFF ----------

def decode(d):
    """region.heightmap bytes -> Heightmap. Raises ValueError on bad input."""
    if len(d) < 8 or d[0] != 0x49 or d[1] != 0x49 or struct.unpack_from('<H', d, 2)[0] != 42:
        raise ValueError('not a little-endian TIFF')
    o = struct.unpack_from('<I', d, 4)[0]
    n = struct.unpack_from('<H', d, o)[0]
    tags = {}
    for i in range(n):
        t, ty, c, v = struct.unpack_from('<HHII', d, o + 2 + 12 * i)
        tags[t] = (c, v)
    w, h = tags[256][1], tags[257][1]
    comp = tags.get(259, (0, 1))[1]
    pred = tags.get(317, (0, 1))[1]
    rps = tags.get(278, (0, h))[1]
    def arr(t):
        c, v = tags[t]
        if c == 1:
            return (v,)
        return struct.unpack_from('<%dI' % c, d, v)
    offs, cnts = arr(273), arr(279)
    hm = Heightmap(w, h)
    for k, (so, sc) in enumerate(zip(offs, cnts)):
        strip = d[so:so + sc]
        rows = min(rps, h - k * rps)
        want = w * 2 * rows
        if comp == 5:
            strip = lzw_decode(strip, want)
        if len(strip) < want:
            raise ValueError('strip %d short: %d < %d' % (k, len(strip), want))
        strip = strip[:want]
        a = array.array('H')
        a.frombytes(strip)
        for r in range(rows):
            row = a[r * w:(r + 1) * w]
            if pred == 2:
                for x in range(1, w):
                    row[x] = (row[x] + row[x - 1]) & 0xffff
            hm.raw[(k * rps + r) * w:(k * rps + r + 1) * w] = row
    return hm


def encode(hm, lzw=True, rps=4, flip_y=False):
    """Heightmap -> region.heightmap bytes (native profile: LZW, predictor 2,
    4-row strips; or uncompressed when lzw=False). flip_y writes image rows
    bottom-up: O3DE's ImageGradient inverts Y when sampling, so a TIFF meant
    for it must store row 0 = max world-Y to render unflipped."""
    w, h = hm.w, hm.h
    nstrips = (h + rps - 1) // rps
    strips = []
    for k in range(nstrips):
        rows = min(rps, h - k * rps)
        a = array.array('H')
        for r in range(rows):
            src = k * rps + r
            if flip_y:
                src = h - 1 - src
            row = list(hm.raw[src * w:(src + 1) * w])
            if lzw:
                for x in range(w - 1, 0, -1):
                    row[x] = (row[x] - row[x - 1]) & 0xffff
            a.extend(row)
        strips.append(lzw_encode(a.tobytes()) if lzw else a.tobytes())
    # layout: header(8) | ifd | arrays | strip data
    ntags = 10
    ifd_off = 8
    arr_base = ifd_off + 2 + 12 * ntags + 4
    offs_arr = arr_base
    cnts_arr = offs_arr + 4 * nstrips
    data_off = cnts_arr + 4 * nstrips
    offs, pos = [], data_off
    for s in strips:
        offs.append(pos)
        pos += len(s)
    comp = 5 if lzw else 1
    tags = [
        (256, 4, 1, w), (257, 4, 1, h), (258, 3, 1, 16), (259, 3, 1, comp),
        (262, 3, 1, 1), (273, 4, nstrips, offs_arr), (277, 3, 1, 1),
        (278, 4, 1, rps), (279, 4, nstrips, cnts_arr), (317, 3, 1, 2 if lzw else 1),
    ]
    if nstrips == 1:
        tags[5] = (273, 4, 1, offs[0])
        tags[8] = (279, 4, 1, len(strips[0]))
    out = bytearray(b'II' + struct.pack('<HI', 42, ifd_off))
    out += struct.pack('<H', ntags)
    for t, ty, c, v in sorted(tags):
        out += struct.pack('<HHII', t, ty, c, v)
    out += struct.pack('<I', 0)
    if nstrips > 1:
        out += struct.pack('<%dI' % nstrips, *offs)
        out += struct.pack('<%dI' % nstrips, *[len(s) for s in strips])
    for s in strips:
        out += s
    return bytes(out)


def load(path):
    return decode(open(path, 'rb').read())


def save(hm, path, lzw=True):
    with open(path, 'wb') as f:
        f.write(encode(hm, lzw))
