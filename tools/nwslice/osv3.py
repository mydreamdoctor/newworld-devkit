#!/usr/bin/env python3
"""AZ ObjectStream v3 codec (decode + encode) for New World cooked assets.

Element model (as decoded): dict with keys
    crc : int   field-name crc32          (present iff flag 0x40)
    ver : int   element version byte       (present iff flag 0x80)
    id  : str   element type uuid          (always, 16 bytes)
    val : bytes raw value payload          (present iff flag 0x10)
    ch  : list  child elements

Wire format:
    0x00 tag, u32be version (=3), then element records; each record is
    flags|crc32be?|ver?|uuid16|size+payload?, children..., 0x00 terminator.
    flags: 0x08 always; 0x40 has-crc; 0x80 has-ver; 0x10 has-value;
    0x20 extended size field; f&7 = inline size (<=7) or width of the
    extended size field (1/2/4 bytes). A final 0x00 closes the stream.

decode_objectstream / encode_objectstream are exact inverses on the element
model. The encoder writes val bytes verbatim, so round-trip fidelity does not
depend on interpreting field types. Extended-size width is chosen minimally
(1/2/4); if a source file used a wider-than-minimal size field, encode will
differ at that element (reported by the round-trip harness, never silently).
"""
import struct
import uuid as _uuid

__all__ = ['parse_objectstream', 'encode_objectstream', 'decode_bytes',
           'encode_element_tree', 'VERSION']


def parse_objectstream(d):
    """Return (version, root element). Raises ValueError on malformed data."""
    if d[0] != 0:
        raise ValueError('bad stream tag')
    ver = struct.unpack_from('>I', d, 1)[0]
    if ver != 3:
        raise ValueError('unsupported ObjectStream version %d' % ver)
    p, n = 5, len(d)
    top = {'ch': []}
    stack = [top]
    while p < n and stack:
        f = d[p]; p += 1
        if f == 0:
            stack.pop(); continue
        if not f & 0x08:
            raise ValueError('bad flags 0x%02x at %d' % (f, p - 1))
        e = {'ch': []}
        if f & 0x40:
            e['crc'] = struct.unpack_from('>I', d, p)[0]; p += 4
        if f & 0x80:
            e['ver'] = d[p]; p += 1
        e['id'] = str(_uuid.UUID(bytes=bytes(d[p:p + 16]))); p += 16
        if f & 0x10:
            sz = f & 7
            if f & 0x20:
                if sz == 1:
                    sz = d[p]; p += 1
                elif sz == 2:
                    sz = struct.unpack_from('>H', d, p)[0]; p += 2
                elif sz == 4:
                    sz = struct.unpack_from('>I', d, p)[0]; p += 4
                else:
                    raise ValueError('bad size-field width')
            e['val'] = bytes(d[p:p + sz]); p += sz
        stack[-1]['ch'].append(e)
        stack.append(e)
    if stack or p != n:
        raise ValueError('stream not fully consumed (p=%d n=%d depth=%d)' % (p, n, len(stack)))
    if len(top['ch']) != 1:
        raise ValueError('expected one root element')
    return ver, top['ch'][0]


def _emit(e, out):
    f = 0x08
    val = e.get('val')
    if 'crc' in e:
        f |= 0x40
    if 'ver' in e:
        f |= 0x80
    ext_sz = 0
    if val is not None:
        f |= 0x10
        n = len(val)
        if n > 7:
            f |= 0x20
            ext_sz = 1 if n <= 0xFF else 2 if n <= 0xFFFF else 4
            f |= ext_sz
        else:
            f |= n
    out.append(f)
    if 'crc' in e:
        out += struct.pack('>I', e['crc'])
    if 'ver' in e:
        out.append(e['ver'])
    out += _uuid.UUID(e['id']).bytes
    if val is not None:
        if ext_sz == 1:
            out.append(len(val))
        elif ext_sz == 2:
            out += struct.pack('>H', len(val))
        elif ext_sz == 4:
            out += struct.pack('>I', len(val))
        out += val
    for c in e['ch']:
        _emit(c, out)
    out.append(0)


def encode_objectstream(root, version=3):
    """Inverse of parse_objectstream. Returns bytes."""
    out = bytearray(b'\x00' + struct.pack('>I', version))
    _emit(root, out)
    out.append(0)
    return bytes(out)


def decode_bytes(d, raw_names=None):
    return parse_objectstream(d)


def encode_element_tree(root, version=3):
    return encode_objectstream(root, version)
