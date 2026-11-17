#!/usr/bin/env python3
"""Minimal glTF 2.0 (.glb) writer — JSON + single BIN buffer.

Cry is Z-up right-handed; glTF is Y-up. We attach a root node rotated
-90 deg about X so meshes stay in Cry coordinates and viewers render
them upright.
"""
import json
import struct

_CT = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2), 5123: ('H', 2),
       5125: ('I', 4), 5126: ('f', 4)}
_NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


class Gltf:
    def __init__(self):
        self.bin = bytearray()
        self.g = {'asset': {'version': '2.0',
                            'generator': 'nwmesh cgf2glb'},
                  'scene': 0, 'scenes': [{'nodes': []}],
                  'nodes': [], 'meshes': [], 'accessors': [],
                  'bufferViews': [], 'materials': [],
                  'images': [], 'textures': []}
        # Z-up (Cry) -> Y-up (glTF): -90 deg about X
        self.root = self.node('_cry_root', rotation=(-0.7071067811865476, 0, 0, 0.7071067811865476))
        self.g['scenes'][0]['nodes'].append(self.root)

    def node(self, name, matrix=None, rotation=None, translation=None,
             children=None, mesh=None, skin=None, parent=None):
        n = {'name': name}
        if matrix is not None:
            n['matrix'] = matrix
        if rotation is not None:
            n['rotation'] = list(rotation)
        if translation is not None:
            n['translation'] = list(translation)
        if mesh is not None:
            n['mesh'] = mesh
        if skin is not None:
            n['skin'] = skin
        if children:
            n['children'] = children
        idx = len(self.g['nodes'])
        self.g['nodes'].append(n)
        if parent is not None:
            self.g['nodes'][parent].setdefault('children', []).append(idx)
        return idx

    def material(self, name, base_image=None, normal_image=None,
                 base_color=None):
        """base_image/normal_image: image indexes. base_color: rgba."""
        pbr = {}
        if base_image is not None:
            pbr['baseColorTexture'] = {'index': base_image}
        if base_color is not None:
            pbr['baseColorFactor'] = list(base_color)
        m = {'name': name, 'pbrMetallicRoughness': pbr}
        if normal_image is not None:
            m['normalTexture'] = {'index': normal_image}
        self.g['materials'].append(m)
        return len(self.g['materials']) - 1

    def image(self, uri):
        """External image referenced by URI (relative to the .glb)."""
        self.g['images'].append({'uri': uri})
        self.g['textures'].append({'source': len(self.g['images']) - 1})
        return len(self.g['textures']) - 1

    def accessor(self, ctype, atype, data, count=None, normalized=False,
                 target=None):
        """data: flat list or list of tuples."""
        fmt, isz = _CT[ctype]
        nc = _NC[atype]
        flat = []
        if data and isinstance(data[0], (tuple, list)):
            for row in data:
                flat.extend(row)
        else:
            flat = list(data)
        raw = struct.pack('<%d%s' % (len(flat), fmt), *flat)
        pad = (-len(raw)) % 4
        raw += b'\0' * pad
        bv = len(self.g['bufferViews'])
        view = {'buffer': 0, 'byteOffset': len(self.bin),
                'byteLength': len(raw) - pad}
        if target:
            view['target'] = target
        self.g['bufferViews'].append(view)
        self.bin += raw
        n = count if count is not None else len(flat) // nc
        acc = {'bufferView': bv, 'componentType': ctype, 'count': n,
               'type': atype}
        if normalized:
            acc['normalized'] = True
        if atype == 'SCALAR' and ctype == 5126 and flat:
            acc['min'] = [min(flat)]
            acc['max'] = [max(flat)]
        if atype == 'VEC3' and ctype == 5126 and flat:
            xs, ys, zs = flat[0::3], flat[1::3], flat[2::3]
            acc['min'] = [min(xs), min(ys), min(zs)]
            acc['max'] = [max(xs), max(ys), max(zs)]
        self.g['accessors'].append(acc)
        return len(self.g['accessors']) - 1

    def mesh(self, primitives):
        """primitives: [{'attributes':{}, 'indices':acc, 'material':i}]"""
        self.g['meshes'].append({'primitives': primitives})
        return len(self.g['meshes']) - 1

    def skin(self, joints, ibms):
        """joints: node indices; ibms: MAT4 column-major flat lists."""
        acc = self.accessor(5126, 'MAT4', ibms)
        self.g.setdefault('skins', []).append(
            {'joints': list(joints), 'inverseBindMatrices': acc})
        return len(self.g['skins']) - 1

    def animation(self, name, channels):
        """channels: [(node_idx, 'rotation'|'translation', times, values)].

        times: list of seconds -> SCALAR f32 accessor; values: VEC4 quat
        or VEC3 f32 accessor. One glTF animation, LINEAR samplers.
        """
        samplers, chans = [], []
        for node, path, times, values in channels:
            tin = self.accessor(5126, 'SCALAR', times)
            tout = self.accessor(5126, 'VEC4' if path == 'rotation' else 'VEC3',
                                 values)
            samplers.append({'input': tin, 'output': tout,
                             'interpolation': 'LINEAR'})
            chans.append({'sampler': len(samplers) - 1,
                          'target': {'node': node, 'path': path}})
        self.g.setdefault('animations', []).append(
            {'name': name, 'samplers': samplers, 'channels': chans})

    def write(self, path):
        g = dict(self.g)
        g['buffers'] = [{'byteLength': len(self.bin)}]
        js = json.dumps(g, separators=(',', ':')).encode()
        js += b' ' * ((-len(js)) % 4)
        bn = bytes(self.bin) + b'\0' * ((-len(self.bin)) % 4)
        total = 12 + 8 + len(js) + 8 + len(bn)
        with open(path, 'wb') as f:
            f.write(struct.pack('<4sII', b'glTF', 2, total))
            f.write(struct.pack('<I4s', len(js), b'JSON'))
            f.write(js)
            f.write(struct.pack('<I4s', len(bn), b'BIN\0'))
            f.write(bn)
