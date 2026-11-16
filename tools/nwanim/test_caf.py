#!/usr/bin/env python3
"""caf/adb/caf2glb tests against real New World pak data.

Skipped automatically when the pak corpus is unavailable. Samples:
  objects/characters/npc/npc_skel.chr                 skeleton (130 bones)
  .../adiana_defeated.caf                           72 controllers
  .../npc_palatineguards_weapon_anims.adb           XML database
"""
import json
import math
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'nwslice'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'nwmesh'))

import adb as nwadb
import caf
import caf2glb

CAF = ('animations/gameplay/character/npc/supernatural/adiana/combat/'
       'adiana_defeated.caf')
CHR = 'objects/characters/npc/npc_skel.chr'
ADB = ('animations/mannequin/adb/isleofnight/'
       'npc_palatineguards_weapon_anims.adb')


def _paks():
    try:
        from paks import Paks
    except ImportError:
        return None
    root = '/home/lachlan/nw-install-backup-22469132/New World/assets'
    if not os.path.isdir(root):
        return None
    return Paks([os.path.join(root, '*.pak')])


PAKS = _paks()


@unittest.skipIf(PAKS is None, 'nw pak corpus unavailable')
class TestCaf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.caf_data = PAKS.read(CAF)
        cls.anim = caf.parse_caf(cls.caf_data)
        cls.bones = caf.parse_bones(PAKS.read(CHR))

    def test_timing(self):
        t = self.anim['timing']
        self.assertEqual(t['ticksPerFrame'], 1)
        self.assertAlmostEqual(t['secsPerTick'], 1.0 / 30, places=5)
        self.assertLessEqual(t['start'], t['end'])
        self.assertAlmostEqual(t['duration'], 197 / 30.0, places=2)

    def test_controllers_resolve(self):
        names = {b['id']: b['name'] for b in self.bones}
        self.assertEqual(len(self.anim['controllers']), 72)
        for cid in self.anim['controllers']:
            self.assertIn(cid, names)

    def test_quats_normalized(self):
        for tr in self.anim['controllers'].values():
            for _, q in tr['rot']:
                n = math.sqrt(sum(x * x for x in q))
                self.assertAlmostEqual(n, 1.0, delta=0.02)

    def test_times_monotonic_and_in_range(self):
        end = self.anim['timing']['end']
        for tr in self.anim['controllers'].values():
            for lane in ('rot', 'pos'):
                ts = [k for k, _ in tr[lane]]
                self.assertEqual(ts, sorted(ts))
                if ts:
                    self.assertGreaterEqual(ts[0], 0)
                    self.assertLessEqual(ts[-1], end)

    def test_bones(self):
        self.assertEqual(len(self.bones), 130)
        by = {b['name']: b for b in self.bones}
        self.assertIn('Pelvis', by)
        self.assertEqual(by['Xform']['parent'], None)
        self.assertEqual(by['Pelvis']['parent'], 0)

    def test_glb(self):
        dst = '/tmp/nwanim_test.glb'
        caf2glb.convert(self.caf_data, PAKS.read(CHR), dst,
                        anim_name='t')
        with open(dst, 'rb') as f:
            d = f.read()
        jl, = struct.unpack_from('<I', d, 12)
        g = json.loads(d[20:20 + jl])
        self.assertEqual(len(g['animations']), 1)
        names = {n.get('name') for n in g['nodes']}
        self.assertIn('Pelvis', names)
        ch = g['animations'][0]['channels']
        self.assertGreater(len(ch), 90)
        paths = {c['target']['path'] for c in ch}
        self.assertTrue(paths <= {'rotation', 'translation'})

    def test_adb(self):
        parsed = nwadb.parse_adb(PAKS.read(ADB))
        self.assertTrue(parsed['fragdef'])
        self.assertTrue(parsed['categories'])
        refs = nwadb.animation_refs(parsed)
        self.assertIn('palatinearcher_blazingfission_prop', refs)


if __name__ == '__main__':
    unittest.main()
