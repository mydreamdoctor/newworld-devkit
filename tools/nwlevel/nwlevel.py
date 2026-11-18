#!/usr/bin/env python3
"""Composed NW region level: terrain + slice entities + sun/sky + camera.

Combines, in one .prefab level:

  - terrain heightfield from a client-dump level dir
    (terrain.json + r_+XX_+YY/region.heightmap) via nw2level,
  - entities from a .dynamicslice via slice2prefab (with the mapped
    component set: transforms, splines, polygon prisms),
  - a directional-light sun, a physical sky, and an editor camera
    framed on the slice entity cluster.

Usage:
  nwlevel.py LEVEL_DIR --slice SLICE --regions r_+03_+01 --name nw_r0301 \
      --out PROJECT_ROOT
"""
import argparse
import json
import math
import glob
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'nwterrain'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'nwslice'))

import nw2level
import terrainjson as _tj
from heightmap import decode, encode
import slice2prefab


def _max_eid(prefab):
    hi = 0
    for k in list(prefab.get('Entities', {})) + ['Entity_[1]']:
        if k.startswith('Entity_[') and k.endswith(']'):
            hi = max(hi, int(k[8:-1]))
    return hi


def _slice_resolver(dirs):
    """PrefabSpawnerComponent ref -> slice bytes, indexed by basename."""
    idx = {}
    for d in dirs:
        for p in glob.glob(os.path.join(d, '**', '*.dynamicslice'),
                           recursive=True):
            idx[os.path.basename(p).lower()] = p

    def resolve(ref):
        p = idx.get(os.path.basename(ref.replace('\\', '/')).lower())
        return open(p, 'rb').read() if p else None
    return resolve


def _merge_slice(prefab, slice_raw, resolver=None, missing=None):
    """Append a slice's entities to a level prefab, renumbering ids."""
    spf, skipped = slice2prefab.convert(
        slice_raw, prefab['ContainerEntity']['Name'],
        resolver=resolver, missing=missing)
    base = _max_eid(prefab)
    remap = {}
    for k in sorted(spf['Entities'], key=lambda s: int(s[8:-1])):
        base += 1
        remap[k] = 'Entity_[%d]' % base
    for k, e in spf['Entities'].items():
        e = json.loads(json.dumps(e))
        e['Id'] = remap[k]
        # all slice entities parent to the level container Entity_[1]
        prefab['Entities'][remap[k]] = e
    return len(remap), skipped


def _aux_ents(prefab, camera_pos, camera_rot):
    # Physical sky replaces the goegap HDRi photo skybox (the photograph was
    # visible through geometry gaps); the goegap IBL pair stays for ambient
    # lighting only -- it is not rendered.
    ibl_guid = '{3FD09945-D0F2-55C8-B9AF-B2FD421FE3BE}'
    out = {}
    for name, rot, comps in (
        ('sun', (-55.0, 0.0, 25.0),
         [nw2level.comp('AZ::Render::EditorDirectionalLightComponent',
                        Controller={'Configuration': {
                            'Intensity': 4.0,
                            'CameraEntityId': '',
                            'ShadowFilterMethod': 1}})]),
        ('sky', None,
         [nw2level.comp('AZ::Render::EditorPhysicalSkyComponent',
                        Controller={'Configuration': {}}),
          nw2level.comp('AZ::Render::EditorImageBasedLightComponent',
                        Controller={'Configuration': {
                            'exposure': 2.0,
                            'diffuseImageAsset': {
                                'assetId': {'guid': ibl_guid, 'subId': 3000},
                                'assetHint': 'lightingpresets/highcontrast/'
                                             'goegap_4k_iblglobalcm_ibldiffuse'
                                             '.exr.streamingimage'},
                            'specularImageAsset': {
                                'assetId': {'guid': ibl_guid, 'subId': 2000},
                                'assetHint': 'lightingpresets/highcontrast/'
                                             'goegap_4k_iblglobalcm_iblspecular'
                                             '.exr.streamingimage'}}})]),
        ('devkit_camera', list(camera_rot),
         [nw2level.comp(
             '{CA11DA46-29FF-4083-B5F6-E02C3A8C3A3D} '
             'EditorCameraComponent')]),
    ):
        pos = camera_pos if name == 'devkit_camera' else (0.0, 0.0, 0.0)
        tc = nw2level.transform(*pos, parent='Entity_[1]')
        if rot:
            tc['Transform Data']['Rotate'] = rot
        eid, e = nw2level.entity(name, [tc] + comps)
        out[eid] = e
    return out


def _centroid(prefab):
    pts = []
    for e in prefab['Entities'].values():
        for c in e['Components'].values():
            td = c.get('Transform Data')
            if td:
                pts.append(td.get('Translate', [0, 0, 0]))
                break
    if not pts:
        return (0.0, 0.0, 0.0)
    n = len(pts)
    return (sum(p[0] for p in pts) / n,
            sum(p[1] for p in pts) / n,
            sum(p[2] for p in pts) / n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('level_dir',
                    help='NW level dir with terrain.json; regions are '
                         'r_* dirs inside it (or inside a regions/ subdir)')
    ap.add_argument('--slice', required=True, nargs='+',
                    help='.dynamicslice file(s) to merge in')
    ap.add_argument('--slicedir', nargs='*', default=[],
                    help='dirs indexed for nested-slice spawner '
                         'resolution (PrefabSpawnerComponent m_sliceAsset '
                         'refs resolve by basename)')
    ap.add_argument('--regions', nargs='*', default=None,
                    help='region dir names to include (default: all)')
    ap.add_argument('--name', required=True, help='level name')
    ap.add_argument('--out', required=True, help='project root')
    ap.add_argument('--at', nargs=3, type=float, metavar=('X', 'Y', 'Z'),
                    default=None,
                    help='world offset for merged slice entities (the '
                         'position where the world map spawns the '
                         'composition slice)')
    ap.add_argument('--chunks', type=int, default=0,
                    help='write merged slice entities out to this many '
                         'chunk prefabs under <level>/chunks/ instead of '
                         'into the level prefab; the level stays small and '
                         'the chunks are instantiated progressively by the '
                         'auto-open script (keeps the editor responsive)')
    ap.add_argument('--bake-cookies', action='store_true',
                    help='bake capital cookie flattens into the TIFF '
                         '(legacy — default is raw TIFF + NWCapital gem '
                         'stamps at sample time)')
    a = ap.parse_args()

    src = a.level_dir.rstrip('/')
    tj = _tj.load(os.path.join(src, 'terrain.json'))
    mh = float(tj.get('mountainHeight', 2048.0))
    lvl_dir = os.path.join(a.out, 'Levels', a.name)
    img_dir = os.path.join(lvl_dir, 'heightmaps')
    os.makedirs(img_dir, exist_ok=True)

    rdir = os.path.join(src, 'regions')
    if not os.path.isdir(rdir):
        rdir = src
    regions = []
    all_cookies = {}
    for rname in sorted(os.listdir(rdir)):
        if not rname.startswith('r_'):
            continue
        if a.regions and rname not in a.regions:
            continue
        hm_path = os.path.join(rdir, rname, 'region.heightmap')
        if not os.path.isfile(hm_path):
            continue
        ix, iy = nw2level.region_index(rname)
        hm = decode(open(hm_path, 'rb').read())
        if a.bake_cookies:
            nw2level.apply_cookies(hm, os.path.dirname(hm_path), mh)
        else:
            all_cookies[rname] = nw2level.collect_cookies(
                os.path.dirname(hm_path))
        tif = os.path.join(img_dir, rname + '.tif')
        with open(tif, 'wb') as f:
            f.write(encode(hm, lzw=True, flip_y=False))
        with open(tif + '.assetinfo', 'w') as f:
            f.write('<ObjectStream version="3">\n'
                    '\t<Class name="TextureSettings" version="1" '
                    'type="{980132FF-C450-425D-8AE0-BD96A8486177}">\n'
                    '\t\t<Class name="AZ::Uuid" field="PresetID" '
                    'value="{181FE328-5408-4722-895F-1BB61803997B}" '
                    'type="{E152C105-A133-4D03-BBF8-3D4B2FBA3E2A}"/>\n'
                    '\t</Class>\n</ObjectStream>\n')
        hint = 'levels/%s/heightmaps/%s.tif' % (a.name.lower(), rname)
        regions.append((rname, (ix, iy), hm.w, mh, hint))
        print('  %s: %dx%d' % (rname, hm.w, hm.h))

    nw2level._next_id[0] = 1  # shared id counter
    # client terrain surface layers (regionmat splats + detail materials)
    surfaces = {}
    rms = glob.glob(os.path.join(src, 'terrainmat', '*.regionmat'))
    if rms:
        m = re.search(r'_(\d+)_(\d+)\.regionmat$', os.path.basename(rms[0]))
        tile = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        for rname, (ix, iy), _s, _m, _h in regions:
            if (ix, iy) == tile:
                surfaces[rname] = nw2level.build_surfaces(
                    a.name, src, a.out, rname)
    prefab = nw2level.build_prefab(a.name, regions, surfaces, all_cookies)
    prefab['ContainerEntity']['Name'] = a.name

    resolver = _slice_resolver(a.slicedir) if a.slicedir else None
    missing = set()
    merged_ids = []
    for spath in a.slice:
        slice_raw = open(spath, 'rb').read()
        n, skipped = _merge_slice(prefab, slice_raw,
                                  resolver=resolver, missing=missing)
        merged_ids.extend(sorted(prefab['Entities'],
                                 key=lambda s: int(s[8:-1]))[-n:])
        print('%s: %d entities merged (%d comp types unmapped)'
              % (os.path.basename(spath), n, len(skipped)))
    if missing:
        print('unresolved nested-slice refs:')
        for m in sorted(missing):
            print('   ', m)

    if a.at:
        nw2level._next_id[0] = _max_eid(prefab)  # merge remap bypassed nid()
        eid, pe = nw2level.entity(
            'SlicePlacement',
            [nw2level.transform(*a.at, parent='Entity_[1]')])
        prefab['Entities'][eid] = pe
        for k in merged_ids:
            c = prefab['Entities'][k]['Components'].get('Component_[0]', {})
            c['Parent Entity'] = eid
        print('placed %d slice entities under %s at %s'
              % (len(merged_ids), eid, a.at))

    if a.chunks and merged_ids:
        chunk_dir = os.path.join(lvl_dir, 'chunks')
        os.makedirs(chunk_dir, exist_ok=True)
        at = a.at or (0.0, 0.0, 0.0)

        def _ent_pos(k):
            for c in prefab['Entities'][k]['Components'].values():
                if 'Transform Data' in c:
                    return c['Transform Data']['Translate']
            return (0.0, 0.0, 0.0)

        # centre-out order: the arena proper appears before far-flung art
        ids = sorted(merged_ids,
                     key=lambda k: sum((p - q) ** 2 for p, q in
                                       zip(_ent_pos(k), at)))
        per = (len(ids) + a.chunks - 1) // a.chunks
        for ci in range(a.chunks):
            group = ids[ci * per:(ci + 1) * per]
            if not group:
                break
            nid0 = [1]

            def _cid():
                nid0[0] += 1
                return nid0[0]

            cname = 'chunk_%02d' % ci
            cpf = {
                'ContainerEntity': {
                    'Id': 'Entity_[1]', 'Name': cname,
                    'Components': {
                        'Component_[0]': {
                            '$type': nw2level.TRANSFORM_COMPONENT,
                            'Id': _cid(),
                            'Transform Data': {'Translate': [0.0, 0.0, 0.0]},
                            'Parent Entity': ''},
                        'Component_[1]': {'$type': 'EditorPrefabComponent',
                                          'Id': _cid()}}},
                'Entities': {}}
            root = 'Entity_[%d]' % _cid()
            cpf['Entities'][root] = {
                'Id': root, 'Name': 'SlicePlacement',
                'Components': {
                    'Component_[0]': {
                        '$type': nw2level.TRANSFORM_COMPONENT,
                        'Id': _cid(),
                        'Transform Data': {'Translate': list(at)},
                        'Parent Entity': 'Entity_[1]'}}}
            for k in group:
                e = prefab['Entities'].pop(k)
                for c in e['Components'].values():
                    if 'Transform Data' in c:
                        c['Parent Entity'] = root
                        break
                cpf['Entities'][k] = e
            cpath = os.path.join(chunk_dir, cname + '.prefab')
            with open(cpath, 'w') as f:
                json.dump(cpf, f, indent=1)
            print('  %s: %d entities' % (cname, len(group)))
        print('wrote %d chunk prefabs to %s' % (ci + 1, chunk_dir))

    if a.chunks and a.at:
        cx, cy, cz = a.at  # art moved to chunks; aim at the placement
    else:
        cx, cy, cz = _centroid(prefab)
    cam = (cx, cy - 300.0, cz + 220.0)
    rot = (-35.0, 0.0, 0.0)
    nw2level._next_id[0] = _max_eid(prefab)  # keep aux ids collision-free
    prefab['Entities'].update(_aux_ents(prefab, cam, rot))
    print('camera at %s toward centroid %s' % (cam, (cx, cy, cz)))

    ppath = os.path.join(lvl_dir, a.name + '.prefab')
    with open(ppath, 'w') as f:
        json.dump(prefab, f, indent=1)
    # NB: keep the copy under a non-*terrain.json name — the nw_terrain_builder
    # turns terrain.json into an intermediate <level>.prefab, which collides
    # with the composed source prefab written above.
    shutil.copyfile(os.path.join(src, 'terrain.json'),
                    os.path.join(lvl_dir, 'terrain_src.json'))
    print('wrote %s (%d entities)' % (ppath, len(prefab['Entities'])))


if __name__ == '__main__':
    main()
