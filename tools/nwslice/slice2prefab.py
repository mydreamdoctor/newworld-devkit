#!/usr/bin/env python3
"""Generic NW .dynamicslice -> O3DE .prefab converter (viewing layer).

Each AZ::Entity in the slice becomes a prefab entity placed at its
GameTransformComponent m_worldTM (the client's authoritative transform).
Components with an O3DE counterpart are converted:

  GameTransformComponent -> TransformComponent (Translate + Euler Rotate)
  SplineComponent        -> EditorSplineComponent (bezier points/tangents)

Every other component type is skipped and listed under "skipped" in the
.sidecar.json so nothing is silently lost. Entity placement is flattened
(world transforms are absolute).

Usage: slice2prefab.py SLICE -o out.prefab [--sidecar out.json]
"""
import argparse, hashlib, json, math as _m, os, re, struct, sys, uuid, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from osv3 import parse_objectstream
import river_io
from river2prefab import _spline_component, nid, TRANSFORM_COMPONENT

TN = river_io.TN
FN = river_io.FN
CRC = river_io.CRC
UID = river_io.UID
_kids = river_io._kids
_by_crc = river_io._by_crc
_by_type = river_io._by_type
_walk = river_io._walk
_f32s = river_io._f32s


def _str_val(e):
    try:
        return e['val'].decode('utf-8').rstrip('\x00')
    except Exception:
        return ''


def _euler_deg(tm):
    """Column-major 3x4 basis columns -> ZYX euler degrees (yaw,pitch,roll).

    AZ::Transform Rotate is a ZYX euler in degrees: R = Rz*Ry*Rx.
    """
    bx, by, bz = tm[0:3], tm[3:6], tm[6:9]
    # R columns are bx,by,bz
    r20, r21, r22 = bx[2], by[2], bz[2]
    if abs(r20) < 0.999999:
        ry = _m.degrees(_m.asin(-r20))
        rz = _m.degrees(_m.atan2(by[0], bx[0]))
        rx = _m.degrees(_m.atan2(r21, r22))
    else:
        ry = 90.0 if r20 <= -0.999999 else -90.0
        rz = _m.degrees(_m.atan2(-by[1], by[0] if False else by[1]))
        rx = 0.0
    if abs(rx) < 1e-6 and abs(ry) < 1e-6 and abs(rz) < 1e-6:
        return None
    return [rx, ry, rz]


def _entities(root):
    """Slice root entity -> [(name, {comptype: el}, children-of-SliceComponent)]."""
    out = []
    for sc in _walk(root):
        if sc['id'] != UID['SliceComponent']:
            continue
        for k in _kids(sc):
            for e in _kids(k):
                if e['id'] != UID['AZ::Entity']:
                    continue
                name = ''
                nf = _by_crc(e, 'name')
                if nf is not None and 'val' in nf:
                    name = _str_val(nf)
                comps = {}
                cf = _by_crc(e, 'Components')
                for c in _kids(cf) if cf else []:
                    comps.setdefault(TN.get(c['id'], c['id']), c)
                out.append((name, comps))
    return out


def _spline_points(comp):
    bz = river_io._spline_el(comp)
    spline = _by_type(bz, 'Spline')[0]
    verts, _ = river_io._vertex_elements(bz)
    beziers, _ = river_io._bezier_elements(bz)
    closed = _by_crc(spline, 'Closed')
    gran = _by_crc(bz, 'Granularity')
    pts = []
    for i, v in enumerate(verts):
        p = {'pos': _f32s(v['val'])}
        if i < len(beziers):
            for nm, key in (('Forward', 'forward'), ('Back', 'back'), ('Angle', 'angle')):
                f = _by_crc(beziers[i], nm)
                if f is not None and 'val' in f:
                    p[key] = (_f32s(f['val']) if nm != 'Angle'
                              else struct.unpack('>f', f['val'])[0])
        pts.append(p)
    return pts, (bool(closed['val'][0]) if closed and 'val' in closed else False), \
        (struct.unpack('>H', gran['val'])[0] if gran and 'val' in gran else 8)


def _find_crc(el, name):
    """First descendant field whose crc resolves to `name`."""
    c = CRC[name]
    for k in _walk(el):
        if k.get('crc') == c:
            return k
    return None


def _asset_guid(path):
    """AZ::Uuid::CreateName(lowercase path): sha1[0:16] + v5 bits."""
    h = bytearray(hashlib.sha1(path.lower().encode()).digest()[:16])
    h[6] = (h[6] & 0x0f) | 0x50
    h[8] = (h[8] & 0x3f) | 0x80
    return str(uuid.UUID(bytes=bytes(h))).upper()



def _mesh_asset(comp_el):
    """pak-relative .cgf path from a (Instanced)MeshComponent blob."""
    path = ''
    for k in _walk(comp_el):
        v = k.get('val')
        if not v:
            continue
        m = re.search(
            rb'(?:objects|materials|textures|libs|sharedassets|'
            rb'engineassets)/[a-zA-Z0-9_/\.\-]+\.[Cc][Gg][Ff]', v)
        if m:
            return m.group(0).decode('utf8', 'replace')
        if k.get('crc') == CRC.get('AssetPath') or k.get('crc') == 741691769:
            path = _str_val(v)
    return path if path.lower().endswith('.cgf') else ''


def _skip_model(path):
    """Models that must not render: collision proxies, VFX/fog cards,
    editor primitives used as invisible gameplay blockers."""
    b = os.path.basename(path).lower()
    stem, _, _ = b.rpartition('.')
    p = path.lower()
    return (b.startswith('primitive_') or stem.endswith('_coll')
            or stem.endswith('_vfx') or stem.startswith('fx_')
            or '/vfx/' in p or '/volumetrics/' in p
            or any(k in stem for k in
                   ('fogsheet', 'fogbeam', 'fogcard', 'groundfog',
                    'lightray', 'sunblocker')))


def _model_asset(path):
    """EditorMeshComponent ModelAsset block for a pak-relative .cgf."""
    stem_path = path[:-4]
    stem = stem_path.rsplit('/', 1)[-1]
    guid = _asset_guid(stem_path + '.glb')
    subid = 0x10000000 | (zlib.crc32(stem.lower().encode()) & 0xffffff)
    return {'assetId': {'guid': '{%s}' % guid, 'subId': subid},
            'assetHint': stem_path + '.glb.azmodel'}


def _mesh_component(comp_el):
    """NW MeshComponent -> AZ::Render::EditorMeshComponent.

    The mesh ref sits in a descendant field of the component as
    {guid(16) subId(4) type-uuid(16) path-string} — extract the
    .cgf path embedded in its blob.

    The nw_cgf_builder turns <dir>/<stem>.cgf into intermediate
    <stem>.glb and Scene Builder emits <stem>.glb.azmodel (subId =
    0x10000000 | crc32(stem) & 0xffffff, verified against
    assetdb.sqlite product rows)."""
    path = _mesh_asset(comp_el)
    if not path:
        return None
    return {'$type': 'AZ::Render::EditorMeshComponent', 'Id': nid(),
            'Controller': {'Configuration': {
                'ModelAsset': _model_asset(path)}}}


def _mat_mul(a, b):
    """3x4 column-major transform multiply a*b (a outer, b local)."""
    out = [0.0] * 12
    for col in range(3):           # basis
        for row in range(3):
            out[col*3+row] = (a[row] * b[col*3] + a[3+row] * b[col*3+1]
                              + a[6+row] * b[col*3+2])
    for row in range(3):           # translation
        out[9+row] = (a[row] * b[9] + a[3+row] * b[10]
                      + a[6+row] * b[11] + a[9+row])
    return out


def _instanced_meshes(comp_el):
    """NW InstancedMeshComponent -> [(world_tm, ModelAsset)].

    One .cgf + N local-space instance transforms (field 0xc41bd26a);
    world = entity_world_tm * instance_tm."""
    path = _mesh_asset(comp_el)
    if not path:
        return []
    transforms = []
    for k in _walk(comp_el):
        if k.get('crc') == 0xc41bd26a:
            for t in _kids(k):
                v = t.get('val')
                if v and len(v) == 48:
                    transforms.append(_f32s(v))
    return [(t, _model_asset(path)) for t in transforms]


def _polyprism_component(comp_el):
    """NW PolygonPrismShapeComponent -> O3DE EditorPolygonPrismShapeComponent.
    NW: PolygonPrism{Height f32be, VertexContainer{Vertices{element 8B=2f32be}}}.
    O3DE: Configuration.PolygonPrism{Height, VertexContainer.Vertices [[x,y]]}."""
    hf = _find_crc(comp_el, 'Height')
    vf = _find_crc(comp_el, 'Vertices')
    height = struct.unpack('>f', hf['val'])[0] if hf and 'val' in hf else 1.0
    verts = []
    if vf is not None:
        for v in _kids(vf):
            if 'val' in v and len(v['val']) >= 8:
                verts.append(list(struct.unpack('>2f', v['val'][:8])))
    return {'$type': 'EditorPolygonPrismShapeComponent', 'Id': nid(),
            'Visible': True, 'GameView': True, 'DisplayFilled': False,
            'Configuration': {'PolygonPrism': {
                'Height': height,
                'VertexContainer': {'Vertices': verts}}}}


def convert(raw, level_name='Level'):
    ver, root = parse_objectstream(raw)
    ents = {}
    skipped = {}
    i = 1
    for name, comps in _entities(root):
        i += 1
        eid = 'Entity_[%d]' % i
        clist = []
        tm = None
        gt = comps.get('GameTransformComponent')
        if gt is not None:
            f = _by_crc(gt, 'm_worldTM')
            if f is not None and 'val' in f:
                tm = _f32s(f['val'])
        if tm is None:
            tc = comps.get('TransformComponent')
            if tc is not None:
                f = _by_crc(tc, 'Transform')
                if f is not None and 'val' in f and len(f['val']) == 48:
                    tm = _f32s(f['val'])
        td = {'Translate': [tm[9], tm[10], tm[11]] if tm else [0, 0, 0]}
        rot = _euler_deg(tm) if tm else None
        if rot:
            td['Rotate'] = rot
        clist.append({'$type': TRANSFORM_COMPONENT, 'Id': nid(),
                      'Transform Data': td, 'Parent Entity': 'Entity_[1]'})
        unmapped = []
        for tname, cel in comps.items():
            if tname in ('GameTransformComponent', 'AZ::Component',
                         'TransformComponent'):
                continue
            if tname == 'SplineComponent':
                try:
                    pts, closed, gran = _spline_points(cel)
                    clist.append(_spline_component(pts, closed, gran))
                    continue
                except Exception:
                    pass
            if tname == 'PolygonPrismShapeComponent':
                try:
                    clist.append(_polyprism_component(cel))
                    continue
                except Exception:
                    pass
            if tname == 'MeshComponent':
                try:
                    mp = _mesh_asset(cel)
                    if mp and _skip_model(mp):
                        continue
                    mc = _mesh_component(cel)
                    if mc is not None:
                        clist.append(mc)
                        continue
                except Exception:
                    pass
            if tname == 'InstancedMeshComponent':
                try:
                    mp = _mesh_asset(cel)
                    if mp and _skip_model(mp):
                        continue
                    insts = _instanced_meshes(cel)
                    for itm, mdl in insts:
                        wtm = _mat_mul(tm, itm) if tm else itm
                        td2 = {'Translate': [wtm[9], wtm[10], wtm[11]]}
                        rot2 = _euler_deg(wtm)
                        if rot2:
                            td2['Rotate'] = rot2
                        i += 1
                        ieid = 'Entity_[%d]' % i
                        ic = [
                            {'$type': TRANSFORM_COMPONENT, 'Id': nid(),
                             'Transform Data': td2,
                             'Parent Entity': 'Entity_[1]'},
                            {'$type': 'AZ::Render::EditorMeshComponent',
                             'Id': nid(),
                             'Controller': {'Configuration': {
                                 'ModelAsset': mdl}}}]
                        ents[ieid] = {
                            'Id': ieid,
                            'Name': (name or eid) + '_inst',
                            'Components': {'Component_[%d]' % j: c
                                           for j, c in enumerate(ic)}}
                    if insts:
                        continue
                except Exception:
                    pass
            unmapped.append(tname)
        if unmapped:
            skipped[name or eid] = unmapped
        ents[eid] = {
            'Id': eid, 'Name': name or eid,
            'Components': {'Component_[%d]' % j: c for j, c in enumerate(clist)}}
    prefab = {
        'ContainerEntity': {
            'Id': 'Entity_[1]', 'Name': level_name,
            'Components': {'Component_[0]': {
                '$type': TRANSFORM_COMPONENT, 'Id': nid(),
                'Transform Data': {'Translate': [0.0, 0.0, 0.0]},
                'Parent Entity': ''}}},
        'Entities': ents,
    }
    return prefab, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('slice')
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--sidecar')
    a = ap.parse_args()
    raw = open(a.slice, 'rb').read()
    prefab, skipped = convert(raw, os.path.splitext(os.path.basename(a.slice))[0])
    with open(a.out, 'w') as f:
        json.dump(prefab, f, indent=2)
    n = len(prefab['Entities'])
    print('wrote %s (%d entities, %d with unmapped components)'
          % (a.out, n, len(skipped)))
    if a.sidecar:
        with open(a.sidecar, 'w') as f:
            json.dump({'slice': os.path.basename(a.slice), 'skipped': skipped},
                      f, indent=2)


if __name__ == '__main__':
    main()
