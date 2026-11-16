#!/usr/bin/env python3
"""Convert a New World .cgf/.skin (+.cgfheap) to a .glb.

Usage: cgf2glb.py IN.cgf|IN.skin OUT.glb

Emits one glTF mesh per (node, subset) with POSITION/NORMAL/TEXCOORD_0/
COLOR_0. Missing normals are computed smooth. Node hierarchy and
transforms come from Node chunks; a root node maps Cry Z-up to glTF
Y-up. .skin files convert as static (bind-pose) meshes for now.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cgf
from glb import Gltf


def _normals(pos, idx):
    """Area-weighted smooth vertex normals."""
    n = [[0.0, 0.0, 0.0] for _ in pos]
    for k in range(0, len(idx) - 2, 3):
        a, b, c = pos[idx[k]], pos[idx[k + 1]], pos[idx[k + 2]]
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        for i in (idx[k], idx[k + 1], idx[k + 2]):
            n[i][0] += nx
            n[i][1] += ny
            n[i][2] += nz
    import math
    return [(x / l, y / l, z / l) if (l := math.sqrt(x * x + y * y + z * z)) > 0
            else (0.0, 0.0, 1.0) for x, y, z in n]


def convert(src, dst):
    c = cgf.load(src)
    g = Gltf()
    nmat = 0
    mat_ids = []
    for s in (c.mtl_subs or [c.mtl or os.path.basename(src)]):
        mat_ids.append(g.material(s if isinstance(s, str) else
                                  'mat%d' % len(mat_ids)))
        nmat += 1
    nid_to_gltf = {}
    for nodeid, n in c.nodes.items():
        # Cry row-major flat == glTF column-major flat (v' = v*M)
        nid_to_gltf[nodeid] = g.node(n['name'] or 'node%d' % nodeid,
                                     matrix=list(n['tm']), parent=g.root)
    # reparent under actual parents where known
    for nodeid, n in c.nodes.items():
        if n['parent'] in nid_to_gltf:
            # rebuild hierarchy: move from root to real parent
            gid = nid_to_gltf[nodeid]
            g.g['nodes'][g.root]['children'].remove(gid)
            g.g['nodes'][nid_to_gltf[n['parent']]].setdefault(
                'children', []).append(gid)
    for n, mid in c.node_meshes():
        mh = c.meshes[mid]
        st = c.mesh_streams(mid)
        pos = st.get(cgf.ST_POS, (None,))[0]
        idx = st.get(cgf.ST_INDEX, (None,))[0]
        if not pos or not idx:
            continue
        attrs = {'POSITION': g.accessor(5126, 'VEC3', pos)}
        nrm = st.get(cgf.ST_NORMAL, (None,))[0] or _normals(pos, idx)
        attrs['NORMAL'] = g.accessor(5126, 'VEC3', nrm)
        uv = st.get(cgf.ST_UV, (None,))[0]
        if uv:
            attrs['TEXCOORD_0'] = g.accessor(
                5126, 'VEC2', [(u, 1.0 - v) for u, v in uv])
        col = st.get(cgf.ST_COLOR, (None,))[0]
        if col and len(col) == len(pos):
            attrs['COLOR_0'] = g.accessor(5121, 'VEC4', col,
                                        normalized=True)
        subs = c.subsets.get(mh['subsets_id'])
        prims = []
        iacc = g.accessor(5125, 'SCALAR', idx, target=34963)
        if subs:
            for s_i, s in enumerate(subs):
                sidx = idx[s['first_idx']:s['first_idx'] + s['n_idx']]
                if not sidx:
                    continue
                prims.append({'attributes': attrs,
                              'indices': g.accessor(5125, 'SCALAR', sidx,
                                                    target=34963),
                              'material': mat_ids[min(s['matid'],
                                                      len(mat_ids) - 1)]})
        if not prims:
            prims = [{'attributes': attrs, 'indices': iacc}]
        mesh_i = g.mesh(prims)
        gid = nid_to_gltf.get(next(k for k, v in c.nodes.items()
                                   if v is n))
        g.g['nodes'][gid]['mesh'] = mesh_i
    g.write(dst)
    return c


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    c = convert(src, dst)
    print('%s -> %s (%d nodes, %d meshes)' %
          (src, dst, len(c.nodes), len(c.meshes)))
