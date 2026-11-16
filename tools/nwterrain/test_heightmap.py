#!/usr/bin/env python3
"""Heightmap codec tests: real-file decode, encode->decode round-trip
(LZW and uncompressed), predictor correctness, malformed inputs."""
import array, glob, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from heightmap import decode, encode, Heightmap, lzw_decode, lzw_encode

CORPUS = 'build/nw-corpus/terrain'
ARENA = (CORPUS + '/arena/sharedassets/coatlicue/nw_arena_3v3_04/'
         'regions/r_+00_+00/region.heightmap')


class TestCodec(unittest.TestCase):
    def test_synthetic_roundtrip_lzw(self):
        hm = Heightmap(64, 64)
        hm.raw = array.array('H', [(x * 7 + y * 13) & 0xffff
                                   for y in range(64) for x in range(64)])
        hm2 = decode(encode(hm))
        self.assertEqual(list(hm.raw), list(hm2.raw))
        self.assertEqual((hm.w, hm.h), (hm2.w, hm2.h))

    def test_synthetic_roundtrip_raw(self):
        hm = Heightmap(32, 40)
        hm.raw = array.array('H', [i & 0xffff for i in range(32 * 40)])
        hm2 = decode(encode(hm, lzw=False))
        self.assertEqual(list(hm.raw), list(hm2.raw))

    def test_odd_size_roundtrip(self):
        # height not a multiple of rps=4 exercises the short last strip
        hm = Heightmap(50, 37)
        hm.raw = array.array('H', [(i * 3) & 0xffff for i in range(50 * 37)])
        self.assertEqual(list(hm.raw), list(decode(encode(hm)).raw))
        self.assertEqual(list(hm.raw), list(decode(encode(hm, lzw=False)).raw))

    def test_lzw_random_data(self):
        import random
        rnd = random.Random(9)
        d = bytes(rnd.randrange(256) for _ in range(10000))
        self.assertEqual(lzw_decode(lzw_encode(d), len(d)), d)

    def test_bad_magic(self):
        with self.assertRaises(ValueError):
            decode(b'ZZ' + b'\x00' * 30)

    def test_truncated(self):
        d = open(ARENA, 'rb').read() if os.path.isfile(ARENA) else b'II*\x00'
        with self.assertRaises(Exception):
            decode(d[:20])


@unittest.skipUnless(os.path.isfile(ARENA), 'corpus not extracted')
class TestRealFiles(unittest.TestCase):
    def test_arena_dims_and_values(self):
        hm = decode(open(ARENA, 'rb').read())
        self.assertEqual((hm.w, hm.h), (2048, 2048))
        # arena terrain has real variation and plausible raw heights
        mn, mx = min(hm.raw), max(hm.raw)
        self.assertLess(mn, mx)
        self.assertLess(mx, 65536)
        # Lockstep-derived check: region.heightmap * 2048/65535 gives metres;
        # arena has terrain above ocean level 40m -> raw > 1310 somewhere
        self.assertGreater(mx, int(40 * 65535 / 2048))

    def test_all_real_files_roundtrip(self):
        files = sorted(glob.glob(CORPUS + '/**/*.heightmap', recursive=True))
        self.assertGreater(len(files), 0)
        for f in files:
            hm = decode(open(f, 'rb').read())
            for mode in (True, False):
                hm2 = decode(encode(hm, lzw=mode))
                self.assertEqual(list(hm.raw), list(hm2.raw), f)


if __name__ == '__main__':
    unittest.main()
