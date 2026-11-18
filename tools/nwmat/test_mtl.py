#!/usr/bin/env python3
"""mtl parser + mtl2atom + dds reassembly tests. Corpus-independent."""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dds
import mtl
import mtl2atom

MTL = b'''<?xml version="1.0"?>
<Material MtlFlags="557312" vertModifType="0">
 <SubMaterials>
  <Material Name="UpyrBustG_mat" Shader="Illum" Diffuse="0.5,0.5,0.5,1"
   Specular="1,1,1,1" Opacity="1" Shininess="210" AlphaTest="0.5">
   <Textures>
    <Texture Map="Diffuse" File="objects/props/x/textures/x_diff.dds"/>
    <Texture Map="Bumpmap" File="objects/props/x/textures/x_ddna.tif"/>
    <Texture Map="Specular" File="objects/props/x/textures/x_spec.dds"/>
   </Textures>
   <PublicParams RoughnessBoost="2"/>
  </Material>
  <Material Name="glass_mat" Shader="Glass" Opacity="0.4"/>
 </SubMaterials>
</Material>'''


def _dds_stub(tmp, name, w=64, h=64, mips=7, dxgi=72):
    """Write a split DDS: header+DX10 block + .N mips."""
    hdr = bytearray(148)
    hdr[0:4] = b'DDS '
    struct.pack_into('<I', hdr, 4, 124)
    struct.pack_into('<I', hdr, 12, h)
    struct.pack_into('<I', hdr, 16, w)
    struct.pack_into('<I', hdr, 28, mips)
    struct.pack_into('<I', hdr, 84, 0x4)
    hdr[84:88] = b'DX10'
    struct.pack_into('<I', hdr, 128, dxgi)
    payload = []
    # BC1 (8b/block) sizes for 64x64: mips 0..6
    sizes = [max(1, (w >> i) // 4) * max(1, (h >> i) // 4) * 8
             for i in range(mips)]
    tail = bytes(sizes[-1])  # the stub carries the smallest mip
    path = os.path.join(tmp, name)
    with open(path, 'wb') as f:
        f.write(bytes(hdr) + tail)
    # numbered files cover mips 0..mips-2, tail holds the last
    for i, s in enumerate(sizes[:-1]):
        n = len(sizes) - 1 - i
        with open('%s.%d' % (path, n), 'wb') as f:
            f.write(bytes([i]) * s)
    return path, sum(sizes) + 148


class TestMtl(unittest.TestCase):
    def test_parse(self):
        m = mtl.Mtl.parse(MTL)
        self.assertEqual(len(m.subs), 2)
        s = m.by_name['UpyrBustG_mat']
        self.assertEqual(s.shader, 'Illum')
        self.assertAlmostEqual(s.shininess, 210.0)
        self.assertEqual(s.textures['Diffuse'],
                         'objects/props/x/textures/x_diff.dds')
        self.assertEqual(s.public_params['RoughnessBoost'], '2')

    def test_atom(self):
        m = mtl.Mtl.parse(MTL)
        s = m.by_name['UpyrBustG_mat']
        mat, un = mtl2atom.to_atom(s, {
            'Diffuse': 'objects/props/x/textures/x_diff.dds',
            'Bumpmap': 'objects/props/x/textures/x_ddna.dds'})
        props = mat['properties']
        self.assertEqual(props['baseColor']['textureMap'],
                         'objects/props/x/textures/x_diff.dds')
        self.assertEqual(props['normal']['textureMap'],
                         'objects/props/x/textures/x_ddna.dds')
        self.assertEqual(props['opacity']['mode'], 'Cutout')
        self.assertTrue(any('RoughnessBoost' in u for u in un))

    def test_atom_blended(self):
        m = mtl.Mtl.parse(MTL)
        mat, un = mtl2atom.to_atom(m.by_name['glass_mat'], {})
        self.assertEqual(mat['properties']['opacity']['mode'], 'Blended')
        self.assertTrue(any('shader Glass' in u for u in un))


class TestDds(unittest.TestCase):
    def test_reassemble(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, expected = _dds_stub(tmp, 'x_diff.dds')
            out = dds.reassemble(path)
            self.assertEqual(len(out), expected)
            self.assertEqual(out[:4], b'DDS ')
            # mip0 (largest, highest-N file) comes first after header
            self.assertEqual(out[148], 0)

    def test_complete_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, expected = _dds_stub(tmp, 'y.dds')
            full = dds.reassemble(path)
            with open(path, 'wb') as f:
                f.write(full)
            self.assertEqual(dds.reassemble(path), full)


if __name__ == '__main__':
    unittest.main()
