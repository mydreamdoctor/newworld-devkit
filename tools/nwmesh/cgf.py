#!/usr/bin/env python3
"""New World .cgf/.skin parser (CrChF v7 container + NW deltas).

Delta vs Lumberyard 0x746-era CGF (leads: lumberyard CryHeaders.h,
lockstep tools/cgf_physproxy.py + arena_floor_bake.py):
  - file: 'CrChF' + u32 ver + u32 nChunks + u32 chunkTableOfs, entries
    <HHIII (type, ver, id, size, offset); data at offset (8-aligned
    header included in size? no - size is payload, offset is absolute).
  - mesh chunk 0x1000 ver 0x802: MESH_CHUNK_DESC_0802 — 7 ints, then
    nStreamChunkID[16][8] chunk ids, then 4 physics ids, bbox, etc.
  - streams: either inline ChunkType_DataStream 0x1016 chunks
    (hdr <7I: flags, streamType, ?, count, elemSize, ?, reserved
    then elements)
    or NW-only 0x300b descriptors <5I (kind, heapOfs, size, stride)
    pointing into the sibling .cgfheap blob.

Stream types (ECgfStreamType): 0 pos, 1 normals, 2 uv, 3 col, 4 col2,
5 indices, 6 tangents, 9 bonemapping, 11 vertmats, 12 qtangents, 15 packed.
"""
import os
import struct
import sys

CHUNK_MESH = 0x1000
CHUNK_NODE = 0x100B
CHUNK_MTLNAME = 0x1014
CHUNK_DATASTREAM = 0x1016
CHUNK_SUBSETS = 0x1017
CHUNK_HEAPSTREAM = 0x300B

ST_POS, ST_NORMAL, ST_UV, ST_COLOR, ST_COLOR2, ST_INDEX, ST_TANGENT = range(7)
ST_BONEMAP, ST_VERTMATS, ST_QTANGENT = 9, 11, 12


def chunk_table(d):
    if d[:5] != b'CrChF':
        raise ValueError('not a CrChF file')
    cnt, off = struct.unpack_from('<II', d, 8)
    out = []
    for i in range(cnt):
        t, v, cid, s, o = struct.unpack_from('<HHIII', d, off + 16 * i)
        out.append({'type': t, 'ver': v, 'id': cid, 'size': s, 'off': o})
    return out


def _node(d, o, size):
    name = d[o:o + 64].split(b'\0', 1)[0].decode('utf-8', 'replace')
    objid, parent, nch, matid = struct.unpack_from('<4i', d, o + 64)
    tm = struct.unpack_from('<16f', d, o + 84)
    plen = struct.unpack_from('<i', d, o + 188)[0]
    props = d[o + 192:o + 192 + plen].rstrip(b'\0').decode('utf-8', 'replace')
    return {'name': name, 'objid': objid, 'parent': parent, 'matid': matid,
            'tm': tm, 'props': props}


def _mesh_hdr(d, o):
    w = struct.unpack_from('<178I', d, o)
    return {'flags': w[0], 'nverts': w[2], 'nindices': w[3],
            'nsubsets': w[4], 'subsets_id': w[5], 'vertanim_id': w[6],
            'streams': {st: [x for x in w[7 + st * 8:15 + st * 8] if x]
                        for st in range(16)},
            'physics_ids': w[135:139],
            'bmin': struct.unpack_from('<3f', d, o + 139 * 4),
            'bmax': struct.unpack_from('<3f', d, o + 142 * 4)}


def _stream_desc(d, chunk, heap):
    """Return (data_bytes, ncount, elem_size, src). The stream *type* is
    taken from the mesh header's nStreamChunkID slot, not the descriptor."""
    t, cid, s, o = chunk['type'], chunk['id'], chunk['size'], chunk['off']
    if t == CHUNK_DATASTREAM:
        fl, stype, _x, ncount, esz, _y, _z = struct.unpack_from('<7I', d, o)
        hdr = s - ncount * esz  # NW carries a 28B header (7 u32)
        return d[o + hdr:o + s], ncount, esz, 'inline', None
    if t == CHUNK_HEAPSTREAM:
        _k, kind, hoff, hsize, stride = struct.unpack_from('<5I', d, o)
        ncount = hsize // stride if stride else 0
        return heap[hoff:hoff + hsize], ncount, stride, 'heap', kind
    raise ValueError('chunk id %d type 0x%x is not a stream' % (cid, t))


def _subsets(d, o, size):
    flags, cnt = struct.unpack_from('<2I', d, o)
    out, p = [], o + 16
    for _ in range(cnt):
        fi, ni, fv, nv, mid = struct.unpack_from('<5i', d, p)
        rad = struct.unpack_from('<f', d, p + 20)[0]
        cx, cy, cz = struct.unpack_from('<3f', d, p + 24)
        out.append({'first_idx': fi, 'n_idx': ni, 'first_vert': fv,
                    'n_verts': nv, 'matid': mid, 'radius': rad,
                    'center': (cx, cy, cz)})
        p += 36
    # optional MeshBoneIDs block (flags & 2): u32 num + u16 ids
    return out


def _mtl_names(d, o, ver):
    # NW ver 0x804 uses a 64-byte name field; 0x802 uses 128; 0x800 is
    # the Lumberyard fixed struct (name@+8, nSub@+140, ids[32]@+144).
    namelen = 64 if ver >= 0x804 else 128
    name = d[o:o + namelen].split(b'\0', 1)[0].decode('utf-8', 'replace')
    if ver >= 0x802:
        # name[N], i32 nSub, nSub i32 phys types, ASCIIZ sub names
        nsub = struct.unpack_from('<i', d, o + namelen)[0]
        p = o + namelen + 4 + 4 * max(0, nsub)
        subs = []
        for _ in range(max(0, nsub)):
            e = d.index(b'\0', p)
            subs.append(d[p:e].decode('utf-8', 'replace'))
            p = e + 1
        return name, subs
    nsub = struct.unpack_from('<i', d, o + 140)[0]
    ids = struct.unpack_from('<32i', d, o + 144)
    return name, list(ids[:max(0, nsub)])


def _half(v):
    return struct.unpack_from('<e', struct.pack('<e', v))[0]


def decode_stream(stype, data, ncount, esz, kind=None):
    """Decode a stream blob to a python list per element.

    kind==1 heap streams are packed vertices shared by stypes 0/2/3:
    stride 16 = {pos 4xf16, col RGBA8, uv 2xf16},
    stride 24 = {pos 3xf32, col RGBA8, uv 2xf32}."""
    u = struct.unpack_from
    if kind == 1:
        if stype == ST_POS:
            if esz == 16:
                return [u('<3e', data, i * 16) for i in range(ncount)]
            if esz == 24:
                return [u('<3f', data, i * 24) for i in range(ncount)]
        if stype == ST_UV:
            if esz == 16:
                return [u('<2e', data, i * 16 + 12) for i in range(ncount)]
            if esz == 24:
                return [u('<2f', data, i * 24 + 16) for i in range(ncount)]
        if stype in (ST_COLOR, ST_COLOR2):
            if esz == 16:
                return [tuple(data[i * 16 + 8:i * 16 + 12])
                        for i in range(ncount)]
            if esz == 24:
                return [tuple(data[i * 24 + 12:i * 24 + 16])
                        for i in range(ncount)]
        return None
    if stype == ST_INDEX:
        f = 'H' if esz == 2 else 'I'
        return [u('<' + f, data, i * esz)[0] for i in range(ncount)]
    if stype == ST_POS:
        if esz == 12:
            return [u('<3f', data, i * 12) for i in range(ncount)]
        if esz == 8:
            return [u('<3e', data, i * 8) for i in range(ncount)]
        # stride 16 (3f + 4B pad / w) or larger: first 12 bytes are xyz
        return [u('<3f', data, i * esz) for i in range(ncount)]
    if stype == ST_NORMAL:
        if esz == 8:  # 4 x i16 normalized
            q = [u('<4h', data, i * 8) for i in range(ncount)]
            return [(x / 32767, y / 32767, z / 32767) for x, y, z, w in q]
        return [u('<3f', data, i * esz) for i in range(ncount)]
    if stype == ST_UV:
        if esz == 8:
            return [u('<2f', data, i * 8) for i in range(ncount)]
        if esz == 4:
            q = [u('<2h', data, i * 4) for i in range(ncount)]
            return [(x / 32767, y / 32767) for x, y in q]
        return [u('<2f', data, i * esz) for i in range(ncount)]
    if stype in (ST_COLOR, ST_COLOR2):
        if esz == 4:
            return [tuple(data[i * 4:i * 4 + 4]) for i in range(ncount)]
    if stype == ST_TANGENT:
        if esz == 16:
            return [u('<4f', data, i * 16) for i in range(ncount)]
        if esz == 8:
            q = [u('<4h', data, i * 8) for i in range(ncount)]
            return [(x / 32767, y / 32767, z / 32767, w / 32767)
                    for x, y, z, w in q]
    if stype == ST_QTANGENT:
        if esz == 8:  # packed quat 4 x i16
            return [tuple(x / 32767 for x in u('<4h', data, i * 8))
                    for i in range(ncount)]
    if stype == ST_BONEMAP:
        if esz == 12:  # SMeshBoneMapping_uint16: 4xu16 joints + 4xu8 weights
            return [(u('<4H', data, i * 12),
                     tuple(data[i * 12 + 8:i * 12 + 12]))
                    for i in range(ncount)]
        if esz == 8:  # SMeshBoneMapping_uint8: 4xu8 joints + 4xu8 weights
            return [(tuple(data[i * 8:i * 8 + 4]),
                     tuple(data[i * 8 + 4:i * 8 + 8]))
                    for i in range(ncount)]
    if stype == ST_VERTMATS:
        if esz == 4:
            return [u('<I', data, i * 4)[0] for i in range(ncount)]
    return None  # undecoded


class Cgf:
    """Parsed .cgf/.skin: nodes, per-node meshes with decoded streams."""

    def __init__(self, cgf_bytes, heap_bytes=b''):
        self.d = cgf_bytes
        self.heap = heap_bytes
        self.chunks = chunk_table(cgf_bytes)
        self.byid = {c['id']: c for c in self.chunks}
        self.nodes = {}
        self.meshes = {}
        self.subsets = {}
        self.mtl, self.mtl_subs = '', []
        for c in self.chunks:
            if c['type'] == CHUNK_NODE:
                n = _node(cgf_bytes, c['off'], c['size'])
                self.nodes[c['id']] = n
            elif c['type'] == CHUNK_MESH:
                self.meshes[c['id']] = _mesh_hdr(cgf_bytes, c['off'])
            elif c['type'] == CHUNK_SUBSETS:
                self.subsets[c['id']] = _subsets(cgf_bytes, c['off'], c['size'])
            elif c['type'] == CHUNK_MTLNAME:
                self.mtl, self.mtl_subs = _mtl_names(
                    cgf_bytes, c['off'], c['ver'])

    def mesh_streams(self, mesh_id):
        """{stream_type: (decoded_list, src)} for mesh chunk id."""
        mh = self.meshes[mesh_id]
        out = {}
        for stype, ids in mh['streams'].items():
            for cid in ids:
                c = self.byid.get(cid)
                if not c:
                    continue
                blob, n, esz, src, kind = _stream_desc(
                    self.d, c, self.heap)
                dec = decode_stream(stype, blob, n, esz, kind)
                out[stype] = (dec, src, esz)
                break  # first stream of this type
        return out

    def node_meshes(self):
        """[(node_dict, mesh_chunk_id)] pairs via node.objid."""
        return [(n, n['objid']) for n in self.nodes.values()
                if n['objid'] in self.meshes]


def load(path):
    """Load a .cgf/.skin (+ sibling .cgfheap if present)."""
    with open(path, 'rb') as f:
        d = f.read()
    heap = b''
    hp = path[:-4] + '.cgfheap' if path.endswith('.cgf') else path + 'heap'
    if os.path.isfile(hp):
        with open(hp, 'rb') as f:
            heap = f.read()
    return Cgf(d, heap)


if __name__ == '__main__':
    for p in sys.argv[1:]:
        c = load(p)
        print(p, ': %d nodes, %d meshes, mtl=%s' %
              (len(c.nodes), len(c.meshes), c.mtl))
        for n, mid in c.node_meshes():
            st = c.mesh_streams(mid)
            desc = {s: (len(v[0]) if v[0] else 0) for s, v in st.items()}
            print('  node %-40s mesh %d %s' % (n['name'], mid, desc))
