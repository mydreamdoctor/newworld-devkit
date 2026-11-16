#!/usr/bin/env python3
"""NW Coatlicue region streaming layer (stage 3.3 viewing tool).

Reads a level's region layout from the client paks (or an extracted dir):
  sharedassets/coatlicue/<level>/regions/r_+XX_+YY/
      region.heightmap, region.tractmap.tif,
      capitals/<category>/<category>.capitals.json

Commands:
  scan LEVEL [--assets GLOB|DIR] [-o regions.json]
      list regions + capital categories/entry counts -> JSON model
  worldmap LEVEL REGIONS_JSON -o out.prefab [--capitals]
      emit an O3DE prefab showing the r_+XX_+YY grid (one box entity per
      region at world position; --capitals also emits one entity per
      capital entry, capped at 2000 per region)
  open LEVEL REGION CAPITAL_INDEX|SLICE_NAME [--assets GLOB|DIR] -o out.prefab
      resolve a capital entry -> its root .dynamicslice -> prefab (rivers
      get the full EditorSplineComponent; generic slices get entities +
      transforms with unmapped components listed in the sidecar)

Region grid: r_+XX_+YY = 2048 m cell, world origin (XX*2048, YY*2048).
"""
import argparse, glob, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paks import Paks
import river_io, slice2prefab, river2prefab
from river2prefab import nid, TRANSFORM_COMPONENT

REGION_SIZE = 2048.0
RRE = re.compile(r'r_([+-]\d+)_([+-]\d+)$')


def _open_source(level, assets):
    """Return (read_fn, names) over the paks or an extracted directory."""
    if assets and os.path.isdir(assets) and not glob.glob(
            os.path.join(assets, '*.pak')):
        root = assets
        def read(n):
            with open(os.path.join(root, n), 'rb') as f:
                return f.read()
        names = []
        for dp, _, fns in os.walk(os.path.join(root,
                                               'sharedassets/coatlicue', level)):
            for fn in fns:
                names.append(os.path.relpath(os.path.join(dp, fn), root))
        return read, names
    paks = Paks([os.path.join(assets, '*.pak')] if os.path.isdir(assets)
                else [assets])
    return paks.read, sorted(paks.idx)


def region_index(name):
    m = RRE.match(name)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _quat_euler(q):
    """{x,y,z,w} -> ZYX euler degrees [rx,ry,rz]; None if identity."""
    import math
    if not q:
        return None
    x, y, z, w = q['x'], q['y'], q['z'], q['w']
    rx = math.degrees(math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)))
    ry = math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))))
    rz = math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))
    if abs(rx) < 1e-6 and abs(ry) < 1e-6 and abs(rz) < 1e-6:
        return None
    return [rx, ry, rz]


def scan(level, assets):
    read, names = _open_source(level, assets)
    prefix = 'sharedassets/coatlicue/%s/regions/' % level
    model = {'level': level, 'regionSize': REGION_SIZE, 'regions': {}}
    for n in names:
        if not n.startswith(prefix):
            continue
        rel = n[len(prefix):]
        rname = rel.split('/')[0]
        if not RRE.match(rname):
            continue
        reg = model['regions'].setdefault(rname, {'files': [], 'capitals': {}})
        rest = rel[len(rname) + 1:]
        if rest.startswith('capitals/') and rest.endswith('.capitals.json'):
            cat = rest.split('/')[1]
            try:
                caps = json.loads(read(n))
                reg['capitals'][cat] = len(caps.get('Capitals', []))
            except Exception:
                reg['capitals'][cat] = -1
        elif rest:
            reg['files'].append(rest)
    return model


def worldmap(level, model, out, with_capitals=False, assets=None):
    read = _open_source(level, assets)[0] if with_capitals else None
    ents = {}
    i = 1
    cap_total = 0
    for rname, reg in sorted(model['regions'].items()):
        rc = region_index(rname)
        if not rc:
            continue
        i += 1
        eid = 'Entity_[%d]' % i
        cx, cy = rc[0] * REGION_SIZE + REGION_SIZE / 2, \
            rc[1] * REGION_SIZE + REGION_SIZE / 2
        comps = {
            'Component_[0]': {'$type': TRANSFORM_COMPONENT, 'Id': nid(),
                              'Transform Data': {'Translate': [cx, cy, 0.0]},
                              'Parent Entity': 'Entity_[1]'},
            'Component_[1]': {'$type': 'EditorAxisAlignedBoxShapeComponent',
                              'Id': nid(),
                              'AxisAlignedBoxShape': {'Configuration': {
                                  'Dimensions': [REGION_SIZE, REGION_SIZE,
                                                 1.0]}}},
        }
        ents[eid] = {'Id': eid, 'Name': rname, 'Components': comps}
        if not with_capitals:
            continue
        for cat in sorted(reg['capitals']):
            cpath = ('sharedassets/coatlicue/%s/regions/%s/capitals/%s/'
                     '%s.capitals.json' % (level, rname, cat, cat))
            try:
                entries = json.loads(read(cpath)).get('Capitals', [])
            except Exception:
                continue
            for k, c in enumerate(entries):
                if cap_total >= 2000:
                    break
                wp = c.get('worldPosition', {})
                sn = c.get('sliceName', '') or '<none>'
                i += 1
                ceid = 'Entity_[%d]' % i
                cap_total += 1
                ents[ceid] = {
                    'Id': ceid,
                    'Name': '%s/%s[%d] %s' % (rname, cat, k,
                                             os.path.basename(sn)),
                    'Components': {'Component_[0]': {
                        '$type': TRANSFORM_COMPONENT, 'Id': nid(),
                        'Transform Data': {'Translate':
                                           [wp.get('x', 0), wp.get('y', 0),
                                            wp.get('z', 0)]},
                        'Parent Entity': 'Entity_[1]'}}}
    prefab = {
        'ContainerEntity': {
            'Id': 'Entity_[1]', 'Name': '%s_worldmap' % level,
            'Components': {'Component_[0]': {
                '$type': TRANSFORM_COMPONENT, 'Id': nid(),
                'Transform Data': {'Translate': [0.0, 0.0, 0.0]},
                'Parent Entity': ''}}},
        'Entities': ents}
    with open(out, 'w') as f:
        json.dump(prefab, f, indent=2)
    print('wrote %s: %d regions, %d capital markers' %
          (out, len(model['regions']), cap_total))


def open_capital(level, region, which, assets, out):
    read, _ = _open_source(level, assets)
    found = None
    for n in sorted(glob.glob('')):
        pass
    # find the capital entry across the region's categories
    prefix = ('sharedassets/coatlicue/%s/regions/%s/capitals/'
              % (level, region))
    read_names = _open_source(level, assets)[1]
    for n in read_names:
        if not (n.startswith(prefix) and n.endswith('.capitals.json')):
            continue
        cat = n[len(prefix):].split('/')[0]
        try:
            entries = json.loads(read(n)).get('Capitals', [])
        except Exception:
            continue
        for k, c in enumerate(entries):
            sn = (c.get('sliceName') or '').replace('\\', '/')
            key = '%s[%d]' % (cat, k)
            if which == key or (sn and sn != '<PLOT>'
                                and sn.lower().endswith(which.lower())):
                found = (cat, k, c, n)
                break
        if found:
            break
    if not found:
        raise SystemExit('capital %r not found under %s' % (which, prefix))
    cat, k, c, cfile = found
    sn = (c.get('sliceName') or '').replace('\\', '/')
    if not sn or sn == '<PLOT>':
        raise SystemExit('capital %s[%d] has sliceName <PLOT> '
                         '(procedural, no root slice)' % (cat, k))
    spath = sn if sn.endswith('.dynamicslice') else sn + '.dynamicslice'
    raw = read(spath)
    prefab, skipped = slice2prefab.convert(
        raw, os.path.splitext(os.path.basename(spath))[0])
    # placement entity: capital world transform (the slice's own transforms
    # are in slice space — the capital transforms slice space -> world)
    wp = c.get('worldPosition', {})
    rot = _quat_euler(c.get('rotation'))
    peid = 'Entity_[placement]'
    td = {'Translate': [wp.get('x', 0), wp.get('y', 0), wp.get('z', 0)]}
    if rot:
        td['Rotate'] = rot
    prefab['Entities'][peid] = {
        'Id': peid, 'Name': 'CapitalPlacement_%s%d' % (cat, k),
        'Components': {'Component_[0]': {
            '$type': TRANSFORM_COMPONENT, 'Id': nid(),
            'Transform Data': td, 'Parent Entity': 'Entity_[1]'}}}
    for e in prefab['Entities'].values():
        if e['Id'] == peid:
            continue
        for comp in e['Components'].values():
            if comp['$type'] == TRANSFORM_COMPONENT:
                comp['Parent Entity'] = peid
    prefab['ContainerEntity']['Name'] = '%s_%s%d' % (region, cat, k)
    with open(out, 'w') as f:
        json.dump(prefab, f, indent=2)
    sidecar = out[:-len('.prefab')] + '.sidecar.json' \
        if out.endswith('.prefab') else out + '.sidecar.json'
    with open(sidecar, 'w') as f:
        json.dump({'capital': c, 'capitals_file': cfile, 'slice': spath,
                   'worldPosition': wp, 'skipped': skipped}, f, indent=2)
    print('opened %s -> %s (capital %s[%d] at %s; %d unmapped component kinds)'
          % (spath, out, cat, k,
             [wp.get('x'), wp.get('y'), wp.get('z')], len(skipped)))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('scan')
    s.add_argument('level')
    s.add_argument('--assets', default='/home/lachlan/nwclient-frozen-20261022/assets')
    s.add_argument('-o', '--out')
    w = sub.add_parser('worldmap')
    w.add_argument('level')
    w.add_argument('model')
    w.add_argument('-o', '--out', required=True)
    w.add_argument('--capitals', action='store_true')
    w.add_argument('--assets', default='/home/lachlan/nwclient-frozen-20261022/assets')
    o = sub.add_parser('open')
    o.add_argument('level')
    o.add_argument('region')
    o.add_argument('which', help='category[index] or slice name tail')
    o.add_argument('--assets', default='/home/lachlan/nwclient-frozen-20261022/assets')
    o.add_argument('-o', '--out', required=True)
    a = ap.parse_args()
    if a.cmd == 'scan':
        model = scan(a.level, a.assets)
        txt = json.dumps(model, indent=2)
        if a.out:
            open(a.out, 'w').write(txt + '\n')
        else:
            print(txt)
    elif a.cmd == 'worldmap':
        worldmap(a.level, json.load(open(a.model)), a.out, a.capitals, a.assets)
    else:
        open_capital(a.level, a.region, a.which, a.assets, a.out)


if __name__ == '__main__':
    main()
