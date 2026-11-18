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
import argparse, glob, hashlib, json, os, re, sys, uuid, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               '..', 'nwmat'))
from heightmap import decode, encode
import terrainjson as _tj
import mtl as _mtl
import dds as _dds

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


def _img(hint):
    """StreamingImage assetId for a source image at scan-relative `hint`."""
    return {'assetId': {'guid': '{%s}' % asset_guid(hint), 'subId': 1000},
            'assetHint': hint + '.streamingimage'}


def _azmat(hint):
    """AzMaterial assetId for a source .material at scan-relative `hint`
    (product subId 0, verified against assetdb.sqlite)."""
    return {'assetId': {'guid': '{%s}' % asset_guid(hint), 'subId': 0},
            'assetHint': re.sub(r'\.material$', '.azmaterial', hint)}


_LAYER_RE = re.compile(
    r'field="Material" value="[^"]*hint=\{([^}]+)\}[^"]*"'
    r'.*?field="SplatMap" value="[^"]*hint=\{([^}]+)\}', re.S)

TERRAIN_DETAIL_MATERIALTYPE = \
    'Materials/Terrain/TerrainDetailMaterial.materialtype'


def _layer_material(sub, tex_rel, name):
    """StandardPBR-shaped properties on the TerrainDetailMaterial type —
    same property groups, plus the parallax overrides the terrain detail
    shader uses. tex_rel: {slot: scan-relative texture source path}."""
    props = {}
    if 'Diffuse' in tex_rel:
        props['baseColor'] = {'textureMap': tex_rel['Diffuse'],
                              'useTexture': True}
    if 'Bumpmap' in tex_rel:
        props['normal'] = {'textureMap': tex_rel['Bumpmap'],
                           'useTexture': True}
    if 'Specular' in tex_rel:
        props['specularF0'] = {'textureMap': tex_rel['Specular'],
                               'useTexture': True}
    return {'description': 'NW terrain layer %s' % name,
            'materialType': TERRAIN_DETAIL_MATERIALTYPE,
            'parentMaterial': '',
            'materialTypeVersion': 1,
            'properties': props}


def _find_tex(file_ref, out_root):
    """Locate an mtl texture ref as a project source; try the ref, the
    .dds swap, and a case-insensitive basename search under out_root."""
    ref = file_ref.replace('\\', '/').lstrip('/')
    for cand in (ref, os.path.splitext(ref)[0] + '.dds'):
        if os.path.isfile(os.path.join(out_root, cand)):
            return cand.replace(os.sep, '/')
    base = os.path.splitext(os.path.basename(ref))[0] + '.dds'
    for p in glob.glob(os.path.join(out_root, '**', base), recursive=True):
        return os.path.relpath(p, out_root).replace(os.sep, '/')
    for p in glob.glob(os.path.join(out_root, '**',
                                    os.path.basename(ref).lower()),
                       recursive=True):
        return os.path.relpath(p, out_root).replace(os.sep, '/')
    return None


def build_surfaces(level, src, out, rname):
    """Turn the client's regionmat (in <src>/terrainmat/) into O3DE terrain
    surface data for region `rname`:

      Levels/<level>/splats/<tag>.dds          reassembled splat images
      Levels/<level>/terrain_layers/<tag>.material  detail materials
      Levels/<level>/macro/macro_<c|n>.dds     reassembled macro maps

    Returns (gradients, materials, macros):
      gradients  [(tag_crc, splat_scan_hint)]
      materials  [(tag_crc, material_scan_hint)]
      macros     (color_hint, normal_hint) or None
    Only layers whose splat actually reassembles (>1KiB — most of the 65
    declared layers are empty stubs) are emitted.
    """
    tdir = os.path.join(src, 'terrainmat')
    rms = glob.glob(os.path.join(tdir, '*.regionmat'))
    if not rms:
        return [], [], None
    rm = open(rms[0], errors='replace').read()
    splat_dir = os.path.join(lvl := os.path.join(
        out, 'Levels', level), 'splats')
    layer_dir = os.path.join(lvl, 'terrain_layers')
    gradients, materials = [], []
    for mtl_hint, splat_hint in _LAYER_RE.findall(rm):
        # nw_arena_3v3_04_0.0.<tag>_splat.dds -> <tag>
        tag = os.path.basename(splat_hint)[:-len('.dds')].rsplit('.', 1)[-1]
        tag = tag.replace('_splat', '')
        # splat source lives beside the regionmat under terrainmat/
        splat_src = os.path.join(tdir, os.path.basename(splat_hint))
        if not os.path.isfile(splat_src):
            continue
        try:
            blob = _dds.reassemble(splat_src)
        except Exception:
            continue
        if len(blob) < 1024:
            continue
        os.makedirs(splat_dir, exist_ok=True)
        splat_name = tag + '_splat.dds'
        with open(os.path.join(splat_dir, splat_name), 'wb') as f:
            f.write(blob)
        # layer detail material from the client .mtl
        mtl_path = os.path.join(tdir, os.path.basename(mtl_hint))
        if not os.path.isfile(mtl_path):
            hits = glob.glob(os.path.join(
                src, '**', os.path.basename(mtl_hint)), recursive=True)
            if not hits:
                continue
            mtl_path = hits[0]
        m = _mtl.Mtl.load(mtl_path)
        if not m.subs:
            continue
        tex_rel = {}
        for slot, ref in m.subs[0].textures.items():
            rel = _find_tex(ref, out)
            if rel:
                tex_rel[slot] = rel
        os.makedirs(layer_dir, exist_ok=True)
        mat_name = tag + '.material'
        with open(os.path.join(layer_dir, mat_name), 'w') as f:
            json.dump(_layer_material(m.subs[0], tex_rel, tag), f, indent=1)
        crc = zlib.crc32(tag.encode()) & 0xFFFFFFFF
        gradients.append((crc,
                          'levels/%s/splats/%s' % (level.lower(), splat_name)))
        materials.append((crc,
                          'levels/%s/terrain_layers/%s'
                          % (level.lower(), mat_name)))
        print('  layer %-10s splat=%dB tex=%s' % (tag, len(blob), tex_rel))
    macros = None
    macro_dir = os.path.join(lvl, 'macro')
    mc, mn = {}, {}
    for kind, pat in (('color', 'macro_diff'), ('normal', 'macro_ddn')):
        hits = glob.glob(os.path.join(tdir, '*' + pat + '.dds'))
        if hits:
            try:
                blob = _dds.reassemble(hits[0])
            except Exception:
                continue
            if len(blob) >= 1024:
                os.makedirs(macro_dir, exist_ok=True)
                name = pat + '.dds'
                with open(os.path.join(macro_dir, name), 'wb') as f:
                    f.write(blob)
                (mc if kind == 'color' else mn)['hint'] = \
                    'levels/%s/macro/%s' % (level.lower(), name)
    if mc and mn:
        macros = (mc['hint'], mn['hint'])
    return gradients, materials, macros


def collect_cookies(region_dir):
    """Gather capital 'cookie' terrain stamps from every *.capitals.json
    beside region.heightmap. Returns a list of stamp dicts ready for
    serialization into a CapitalCookieGradientComponent config — the gem
    applies them at gradient-sample time, so the TIFF stays raw (the
    client also keeps its heightmap unflattened and stamps at load)."""
    cookies = []
    for fn in sorted(glob.glob(os.path.join(region_dir,
                                          '*.capitals.json'))):
        try:
            caps = json.load(open(fn))
        except Exception:
            continue
        for c in caps.get('Capitals', []):
            ck = c.get('cookie')
            if not ck:
                continue
            wp = c.get('worldPosition') or {}
            outer = float(ck.get('outerRadius', 0.0))
            if outer <= 0:
                continue
            cookies.append({
                'Position': [float(wp.get('x', 0)), float(wp.get('y', 0)),
                             float(wp.get('z', 0))],
                'InnerRadius': float(ck.get('innerRadius', 0.0)),
                'OuterRadius': outer,
                'MaxHeightBlend': float(ck.get('maxHeightBlend', 1.0)),
                'EdgeNoise': float(ck.get('edgeNoise', 0.0)),
                'EdgeNoiseFeatureSize': float(
                    ck.get('edgeNoiseFeatureSize', 0.0)),
                'GroundNoiseScale': float(ck.get('groundNoiseScale', 0.0)),
            })
            print('  cookie %s: flatten to %.1fm r %.0f-%.0f at (%.1f,%.1f)'
                  % (os.path.basename(fn), float(wp.get('z', 0)),
                     float(ck.get('innerRadius', 0.0)), outer,
                     float(wp.get('x', 0)), float(wp.get('y', 0))))
    return cookies


def apply_cookies(hm, region_dir, mountain_height):
    """Apply capital 'cookie' terrain flattens to a decoded Heightmap.

    Every *.capitals.json beside region.heightmap may carry capitals with a
    'cookie' block {innerRadius, outerRadius, maxHeightBlend,
    groundNoiseScale}. The client deforms the heightmap at runtime with
    these: full flatten to the capital's world z inside innerRadius,
    smoothstep blend back to the source height out to outerRadius
    (radii in metres; 1 texel = 1 m). groundNoiseScale adds 4D simplex
    noise on top — skipped when 0. maxHeightBlend is the flatten
    strength weight (1.0 = full flatten toward the capital z; deltas
    here exceed 40 m so it cannot be a metre cap).
    World mapping: pixel col = world x, row = h-1 - world y.
    Returns the number of cookies applied."""
    applied = 0
    scale = 65535.0 / mountain_height
    for fn in sorted(glob.glob(os.path.join(region_dir,
                                          '*.capitals.json'))):
        try:
            caps = json.load(open(fn))
        except Exception:
            continue
        for c in caps.get('Capitals', []):
            ck = c.get('cookie')
            if not ck:
                continue
            wp = c.get('worldPosition') or {}
            cx, cy = float(wp.get('x', 0)), float(wp.get('y', 0))
            cz = float(wp.get('z', 0))
            inner = float(ck.get('innerRadius', 0.0))
            outer = float(ck.get('outerRadius', inner))
            mhb = float(ck.get('maxHeightBlend', 0.0))
            if outer <= 0:
                continue
            flat_raw = max(0, min(65535, int(round(cz * scale))))
            x0, x1 = max(0, int(cx - outer - 1)), min(hm.w - 1,
                                                    int(cx + outer + 1))
            y0 = max(0, int(cy - outer - 1))
            y1 = min(hm.h - 1, int(cy + outer + 1))
            for wy in range(y0, y1 + 1):
                row = (hm.h - 1) - wy
                base = row * hm.w
                for wx in range(x0, x1 + 1):
                    dx, dy = wx - cx, wy - cy
                    d2 = dx * dx + dy * dy
                    if d2 > outer * outer:
                        continue
                    d = d2 ** 0.5
                    i = base + wx
                    cur = hm.raw[i]
                    if d <= inner:
                        new = flat_raw
                    else:
                        t = (d - inner) / (outer - inner)
                        s = t * t * (3.0 - 2.0 * t)
                        new = int(round(flat_raw * (1 - s) + cur * s))
                    if mhb < 1.0:
                        new = int(round(cur * (1 - mhb) + new * mhb))
                    hm.raw[i] = new
            applied += 1
            print('  cookie %s: flatten to %.1fm r %.0f-%.0f at (%.1f,%.1f)'
                  % (os.path.basename(fn), cz, inner, outer, cx, cy))
    return applied


NW_CAPITAL_STAMP_TYPE = \
    '{5D1A8E3B-4F6C-4A9D-8E2B-7C3F5A1D6E04} EditorCapitalCookieGradientComponent'


def build_prefab(level, regions, surfaces=None, cookies=None):
    """regions: [(name,(ix,iy),size,mountainHeight,img_hint)]
    surfaces: {region_name: (gradients, materials, macros)} from
    build_surfaces — detail-material/splat/macro bindings.
    cookies: {region_name: [cookie dicts]} from collect_cookies — emitted as
    an NWCapital stamp entity between the ImageGradient and the terrain
    height list so the TIFF stays raw and the gem stamps at sample time."""
    surfaces = surfaces or {}
    cookies = cookies or {}
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
             'Configuration': {'StreamingImageAsset': _img(hint)}},
        ])
        height_grad = geid
        if cookies.get(name):
            # capital cookie stamps: image gradient -> stamp -> terrain list
            steid, ste = entity('CapitalStamps_' + name, [
                transform(0.0, 0.0, 0.0, parent=seid),
                comp(NW_CAPITAL_STAMP_TYPE, {
                    'Gradient': {'GradientId': geid},
                    'Cookies': cookies[name],
                    'HeightMin': 0.0,
                    'HeightMax': mh}),
            ])
            ents[steid] = ste
            height_grad = steid
        # backpatch the gradient entity ref
        for c in se['Components'].values():
            if c['$type'] == 'EditorTerrainHeightGradientListComponent':
                c['Configuration']['GradientEntities'] = [height_grad]
        ents[seid] = se
        ents[geid] = ge
        gradients, materials, macros = surfaces.get(name, ([], [], None))
        grad_maps = []
        for crc, shint in gradients:
            sgid, sge = entity('SplatGradient_' + name + '_' + shint.rsplit(
                '/', 1)[-1].replace('_splat.dds', ''), [
                transform(0.0, 0.0, 0.0, parent=seid),
                comp('EditorReferenceShapeComponent', {'ShapeEntityId': seid}),
                comp('EditorGradientTransformComponent', {
                    'ShapeReference': '',
                    'Bounds': [size, size, mh],
                    'Translate': [cx, cy, mh / 2.0]}),
                {'$type': 'EditorImageGradientComponent', 'Id': nid(),
                 'Previewer': {'BoundsEntity': ''},
                 'Configuration': {'StreamingImageAsset': _img(shint)}},
            ])
            ents[sgid] = sge
            grad_maps.append({'Gradient Entity': sgid,
                              'Surface Tag': {'SurfaceTagCrc': crc}})
        if grad_maps:
            se['Components']['Component_[%d]' % len(se['Components'])] = comp(
                'EditorTerrainSurfaceGradientListComponent',
                {'Mappings': grad_maps})
        if materials:
            mat_maps = [{'Surface': {'SurfaceTagCrc': crc},
                         'MaterialAsset': _azmat(mhint)}
                        for crc, mhint in materials]
            se['Components']['Component_[%d]' % len(se['Components'])] = comp(
                'EditorTerrainSurfaceMaterialsListComponent',
                {'DefaultMaterial': mat_maps[0], 'Mappings': mat_maps})
        if macros:
            color_hint, normal_hint = macros
            se['Components']['Component_[%d]' % len(se['Components'])] = comp(
                'EditorTerrainMacroMaterialComponent',
                {'MacroColor': _img(color_hint),
                 'MacroNormal': _img(normal_hint)})
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
    ap.add_argument('--bake-cookies', action='store_true',
                    help='bake capital cookie flattens into the TIFF '
                         '(legacy path — default is raw TIFF + NWCapital '
                         'gem stamps at sample time)')
    a = ap.parse_args()
    src = a.level_dir.rstrip('/')
    level = a.name or os.path.basename(src)
    tj = _tj.load(os.path.join(src, 'terrain.json'))
    mh = float(tj.get('mountainHeight', 2048.0))
    lvl_dir = os.path.join(a.out, 'Levels', level)
    img_dir = os.path.join(lvl_dir, 'heightmaps')
    os.makedirs(img_dir, exist_ok=True)
    regions = []
    all_cookies = {}
    rdir = os.path.join(src, 'regions')
    if not os.path.isdir(rdir):
        rdir = src  # region dirs may sit directly under the level dir
    for rname in sorted(os.listdir(rdir)):
        if not rname.startswith('r_'):
            continue
        hm_path = os.path.join(rdir, rname, 'region.heightmap')
        if not os.path.isfile(hm_path):
            continue
        ix, iy = region_index(rname)
        hm = decode(open(hm_path, 'rb').read())
        if a.bake_cookies:
            apply_cookies(hm, os.path.dirname(hm_path), mh)
        else:
            all_cookies[rname] = collect_cookies(
                os.path.dirname(hm_path))
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
    # client terrain surface layers (regionmat splats + detail materials)
    surfaces = {}
    rms = glob.glob(os.path.join(src, 'terrainmat', '*.regionmat'))
    if rms:
        m = re.search(r'_(\d+)_(\d+)\.regionmat$', os.path.basename(rms[0]))
        tile = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        for rname, (ix, iy), _size, _mh, _hint in regions:
            if (ix, iy) == tile:
                surfaces[rname] = build_surfaces(level, src, a.out, rname)
    prefab = build_prefab(level, regions, surfaces, all_cookies)
    ppath = os.path.join(lvl_dir, level + '.prefab')
    with open(ppath, 'w') as f:
        json.dump(prefab, f, indent=1)
    import shutil
    shutil.copyfile(os.path.join(src, 'terrain.json'), os.path.join(lvl_dir, 'terrain.json'))
    print('wrote %s (%d regions)' % (ppath, len(regions)))


if __name__ == '__main__':
    main()
