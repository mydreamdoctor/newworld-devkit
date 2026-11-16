#!/usr/bin/env python3
"""Editable model for NW terrain_water river slices (.dynamicslice).

extract(bytes) -> model dict   (spline points, tangents, widths, transform)
apply(model, bytes) -> bytes   (patch the element tree, reserialize)

The element tree patches in place: values are rewritten in `val` payloads and
element lists are resized by cloning template elements, so everything outside
the edited fields reserializes byte-identical.

Transform layout: AZ::Transform serializes column-major 3x4 — basisX, basisY,
basisZ, translation as four big-endian float32 triples (48 bytes).

Usage:
  river_io.py dump  SLICE > river.json
  river_io.py apply SLICE river.json > out.dynamicslice
"""
import copy, json, struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from osv3 import parse_objectstream, encode_objectstream

HERE = os.path.dirname(os.path.abspath(__file__))
_REG = json.load(open(os.path.join(HERE, 'nw_registry.json')))
TN = reg_types = _REG['type_names']            # uuid -> name
FN = _REG['field_names']                        # hex crc -> name
CRC = {v: int(k, 16) for k, v in FN.items()}    # name -> crc
UID = {v: k for k, v in TN.items()}             # name -> uuid


def _kids(e):
    return e.get('ch', [])


def _by_crc(e, name):
    c = CRC[name]
    for k in _kids(e):
        if k.get('crc') == c:
            return k
    return None


def _by_type(e, name):
    u = UID[name]
    return [k for k in _kids(e) if k['id'] == u]


def _walk(e):
    yield e
    for k in _kids(e):
        yield from _walk(k)


def _f32s(v):
    return list(struct.unpack('>%df' % (len(v) // 4), v))


def _pf32s(vals):
    return struct.pack('>%df' % len(vals), *vals)


def _f32(v):
    return struct.unpack('>f', v)[0]


def _pf32(x):
    return struct.pack('>f', x)


def _components(entity_el):
    """entity el -> {type-name: component element}."""
    out = {}
    comps = _by_crc(entity_el, 'Components')
    if comps is None:
        return out
    for c in _kids(comps):
        out[TN.get(c['id'], c['id'])] = c
    return out


def _entities(root):
    """Every AZ::Entity element in the tree (root entity + slice entities)."""
    return [e for e in _walk(root)
            if e['id'] == UID['AZ::Entity'] and _by_crc(e, 'Components') is not None]


def _spline_el(comp):
    """SplineComponent -> BezierSpline element."""
    conf = _by_crc(comp, 'Configuration')
    spl = _by_crc(conf, 'Spline')
    for k in _kids(spl):
        if k['id'] == UID['BezierSpline']:
            return k
    raise KeyError('no BezierSpline under Spline field')


def _river_el(comp):
    """RiverComponent -> River element."""
    return _by_crc(comp, 'River')


def _vertex_elements(bezier):
    spline = _by_type(bezier, 'Spline')[0]
    vc = _by_crc(spline, 'Vertices')
    inner = _by_crc(vc, 'Vertices')
    return [k for k in _kids(inner) if k['id'] == UID['Vector3']], inner


def _bezier_elements(bezier):
    bd = _by_crc(bezier, 'Bezier Data')
    return [k for k in _kids(bd) if k['id'] == UID['BezierData']], bd


def _width_elements(river):
    geom = _by_type(river, 'SplineGeometry')[0]
    w = _by_crc(geom, 'Width')
    wa = _by_crc(w, 'WidthAttribute')
    floats = []
    for k in _kids(wa):
        for e in _kids(k):
            floats.append(e)
    return floats, wa, geom, w


def extract(raw):
    ver, root = parse_objectstream(raw)
    for ent in _entities(root):
        comps = _components(ent)
        if 'SplineComponent' not in comps or 'RiverComponent' not in comps:
            continue
        bz = _spline_el(comps['SplineComponent'])
        spline = _by_type(bz, 'Spline')[0]
        verts, _ = _vertex_elements(bz)
        beziers, _ = _bezier_elements(bz)
        closed = _by_crc(spline, 'Closed')
        gran = _by_crc(bz, 'Granularity')
        points = []
        for i, v in enumerate(verts):
            p = {'pos': _f32s(v['val'])}
            if i < len(beziers):
                bd = beziers[i]
                for nm in ('Forward', 'Back', 'Angle'):
                    f = _by_crc(bd, nm)
                    if f is not None and 'val' in f:
                        p[nm.lower()] = _f32s(f['val']) if nm != 'Angle' else _f32(f['val'])
            points.append(p)
        river = _river_el(comps['RiverComponent'])
        wfloats, wa, geom, wmod = _width_elements(river)
        dw = _by_crc(wmod, 'DefaultWidth')
        model = {
            'spline': {
                'closed': bool(closed['val'][0]) if closed and 'val' in closed else False,
                'granularity': struct.unpack('>H', gran['val'])[0] if gran else 8,
                'points': points,
            },
            'river': {
                'defaultWidth': _f32(dw['val']) if dw else 0.0,
                'widthKeys': [_f32(e['val']) for e in wfloats],
            },
        }
        for nm, dec in (('SegmentLength', _f32), ('TileLength', _f32),
                        ('SortPriority', lambda v: struct.unpack('>i', v)[0]),
                        ('ViewDistanceMultiplier', _f32),
                        ('MinSpec', lambda v: struct.unpack('>I', v)[0])):
            f = _by_crc(geom, nm)
            if f is not None and 'val' in f:
                model['river'][nm] = dec(f['val'])
        # every other River field: expose read-only values for the editor UI
        extra = {}
        for f in _kids(river):
            nm = FN.get('%08x' % f.get('crc', 0))
            if nm and 'val' in f:
                extra[nm] = _f32s(f['val']) if len(f['val']) % 4 == 0 else list(f['val'])
        model['river']['other'] = extra
        gt = comps.get('GameTransformComponent')
        if gt is not None:
            for nm in ('m_worldTM', 'm_localTM'):
                f = _by_crc(gt, nm)
                if f is not None and 'val' in f:
                    model[nm] = _f32s(f['val'])
        model['_entity_found'] = True
        return model
    raise KeyError('no entity with SplineComponent + RiverComponent')


def _resize(elements, holder, want, template):
    """Grow/shrink a child-element list to `want` entries via deepcopy."""
    cur = len(elements)
    if cur == want:
        return
    if cur > want:
        del holder['ch'][holder['ch'].index(elements[want]):holder['ch'].index(elements[-1]) + 1]
        del elements[want:]
        return
    for _ in range(want - cur):
        e = copy.deepcopy(template)
        holder['ch'].append(e)
        elements.append(e)


def apply(model, raw):
    ver, root = parse_objectstream(raw)
    for ent in _entities(root):
        comps = _components(ent)
        if 'SplineComponent' not in comps or 'RiverComponent' not in comps:
            continue
        bz = _spline_el(comps['SplineComponent'])
        spline = _by_type(bz, 'Spline')[0]
        pts = model['spline']['points']
        verts, vholder = _vertex_elements(bz)
        beziers, bholder = _bezier_elements(bz)
        _resize(verts, vholder, len(pts), verts[-1])
        _resize(beziers, bholder, len(pts), beziers[-1])
        for i, p in enumerate(pts):
            verts[i]['val'] = _pf32s(p['pos'])
            bd = beziers[i]
            for nm, key in (('Forward', 'forward'), ('Back', 'back'), ('Angle', 'angle')):
                f = _by_crc(bd, nm)
                if f is None or key not in p:
                    continue
                v = p[key]
                f['val'] = _pf32s(v) if isinstance(v, list) else _pf32(v)
        closed = _by_crc(spline, 'Closed')
        if closed is not None:
            closed['val'] = bytes([1 if model['spline'].get('closed') else 0])
        gran = _by_crc(bz, 'Granularity')
        if gran is not None and 'granularity' in model['spline']:
            gran['val'] = struct.pack('>H', int(model['spline']['granularity']))
        river = _river_el(comps['RiverComponent'])
        wfloats, wa, geom, wmod = _width_elements(river)
        keys = model['river'].get('widthKeys', [])
        _resize(wfloats, wa, len(keys), wfloats[-1] if wfloats else None)
        for i, k in enumerate(keys):
            wfloats[i]['val'] = _pf32(k)
        dw = _by_crc(wmod, 'DefaultWidth')
        if dw is not None and 'defaultWidth' in model['river']:
            dw['val'] = _pf32(model['river']['defaultWidth'])
        for nm in ('SegmentLength', 'TileLength'):
            f = _by_crc(geom, nm)
            if f is not None and nm in model['river']:
                f['val'] = _pf32(model['river'][nm])
        gt = comps.get('GameTransformComponent')
        if gt is not None:
            for nm in ('m_worldTM', 'm_localTM'):
                f = _by_crc(gt, nm)
                if f is not None and nm in model:
                    f['val'] = _pf32s(model[nm])
        return encode_objectstream(root, ver)
    raise KeyError('no entity with SplineComponent + RiverComponent')


def main():
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('dump')
    d.add_argument('slice')
    a = sub.add_parser('apply')
    a.add_argument('slice')
    a.add_argument('model')
    a.add_argument('-o', '--out')
    args = ap.parse_args()
    raw = open(args.slice, 'rb').read()
    if args.cmd == 'dump':
        json.dump(extract(raw), sys.stdout, indent=2)
        print()
    else:
        model = json.load(open(args.model))
        out = apply(model, raw)
        if args.out:
            open(args.out, 'wb').write(out)
        else:
            sys.stdout.buffer.write(out)


if __name__ == '__main__':
    main()
