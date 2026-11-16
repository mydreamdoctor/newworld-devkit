#!/usr/bin/env python3
"""Bridge a NW terrain_water river slice <-> an O3DE prefab.

to-prefab:   slice -> .prefab with an entity carrying EditorSplineComponent
             (the NW bezier points/tangents verbatim) + a .river.json sidecar
             holding the river params O3DE has no component for.
from-prefab: edited .prefab's spline points -> patched .dynamicslice.

The river's world placement comes from the level's water.capitals.json (the
slice's own transform is identity); pass --capitals to position the entity.

Usage:
  river2prefab.py to-prefab SLICE [--capitals WATER.CAPITALS.JSON]
                  [--slice-name NAME] -o river.prefab [--json river.json]
  river2prefab.py from-prefab SLICE river.prefab [-o out.dynamicslice]
"""
import argparse, json, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from osv3 import parse_objectstream, encode_objectstream
import river_io

BEZIER_TYPE_HASH = 2612576363626472641  # AZ::u64 spline-type id for BezierSpline
TRANSFORM_COMPONENT = '{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0} TransformComponent'

_next_id = [1]
def nid():
    _next_id[0] += 1
    return _next_id[0]


def _tm_translate(tm):
    """AZ::Transform (column-major 3x4) -> [tx, ty, tz]."""
    return [tm[9], tm[10], tm[11]] if tm else [0.0, 0.0, 0.0]


def _spline_component(points, closed, granularity):
    return {
        '$type': 'EditorSplineComponent', 'Id': nid(),
        'Visible': True,
        'Configuration': {
            'Spline Type': BEZIER_TYPE_HASH,
            'Spline': {
                '$type': 'BezierSpline',
                'BaseClass1': {
                    '$type': 'Spline',
                    'Vertices': {'element': [p['pos'] for p in points]},
                    'Closed': closed,
                },
                'Bezier Data': {'element': [{
                    'Forward': p.get('forward', p['pos']),
                    'Back': p.get('back', p['pos']),
                    'Angle': p.get('angle', 0.0),
                } for p in points]},
                'Granularity': granularity,
            },
        },
    }


def to_prefab(slice_path, out, json_out, capitals=None, slice_name=None):
    raw = open(slice_path, 'rb').read()
    m = river_io.extract(raw)
    name = slice_name or os.path.splitext(os.path.basename(slice_path))[0]
    pos = _tm_translate(m.get('m_worldTM'))
    if capitals:
        caps = json.load(open(capitals))
        sn = name.lower() + '.dynamicslice'
        for c in caps.get('Capitals', []):
            cn = c.get('sliceName', '').lower().replace('\\', '/')
            cn = cn[:-len('.dynamicslice')] if cn.endswith('.dynamicslice') else cn
            if cn.endswith(name.lower()):
                wp = c['worldPosition']
                pos = [wp['x'], wp['y'], wp['z']]
                break
    eid = 'Entity_[2]'
    comps = {
        'Component_[0]': {'$type': TRANSFORM_COMPONENT, 'Id': nid(),
                          'Transform Data': {'Translate': pos},
                          'Parent Entity': 'Entity_[1]'},
        'Component_[1]': _spline_component(
            m['spline']['points'], m['spline']['closed'],
            m['spline']['granularity']),
    }
    prefab = {
        'ContainerEntity': {
            'Id': 'Entity_[1]', 'Name': 'Level',
            'Components': {'Component_[0]': {
                '$type': TRANSFORM_COMPONENT, 'Id': nid(),
                'Transform Data': {'Translate': [0.0, 0.0, 0.0]},
                'Parent Entity': ''}}},
        'Entities': {eid: {'Id': eid, 'Name': name, 'Components': comps}},
    }
    with open(out, 'w') as f:
        json.dump(prefab, f, indent=2)
    if json_out:
        sidecar = {'slice': os.path.basename(slice_path),
                   'river': m['river'],
                   'm_worldTM': m.get('m_worldTM'),
                   'm_localTM': m.get('m_localTM')}
        with open(json_out, 'w') as f:
            json.dump(sidecar, f, indent=2)
    print('wrote %s (%d spline points, pos=%s)' %
          (out, len(m['spline']['points']), pos))


def _find_spline_component(prefab):
    for ent in prefab.get('Entities', {}).values():
        for c in ent.get('Components', {}).values():
            if c.get('$type') == 'EditorSplineComponent':
                return c
    raise KeyError('no EditorSplineComponent in prefab')


def from_prefab(slice_path, prefab_path, out):
    prefab = json.load(open(prefab_path))
    comp = _find_spline_component(prefab)
    spline = comp['Configuration']['Spline']
    base = spline['BaseClass1']
    verts = base['Vertices']['element']
    bds = spline['Bezier Data']['element']
    raw = open(slice_path, 'rb').read()
    m = river_io.extract(raw)
    pts = []
    for i, v in enumerate(verts):
        p = {'pos': v}
        if i < len(bds):
            p['forward'] = bds[i]['Forward']
            p['back'] = bds[i]['Back']
            p['angle'] = bds[i].get('Angle', 0.0)
        pts.append(p)
    m['spline']['points'] = pts
    m['spline']['closed'] = bool(base.get('Closed', m['spline']['closed']))
    m['spline']['granularity'] = spline.get('Granularity',
                                            m['spline']['granularity'])
    result = river_io.apply(m, raw)
    open(out, 'wb').write(result)
    print('wrote %s (%d spline points)' % (out, len(pts)))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    t = sub.add_parser('to-prefab')
    t.add_argument('slice')
    t.add_argument('-o', '--out', required=True)
    t.add_argument('--json')
    t.add_argument('--capitals')
    t.add_argument('--slice-name')
    f = sub.add_parser('from-prefab')
    f.add_argument('slice')
    f.add_argument('prefab')
    f.add_argument('-o', '--out', required=True)
    a = ap.parse_args()
    if a.cmd == 'to-prefab':
        to_prefab(a.slice, a.out, a.json, a.capitals, a.slice_name)
    else:
        from_prefab(a.slice, a.prefab, a.out)


if __name__ == '__main__':
    main()
