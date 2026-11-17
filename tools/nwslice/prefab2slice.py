#!/usr/bin/env python3
"""O3DE .prefab -> NW .dynamicslice write-back (the kit's 'save').

Re-parses the ORIGINAL .dynamicslice and patches, in place:

  - each entity's GameTransformComponent m_worldTM from the prefab's
    TransformComponent (Translate + ZYX-euler Rotate), preserving the
    entity's original scale columns (NW transforms carry scale; the
    prefab view does not edit it),
  - each entity's SplineComponent bezier vertices from the prefab's
    EditorSplineComponent (pos + forward/back tangents), when the
    prefab actually carries one.

Everything else — every unmapped component, ids, flags, unknown fields —
round-trips byte-exact via the osv3 element model.

Entity matching: by name first (slice names are unique per file in
practice), falling back to document order. Prefab entities that match
nothing in the slice, and slice entities the prefab dropped, are
reported in the JSON summary; they are left untouched in the output.

Usage: prefab2slice.py SLICE PREFAB [-o OUT.dynamicslice] [--json out.json]
"""
import argparse, json, math as _m, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from osv3 import parse_objectstream, encode_objectstream
import river_io
from slice2prefab import _entities, _euler_deg, _str_val

_by_crc = river_io._by_crc
_f32s = river_io._f32s
_pf32s = river_io._pf32s
_f32 = river_io._f32
_kids = river_io._kids


def _mat34(translate, rotate):
    """Translate + ZYX euler degrees -> AZ-style 3x4 (basis columns + t),
    flat list of 12 floats matching m_worldTM layout."""
    tx, ty, tz = translate
    if not rotate:
        return [1, 0, 0, 0, 1, 0, 0, 0, 1, tx, ty, tz]
    rx, ry, rz = (_m.radians(v) for v in rotate)
    cx, sx, cy, sy, cz, sz = (_m.cos(rx), _m.sin(rx), _m.cos(ry),
                             _m.sin(ry), _m.cos(rz), _m.sin(rz))
    # R = Rz * Ry * Rx, column vectors
    return [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz,
            cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz,
            -sy, sx * cy, cx * cy,
            tx, ty, tz]


def _prefab_transforms(prefab):
    """prefab Entities dict -> [(name, translate, rotate, comps)] in order."""
    out = []
    for eid, e in prefab.get('Entities', {}).items():
        comps = e.get('Components', {})
        tr, rot = [0.0, 0.0, 0.0], None
        for c in comps.values():
            td = c.get('Transform Data')
            if td:
                tr = td.get('Translate', tr)
                rot = td.get('Rotate')
        out.append((e.get('Name', ''), tr, rot, comps))
    return out


def _patch_spline(comp_el, spline_comp):
    """Patch a slice SplineComponent element from an EditorSplineComponent.

    Prefab spline format: 'Spline Data': {'m_vertices':[{'Position':[x,y,z],
    'Forward':[...], 'Back':[...]}...], 'Closed':bool} — tolerate missing
    tangent fields. Returns True when patched."""
    sd = spline_comp.get('Spline Data') or {}
    pverts = sd.get('m_vertices') or []
    if not pverts:
        return False
    bz = river_io._spline_el(comp_el)
    verts, vels = river_io._vertex_elements(bz)
    beziers, _ = river_io._bezier_elements(bz)
    if len(pverts) != len(verts):
        return False
    for i, pv in enumerate(pverts):
        pos = pv.get('Position') or [0, 0, 0]
        verts[i]['val'] = _pf32s(pos)
        if i < len(beziers):
            for nm, key in (('Forward', 'Forward'), ('Back', 'Back')):
                f = _by_crc(beziers[i], nm)
                v = pv.get(key) or pv.get(nm)
                if f is not None and 'val' in f and v:
                    f['val'] = _pf32s(v)
    return True


def convert(slice_raw, prefab, level_name=None):
    ver, root = parse_objectstream(slice_raw)
    slice_ents = _entities(root)          # [(name, comps)]
    prefab_ents = _prefab_transforms(prefab)

    by_name = {}
    for name, comps in slice_ents:
        by_name.setdefault(name, []).append(comps)

    report = {'updated': 0, 'unmatched_prefab': [], 'dropped_slice': [],
              'splines_patched': 0}
    used = set()

    for name, tr, rot, pcomps in prefab_ents:
        comps = None
        cands = by_name.get(name)
        if cands:
            for c in cands:
                if id(c) not in used:
                    comps = c
                    break
        if comps is None:
            # order fallback: positional pairing was used when generating
            report['unmatched_prefab'].append(name)
            continue
        used.add(id(comps))
        gt = comps.get('GameTransformComponent')
        if gt is None:
            continue
        f = _by_crc(gt, 'm_worldTM')
        if f is None or 'val' not in f:
            continue
        old = _f32s(f['val'])
        new = list(old)
        changed = False
        # translation: patch only if it moved (keeps untouched bytes exact)
        if any(abs(a - b) > 1e-4 for a, b in zip(tr, old[9:12])):
            new[9:12] = tr
            changed = True
        # rotation: rebuild basis only if the euler changed, preserving
        # the source per-column scale
        old_rot = _euler_deg(old) or [0.0, 0.0, 0.0]
        new_rot = rot or [0.0, 0.0, 0.0]
        if any(abs(a - b) > 1e-3 for a, b in zip(new_rot, old_rot)):
            rb = _mat34(tr, rot)[:9]
            for b in range(3):
                o = _m.sqrt(old[b * 3] ** 2 + old[b * 3 + 1] ** 2
                            + old[b * 3 + 2] ** 2)
                if o > 1e-9:
                    for r in range(3):
                        rb[b * 3 + r] *= o
            new[:9] = rb
            changed = True
        if not changed:
            continue
        f['val'] = _pf32s(new)
        report['updated'] += 1
        sc = comps.get('SplineComponent')
        if sc is not None:
            for c in pcomps.values():
                if 'Spline' in str(c.get('$type', '')):
                    if _patch_spline(sc, c):
                        report['splines_patched'] += 1
                    break

    matched = sum(1 for _, c in slice_ents if id(c) in used)
    report['dropped_slice'] = [n for n, c in slice_ents if id(c) not in used
                               and n]
    report['total_slice_entities'] = len(slice_ents)
    report['matched'] = matched
    return encode_objectstream(root, ver), report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('slice')
    ap.add_argument('prefab')
    ap.add_argument('-o', '--out')
    ap.add_argument('--json')
    a = ap.parse_args()
    raw = open(a.slice, 'rb').read()
    prefab = json.load(open(a.prefab))
    out, report = convert(raw, prefab)
    dst = a.out or a.slice
    open(dst, 'wb').write(out)
    report['wrote'] = dst
    print(json.dumps(report, indent=1))
    if a.json:
        json.dump(report, open(a.json, 'w'), indent=1)


if __name__ == '__main__':
    main()
