#!/usr/bin/env python3
"""cgf parser + cgf2glb tests. Corpus lives outside the repo; tests
skip cleanly when absent."""
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cgf
import cgf2glb

CORPUS = os.environ.get('NW_MESH_CORPUS', '/tmp/nwcorpus')
CGF = os.path.join(CORPUS, 'upyrbustg_lod3.cgf')
SKIN = os.path.join(CORPUS, 'adiana_body.skin')


@unittest.skipUnless(os.path.isfile(CGF), 'corpus missing')
class TestCgfParse(unittest.TestCase):
    def test_chunk_table(self):
        c = cgf.load(CGF)
        types = {x['type'] for x in c.chunks}
        self.assertIn(cgf.CHUNK_MESH, types)
        self.assertIn(cgf.CHUNK_NODE, types)
        self.assertIn(cgf.CHUNK_SUBSETS, types)

    def test_streams_decode(self):
        c = cgf.load(CGF)
        n, mid = c.node_meshes()[0]
        st = c.mesh_streams(mid)
        self.assertEqual(len(st[cgf.ST_POS][0]), c.meshes[mid]['nverts'])
        self.assertEqual(len(st[cgf.ST_INDEX][0]),
                         c.meshes[mid]['nindices'])

    def test_glb_roundtrip_structure(self):
        with tempfile.NamedTemporaryFile(suffix='.glb') as t:
            cgf2glb.convert(CGF, t.name)
            d = open(t.name, 'rb').read()
        self.assertEqual(d[:4], b'glTF')
        jlen = struct.unpack_from('<I', d, 12)[0]
        j = json.loads(d[20:20 + jlen])
        prim = j['meshes'][0]['primitives'][0]
        acc = j['accessors']
        self.assertEqual(acc[prim['attributes']['POSITION']]['count'], 42)
        self.assertEqual(acc[prim['indices']]['count'], 60)


@unittest.skipUnless(os.path.isfile(SKIN), 'corpus missing')
class TestSkinParse(unittest.TestCase):
    def test_skin_streams(self):
        c = cgf.load(SKIN)
        n, mid = c.node_meshes()[0]
        st = c.mesh_streams(mid)
        self.assertEqual(len(st[cgf.ST_POS][0]), 22684)
        self.assertEqual(len(st[cgf.ST_UV][0]), 22684)
        self.assertIn(cgf.ST_BONEMAP, st)
        self.assertEqual(len(c.mtl_subs), 5)


if __name__ == '__main__':
    unittest.main()
