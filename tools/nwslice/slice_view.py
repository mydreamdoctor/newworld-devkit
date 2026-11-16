#!/usr/bin/env python3
"""Named view of an ObjectStream v3 asset: resolves element type UUIDs to class
names and field CRCs to field names via nw_registry.json, and decodes primitive
value payloads. This is the "stub loader" for stage 2.3: every registered class
shows real names instead of raw uuids.

Usage:
  slice_view.py FILE [--depth N] [--stats] [--json]
  --stats prints resolution coverage only (no tree dump).
"""
import argparse, json, os, struct, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from osv3 import parse_objectstream

HERE = os.path.dirname(os.path.abspath(__file__))
_REG = None


def registry():
    global _REG
    if _REG is None:
        _REG = json.load(open(os.path.join(HERE, 'nw_registry.json')))
    return _REG


def type_name(uid):
    return registry()['type_names'].get(uid, uid)


def field_name(crc):
    return registry()['field_names'].get('%08x' % crc)


_PRIMS = {
    'bool': ('<?', 1), 'char': ('<b', 1), 'signed char': ('<b', 1),
    'unsigned char': ('<B', 1), 'short': ('>h', 2), 'unsigned short': ('>H', 2),
    'int': ('>i', 4), 'unsigned int': ('>I', 4), 'AZ::s32': ('>i', 4),
    'AZ::u32': ('>I', 4), 'AZ::s64': ('>q', 8), 'AZ::u64': ('>Q', 8),
    'unsigned long long': ('>Q', 8), 'long long': ('>q', 8),
    'float': ('>f', 4), 'double': ('>d', 8),
    'AZ::Crc32': ('>I', 4),
}


def decode_val(e):
    n = type_name(e['id'])
    v = e.get('val')
    if v is None:
        return None
    if n == 'AZ::Uuid' and len(v) == 16:
        return str(uuid.UUID(bytes=v))
    if n == 'AZStd::string':
        try:
            return v.decode('utf-8')
        except UnicodeDecodeError:
            return '0x' + v.hex()
    p = _PRIMS.get(n)
    if p and len(v) == p[1]:
        return struct.unpack(p[0], v)[0]
    return v


def view(e, depth=0, max_depth=1 << 30):
    tn = type_name(e['id'])
    out = {'type': tn}
    if 'crc' in e:
        fn = field_name(e['crc'])
        out['field'] = fn if fn else 'crc:%08x' % e['crc']
    if 'ver' in e:
        out['ver'] = e['ver']
    if 'val' in e:
        dv = decode_val(e)
        out['val'] = dv if not isinstance(dv, bytes) else ('0x' + dv.hex() if len(dv) <= 64 else '0x' + dv[:64].hex() + '...<%dB>' % len(dv))
    if depth < max_depth:
        ch = [view(c, depth + 1, max_depth) for c in e['ch']]
        if ch:
            out['ch'] = ch
    elif e['ch']:
        out['ch'] = '<%d children>' % len(e['ch'])
    return out


def stats(e, acc):
    acc['elements'] += 1
    acc['types'].setdefault(type_name(e['id']), 0)
    acc['types'][type_name(e['id'])] += 1
    acc['resolved_types'] += type_name(e['id']) != e['id']
    if 'crc' in e:
        acc['fields'] += 1
        acc['resolved_fields'] += field_name(e['crc']) is not None
    for c in e['ch']:
        stats(c, acc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('--depth', type=int, default=1 << 30)
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    ver, root = parse_objectstream(open(a.file, 'rb').read())
    if a.stats:
        acc = {'elements': 0, 'fields': 0, 'resolved_fields': 0,
               'resolved_types': 0, 'types': {}}
        stats(root, acc)
        n_known = sum(1 for t in acc['types'] if not t.count('-') == 4 or t in registry()['type_names'])
        print('%s: %d elements, %d distinct types, %d/%d type-refs resolved, %d/%d fields named'
              % (a.file, acc['elements'], len(acc['types']), acc['resolved_types'],
                 acc['elements'], acc['resolved_fields'], acc['fields']))
        unres = sorted(t for t in acc['types'] if t not in registry()['type_names'])
        if unres:
            print('unresolved types (%d):' % len(unres))
            for t in unres[:40]:
                print('  ', t, acc['types'][t])
        return
    v = view(root, max_depth=a.depth)
    print(json.dumps(v, indent=1, default=str) if a.json else _fmt(v))


def _fmt(v, ind=0):
    s = '  ' * ind
    line = s + v.get('field', '') + ': ' + v['type'] if 'field' in v else s + v['type']
    if 'ver' in v:
        line += ' (v%d)' % v['ver']
    if 'val' in v:
        line += ' = %r' % v['val']
    out = [line]
    ch = v.get('ch')
    if isinstance(ch, list):
        for c in ch:
            out.append(_fmt(c, ind + 1))
    elif ch:
        out.append('  ' * (ind + 1) + ch)
    return '\n'.join(out)


if __name__ == '__main__':
    main()
