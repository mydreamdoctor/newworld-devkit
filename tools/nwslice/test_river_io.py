#!/usr/bin/env python3
"""river_io tests: extract/apply round-trip on the terrain_water corpus,
same-count edits, point add/remove, and river param patching."""
import copy, glob, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import river_io

CORPUS = 'build/nw-corpus/terrain_water/slices/terrain_water'
SLICES = sorted(glob.glob(os.path.join(CORPUS, '**', '*.dynamicslice'),
                          recursive=True))
RIVER = os.path.join(CORPUS, 'template_modes',
                     'template_modes_valley_river_a.dynamicslice')


def _raw(fn):
    return open(fn, 'rb').read()


class TestRoundTrip(unittest.TestCase):
    def test_unchanged_apply_is_byte_identical(self):
        for fn in SLICES:
            raw = _raw(fn)
            try:
                m = river_io.extract(raw)
            except KeyError:
                continue  # not a river slice (e.g. *_add particle slices)
            self.assertEqual(river_io.apply(m, raw), raw, fn)


@unittest.skipUnless(os.path.isfile(RIVER), 'corpus missing')
class TestEdit(unittest.TestCase):
    def setUp(self):
        self.raw = _raw(RIVER)
        self.m = river_io.extract(self.raw)

    def test_vertex_edit_roundtrip(self):
        self.m['spline']['points'][0]['pos'] = [1.5, 2.5, 3.5]
        self.m['spline']['points'][0]['forward'] = [0.5, 2.5, 3.5]
        out = river_io.apply(self.m, self.raw)
        m2 = river_io.extract(out)
        self.assertEqual(m2['spline']['points'][0]['pos'], [1.5, 2.5, 3.5])
        self.assertEqual(m2['spline']['points'][0]['forward'], [0.5, 2.5, 3.5])
        # untouched point unchanged
        self.assertEqual(m2['spline']['points'][1],
                         self.m['spline']['points'][1])

    def test_point_append_and_remove(self):
        n = len(self.m['spline']['points'])
        self.m['spline']['points'].append(
            copy.deepcopy(self.m['spline']['points'][-1]))
        out = river_io.apply(self.m, self.raw)
        self.assertEqual(len(river_io.extract(out)['spline']['points']), n + 1)
        self.m['spline']['points'] = self.m['spline']['points'][:n - 1]
        out = river_io.apply(self.m, self.raw)
        self.assertEqual(len(river_io.extract(out)['spline']['points']), n - 1)

    def test_width_and_length_edit(self):
        self.m['river']['defaultWidth'] = 42.0
        self.m['river']['widthKeys'][1] = 7.5
        self.m['river']['SegmentLength'] = 5.0
        out = river_io.apply(self.m, self.raw)
        m2 = river_io.extract(out)
        self.assertEqual(m2['river']['defaultWidth'], 42.0)
        self.assertEqual(m2['river']['widthKeys'][1], 7.5)
        self.assertEqual(m2['river']['SegmentLength'], 5.0)

    def test_non_river_slice_raises(self):
        add = os.path.join(CORPUS, 'nw_trench_00',
                           'nw_trench_00_river_a_add.dynamicslice')
        if os.path.isfile(add):
            with self.assertRaises(KeyError):
                river_io.extract(_raw(add))


if __name__ == '__main__':
    unittest.main()
