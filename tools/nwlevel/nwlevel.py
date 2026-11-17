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
import os
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


def _merge_slice(prefab, slice_raw):
    """Append a slice's entities to a level prefab, renumbering ids."""
    spf, skipped = slice2prefab.convert(
        slice_raw, prefab['ContainerEntity']['Name'])
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
    # Atom editor components serialize namespaced (AZ::Render::...) under
    # Controller.Configuration; sky assets use the engine's default HDRi
    # preset (goegap) which AP already produces as streamingimages.
    skybox_asset = {
        'assetId': {'guid': '{215E47FD-D181-5832-B1AB-91673ABF6399}',
                    'subId': 1000},
        'assetHint': 'lightingpresets/highcontrast/'
                     'goegap_4k_skyboxcm.exr.streamingimage'}
    ibl_guid = '{3FD09945-D0F2-55C8-B9AF-B2FD421FE3BE}'
    out = {}
    for name, rot, comps in (
        ('sun', (-55.0, 0.0, 25.0),
         [nw2level.comp('AZ::Render::EditorDirectionalLightComponent',
                        Controller={'Configuration': {
                            'Intensity': 1.0,
                            'CameraEntityId': '',
                            'ShadowFilterMethod': 1}})]),
        ('sky', None,
         [nw2level.comp('AZ::Render::EditorHDRiSkyboxComponent',
                        Controller={'Configuration': {
                            'CubemapAsset': skybox_asset}}),
          nw2level.comp('AZ::Render::EditorImageBasedLightComponent',
                        Controller={'Configuration': {
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
    ap.add_argument('--slice', required=True,
                    help='.dynamicslice to merge in')
    ap.add_argument('--regions', nargs='*', default=None,
                    help='region dir names to include (default: all)')
    ap.add_argument('--name', required=True, help='level name')
    ap.add_argument('--out', required=True, help='project root')
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
        tif = os.path.join(img_dir, rname + '.tif')
        with open(tif, 'wb') as f:
            f.write(encode(hm, lzw=True))
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
    prefab = nw2level.build_prefab(a.name, regions)
    prefab['ContainerEntity']['Name'] = a.name

    slice_raw = open(a.slice, 'rb').read()
    n, skipped = _merge_slice(prefab, slice_raw)
    print('slice entities merged: %d (%d comp types unmapped)'
          % (n, len(skipped)))

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
