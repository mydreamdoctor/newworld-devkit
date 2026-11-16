#!/usr/bin/env python3
"""Tests for the generated registry + named-field loader."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from osv3 import parse_objectstream
import slice_view

HERE = os.path.dirname(os.path.abspath(__file__))
PLAYER = 'build/nw-corpus/player/slices/player.dynamicslice'


class TestRegistry(unittest.TestCase):
    def test_registry_loads(self):
        r = slice_view.registry()
        self.assertGreater(len(r['types']), 4300)
        self.assertGreater(len(r['field_names']), 6000)

    def test_known_type_and_field(self):
        # SliceComponent must be a registered type; 'm_worldTM' field resolves
        r = slice_view.registry()
        names = set(r['type_names'].values())
        self.assertIn('SliceComponent', names)
        self.assertIsNotNone(slice_view.field_name(0xd4925735))  # BaseClass1

    def test_crc_lowercase(self):
        import zlib
        h = zlib.crc32('actionname'.encode()) & 0xffffffff
        self.assertEqual(slice_view.field_name(h), 'actionName')


@unittest.skipUnless(os.path.isfile(PLAYER), 'corpus not extracted')
class TestNamedLoad(unittest.TestCase):
    def test_player_slice_named_fields(self):
        ver, root = parse_objectstream(open(PLAYER, 'rb').read())
        acc = {'e': 0, 'tr': 0, 'f': 0, 'fr': 0}
        def w(e):
            acc['e'] += 1
            acc['tr'] += e['id'] in slice_view.registry()['type_names']
            if 'crc' in e:
                acc['f'] += 1
                acc['fr'] += slice_view.field_name(e['crc']) is not None
            for c in e['ch']:
                w(c)
        w(root)
        self.assertGreater(acc['tr'] / acc['e'], 0.9)
        self.assertGreater(acc['fr'] / acc['f'], 0.99)

    def test_transform_component_named(self):
        ver, root = parse_objectstream(open(PLAYER, 'rb').read())
        text = slice_view._fmt(slice_view.view(root))
        self.assertIn('GameTransformComponent', text)
        self.assertIn('m_worldTM', text)


if __name__ == '__main__':
    unittest.main()
