#!/usr/bin/env python3
"""Generate an O3DE level from an NW Coatlicue level dir (terrain.json +
regions/<r_+xx_+yy>/region.heightmap).

Output under <out>:
  Levels/<level>/<level>.prefab      level with one TerrainSpawner+HeightGradient
                                    entity pair per region
  Levels/<level>/heightmaps/<region>.tif   16-bit grayscale TIFF source images
                                    (NW row order kept: O3DE's image-gradient
                                    uv.y already matches row-0-is-high-y)
  Levels/<level>/terrain.json        verbatim copy — level source of truth for
                                    oceanLevel/worldMaterialAssetPath etc.

Height mapping (honours mountainHeight): the TerrainSpawner's AABB z-range is
0..mountainHeight, and O3DE lerp's the 0..1 gradient over it, so
world height = raw/65535 * mountainHeight — exactly the NW decode.
NW row 0 = highest world y; O3DE's gradient pipeline maps world y to image
rows the same way, so rows are written UNFLIPPED (verified in-editor).

Asset GUIDs: AZ CreateName = sha1(lowercase source path)[0:16] + uuid v5
variant bits (verified against Lockstep m2-remoteplayer-slice.md table).
"""
import argparse, hashlib, json, os, re, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from heightmap import decode, encode
import terrainjson as _tj

TRANSFORM_COMPONENT = '{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0} TransformComponent'


def asset_guid(path):
    h = bytearray(hashlib.sha1(path.lower().encode()).digest()[:16])
    h[6] = (h[6] & 0x0f) | 0x50
    h[8] = (h[8] & 0x3f) | 0x80
    return str(uuid.UUID(bytes=bytes(h))).upper()


def region_index(name):
    m = re.match(r'r_([+-]\d+)_([+-]\d+)$', name)
    if not m:
        raise ValueError('bad region dir %s' % name)
    return int(m.group(1)), int(m.group(2))


_next_id = [1]
def nid():
    _next_id[0] += 1
    return _next_id[0]


def entity(name, comps):
    eid = 'Entity_[%d]' % nid()
    return eid, {'Id': eid, 'Name': name, 'Components': {
        'Component_[%d]' % i: c for i, c in enumerate(comps)}}


def comp(t, conf=None, **kw):
    c = {'$type': t, 'Id': nid()}
    if conf is not None:
        c['Configuration'] = conf
    c.update(kw)
    return c


def transform(tx, ty, tz, parent=''):
    # TransformComponent serializes fields directly on the component object
    # (no 'Configuration' wrapper); 'Parent Entity' key must always be present.
    return {'$type': TRANSFORM_COMPONENT, 'Id': nid(),
            'Transform Data': {'Translate': [tx, ty, tz]},
            'Parent Entity': parent}


def build_prefab(level, regions):
    """regions: [(name,(ix,iy),size,mountainHeight,img_hint)]"""
    ents = {}
    for name, (ix, iy), size, mh, hint in regions:
        cx, cy = ix * size + size / 2.0, iy * size + size / 2.0
        spawn, grad = 'TerrainSpawner_' + name, 'HeightGradient_' + name
        seid, se = entity(spawn, [
            transform(cx, cy, mh / 2.0, parent='Entity_[1]'),
            comp('EditorAxisAlignedBoxShapeComponent',
                 AxisAlignedBoxShape={'Configuration': {
                    'Dimensions': [size, size, mh]}}),
            comp('EditorTerrainLayerSpawnerComponent'),
            comp('EditorTerrainHeightGradientListComponent', {
                'GradientEntities': ['__GRAD__']}),
        ])
        geid, ge = entity(grad, [
            transform(0.0, 0.0, 0.0, parent=seid),
            comp('EditorReferenceShapeComponent', {'ShapeEntityId': seid}),
            comp('EditorGradientTransformComponent', {
                'ShapeReference': '',
                'Bounds': [size, size, mh],
                'Translate': [cx, cy, mh / 2.0]}),
            {'$type': 'EditorImageGradientComponent', 'Id': nid(),
             'Previewer': {'BoundsEntity': ''},
             'Configuration': {'StreamingImageAsset': {
                 'assetId': {'guid': '{%s}' % asset_guid(hint), 'subId': 1000},
                 'assetHint': hint + '.streamingimage'}}},
        ])
        # backpatch the gradient entity ref
        for c in se['Components'].values():
            if c['$type'] == 'EditorTerrainHeightGradientListComponent':
                c['Configuration']['GradientEntities'] = [geid]
        ents[seid] = se
        ents[geid] = ge
    mh = regions[0][3] if regions else 2048.0
    container = {
        'Id': 'Entity_[1]', 'Name': 'Level',
        'Components': {'Component_[%d]' % i: c for i, c in enumerate([
            transform(0.0, 0.0, 0.0),
            comp('EditorPrefabComponent'),
            comp('EditorTerrainWorldComponent', {
                'MinHeight': 0.0, 'MaxHeight': mh,
                'HeightQueryResolution': 1.0,
                'SurfaceDataQueryResolution': 1.0}),
            comp('EditorTerrainWorldRendererComponent'),
        ])}}
    return {'ContainerEntity': container, 'Entities': ents}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('level_dir', help='NW level dir containing terrain.json + regions/')
    ap.add_argument('out', help='output project root')
    ap.add_argument('--name', help='level name (default: dir name)')
    a = ap.parse_args()
    src = a.level_dir.rstrip('/')
    level = a.name or os.path.basename(src)
    tj = _tj.load(os.path.join(src, 'terrain.json'))
    mh = float(tj.get('mountainHeight', 2048.0))
    lvl_dir = os.path.join(a.out, 'Levels', level)
    img_dir = os.path.join(lvl_dir, 'heightmaps')
    os.makedirs(img_dir, exist_ok=True)
    regions = []
    rdir = os.path.join(src, 'regions')
    for rname in sorted(os.listdir(rdir)):
        hm_path = os.path.join(rdir, rname, 'region.heightmap')
        if not os.path.isfile(hm_path):
            continue
        ix, iy = region_index(rname)
        hm = decode(open(hm_path, 'rb').read())
        # NOTE: no row flip. O3DE's image-gradient pipeline already maps
        # uv.y the opposite way to world y, matching NW's row-0-is-high-y.
        tif = os.path.join(img_dir, rname + '.tif')
        with open(tif, 'wb') as f:
            f.write(encode(hm, lzw=True))
        # .assetinfo pins the GSI16 preset (R16 lossless) so the image builder
        # keeps 16-bit height precision instead of BC1-compressing to Albedo.
        with open(tif + '.assetinfo', 'w') as f:
            f.write('<ObjectStream version="3">\n'
                    '\t<Class name="TextureSettings" version="1" '
                    'type="{980132FF-C450-425D-8AE0-BD96A8486177}">\n'
                    '\t\t<Class name="AZ::Uuid" field="PresetID" '
                    'value="{181FE328-5408-4722-895F-1BB61803997B}" '
                    'type="{E152C105-A133-4D03-BBF8-3D4B2FBA3E2A}"/>\n'
                    '\t</Class>\n</ObjectStream>\n')
        hint = 'levels/%s/heightmaps/%s.tif' % (level.lower(), rname)
        regions.append((rname, (ix, iy), hm.w, mh, hint))
        print('  %s: %dx%d -> %s' % (rname, hm.w, hm.h, tif))
    prefab = build_prefab(level, regions)
    ppath = os.path.join(lvl_dir, level + '.prefab')
    with open(ppath, 'w') as f:
        json.dump(prefab, f, indent=1)
    import shutil
    shutil.copyfile(os.path.join(src, 'terrain.json'), os.path.join(lvl_dir, 'terrain.json'))
    print('wrote %s (%d regions)' % (ppath, len(regions)))


if __name__ == '__main__':
    main()
