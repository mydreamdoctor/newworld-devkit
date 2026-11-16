"""Convert a New World .caf + skeleton (.chr/.skin CompiledBones) to GLB.

Emits a node hierarchy named by bone, bind-pose local TRS on every node,
and one LINEAR-sampled glTF animation with rotation/translation channels.
EMotionFX/SceneBuilder turns this into a .motion-style product; node names
are the joint names EMotionFX matches by.
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'nwmesh'))
from glb import Gltf  # noqa: E402
import caf  # noqa: E402


def _mat_t(m):
    """Matrix34 row-major 12 floats -> (3x3 R as tuples, t)."""
    r = ((m[0], m[1], m[2]), (m[4], m[5], m[6]), (m[8], m[9], m[10]))
    return r, (m[3], m[7], m[11])


def _m3_mul_t(a, b):
    """a^T * b for 3x3 tuples (a used as inverse = transpose)."""
    return tuple(
        tuple(a[0][i] * b[0][j] + a[1][i] * b[1][j] + a[2][i] * b[2][j]
              for j in range(3))
        for i in range(3))


def _m3_tv_t(a, v):
    """a^T * v."""
    return tuple(a[0][i] * v[0] + a[1][i] * v[1] + a[2][i] * v[2]
                 for i in range(3))


def _r_to_quat(m):
    """3x3 rotation matrix -> (x,y,z,w) quaternion."""
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w = s / 4
        x = (m[2][1] - m[1][2]) / s
        y = (m[0][2] - m[2][0]) / s
        z = (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        w = (m[2][1] - m[1][2]) / s
        x = s / 4
        y = (m[0][1] + m[1][0]) / s
        z = (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        w = (m[0][2] - m[2][0]) / s
        x = (m[0][1] + m[1][0]) / s
        y = s / 4
        z = (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        w = (m[1][0] - m[0][1]) / s
        x = (m[0][2] + m[2][0]) / s
        y = (m[1][2] + m[2][1]) / s
        z = s / 4
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    return (x / n, y / n, z / n, w / n)


def local_trs(bone, bones):
    """Local bind-pose (t, q) for a bone from the B2W matrices."""
    r, t = _mat_t(bone['b2w'])
    if bone['parent'] is None:
        return t, _r_to_quat(r)
    pr, pt = _mat_t(bones[bone['parent']]['b2w'])
    lr = _m3_mul_t(pr, r)
    lt = _m3_tv_t(pr, (t[0] - pt[0], t[1] - pt[1], t[2] - pt[2]))
    return lt, _r_to_quat(lr)


def convert(caf_bytes, skel_bytes, dst, anim_name=None, fallback_ids=False):
    """caf_bytes: .caf data; skel_bytes: .chr/.skin data (or None when
    fallback_ids is set -> nodes named bone_<ctrlId>)."""
    a = caf.parse_caf(caf_bytes)
    spt = a['timing']['secsPerTick']
    g = Gltf()
    node_of = {}

    if skel_bytes is not None:
        bones = caf.parse_bones(skel_bytes)
        for i, b in enumerate(bones):
            t, q = local_trs(b, bones)
            node_of[b['id']] = g.node(b['name'], rotation=q,
                                      translation=t, parent=g.root if b['parent'] is None else
                                      node_of[bones[b['parent']]['id']])
    else:
        bones = []
        for cid in a['controllers']:
            node_of[cid] = g.node('bone_%08x' % cid, parent=g.root)

    channels = []
    for cid, tr in sorted(a['controllers'].items()):
        node = node_of.get(cid)
        if node is None:
            continue
        if len(tr['rot']) > 0:
            ts = [k * spt for k, _ in tr['rot']]
            channels.append((node, 'rotation', ts, [q for _, q in tr['rot']]))
        if len(tr['pos']) > 0:
            ts = [k * spt for k, _ in tr['pos']]
            channels.append((node, 'translation', ts, [v for _, v in tr['pos']]))

    if channels:
        g.animation(anim_name or 'nw_anim', channels)
    g.write(dst)
    return a
