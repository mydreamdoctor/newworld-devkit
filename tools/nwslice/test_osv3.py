#!/usr/bin/env python3
"""Unit tests for the ObjectStream v3 codec: field combinations, size-field
widths, malformed input, and decode->encode identity."""
import os, struct, sys, unittest, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from osv3 import parse_objectstream, encode_objectstream

U = uuid.UUID('01234567-89ab-cdef-0123-456789abcdef')
U2 = uuid.UUID('deadbeef-1234-5678-9abc-def012345678')
HDR = b'\x00\x00\x00\x00\x03'


def elem(id_=U, crc=None, ver=None, val=None, ch=None):
    e = {'id': str(id_), 'ch': ch or []}
    if crc is not None:
        e['crc'] = crc
    if ver is not None:
        e['ver'] = ver
    if val is not None:
        e['val'] = val
    return e


def rt(e):
    """decode(encode(e)) == e and encode is byte-stable on second pass."""
    d = encode_objectstream(e)
    ver, e2 = parse_objectstream(d)
    return d, ver, e2


class TestElementFields(unittest.TestCase):
    def test_minimal_root_no_fields(self):
        d, ver, e2 = rt(elem())
        self.assertEqual(ver, 3)
        # flags(0x08) + uuid + terminator + pseudo-root terminator
        self.assertEqual(d, HDR + b'\x08' + U.bytes + b'\x00\x00')
        self.assertEqual(e2['id'], str(U))
        self.assertNotIn('crc', e2)
        self.assertNotIn('ver', e2)
        self.assertNotIn('val', e2)

    def test_crc_present(self):
        d, _, e2 = rt(elem(crc=0xDEADBEEF))
        self.assertEqual(d[5], 0x48)                      # 0x08|0x40
        self.assertEqual(d[6:10], struct.pack('>I', 0xDEADBEEF))
        self.assertEqual(e2['crc'], 0xDEADBEEF)

    def test_version_present(self):
        d, _, e2 = rt(elem(ver=0x2A))
        self.assertEqual(d[5], 0x88)                      # 0x08|0x80
        self.assertEqual(d[6], 0x2A)
        self.assertEqual(e2['ver'], 0x2A)

    def test_crc_and_version(self):
        d, _, e2 = rt(elem(crc=1, ver=255))
        self.assertEqual(d[5], 0xC8)                      # 0x08|0x40|0x80
        self.assertEqual(e2['crc'], 1)
        self.assertEqual(e2['ver'], 255)

    def test_empty_value(self):
        d, _, e2 = rt(elem(val=b''))
        self.assertEqual(d[5], 0x18)                      # 0x08|0x10|sz=0
        self.assertEqual(e2['val'], b'')

    def test_inline_sizes(self):
        for n in (1, 3, 7):
            v = bytes(range(n))
            d, _, e2 = rt(elem(val=v))
            self.assertEqual(d[5], 0x18 | n)              # 0x08|0x10|inline sz, no 0x20
            self.assertEqual(e2['val'], v)

    def test_ext_size_1(self):
        v = b'x' * 200
        d, _, e2 = rt(elem(val=v))
        self.assertEqual(d[5], 0x38 | 1)                  # 0x08|0x10|0x20|w=1
        self.assertEqual(d[6 + 16], 200)                  # size byte after uuid
        self.assertEqual(e2['val'], v)

    def test_ext_size_2(self):
        v = b'y' * 700
        d, _, e2 = rt(elem(val=v))
        self.assertEqual(d[5], 0x38 | 2)
        self.assertEqual(d[6 + 16:8 + 16], struct.pack('>H', 700))
        self.assertEqual(e2['val'], v)

    def test_ext_size_4(self):
        v = b'z' * 70000
        d, _, e2 = rt(elem(val=v))
        self.assertEqual(d[5], 0x38 | 4)
        self.assertEqual(d[6 + 16:10 + 16], struct.pack('>I', 70000))
        self.assertEqual(e2['val'], v)

    def test_ext_size_boundary_256(self):
        d, _, _ = rt(elem(val=b'a' * 255))
        self.assertEqual(d[5] & 7, 1)
        d, _, _ = rt(elem(val=b'a' * 256))
        self.assertEqual(d[5] & 7, 2)


class TestStructure(unittest.TestCase):
    def test_nesting(self):
        leaf = elem(val=b'leaf')
        mid = elem(ch=[leaf])
        d, _, e2 = rt(elem(ch=[mid, leaf]))
        self.assertEqual(len(e2['ch']), 2)
        self.assertEqual(e2['ch'][0]['ch'][0]['val'], b'leaf')

    def test_duplicate_fields_preserved(self):
        # two children with identical crc (duplicate field name) stay ordered
        a, b = elem(crc=0xAB, val=b'1'), elem(crc=0xAB, val=b'2')
        _, _, e2 = rt(elem(ch=[a, b]))
        self.assertEqual([c['val'] for c in e2['ch']], [b'1', b'2'])
        self.assertEqual([c['crc'] for c in e2['ch']], [0xAB, 0xAB])

    def test_order_and_ids(self):
        _, _, e2 = rt(elem(ch=[elem(id_=U2), elem()]))
        self.assertEqual(e2['ch'][0]['id'], str(U2))
        self.assertEqual(e2['ch'][1]['id'], str(U))


class TestMalformed(unittest.TestCase):
    def test_bad_stream_tag(self):
        with self.assertRaises(ValueError):
            parse_objectstream(b'\x01' + HDR[1:] + b'\x08' + U.bytes + b'\x00\x00')

    def test_bad_version(self):
        with self.assertRaises(ValueError):
            parse_objectstream(b'\x00\x00\x00\x00\x02' + b'\x08' + U.bytes + b'\x00\x00')

    def test_bad_flags(self):
        with self.assertRaises(ValueError):
            parse_objectstream(HDR + b'\x04' + U.bytes + b'\x00\x00')  # no 0x08 bit

    def test_truncated_uuid(self):
        with self.assertRaises(ValueError):
            parse_objectstream(HDR + b'\x08' + U.bytes[:8] + b'\x00\x00')

    def test_truncated_value(self):
        # claims 5-byte value, supplies 2
        with self.assertRaises(ValueError):
            parse_objectstream(HDR + b'\x1d' + U.bytes + b'ab' + b'\x00\x00')

    def test_unclosed_element(self):
        with self.assertRaises(ValueError):
            parse_objectstream(HDR + b'\x08' + U.bytes + b'\x00')  # only one terminator

    def test_trailing_garbage(self):
        with self.assertRaises(ValueError):
            parse_objectstream(HDR + b'\x08' + U.bytes + b'\x00\x00\xff')


class TestRealBytes(unittest.TestCase):
    def test_handbuilt_stream_decodes(self):
        # manually assembled: root w/ crc+ver+3-byte val, one child, dup field
        body = (
            b'\xdb' + struct.pack('>I', 0x1111) + b'\x07' + U.bytes +
            b'abc' +
            b'\x48' + struct.pack('>I', 0x2222) + U2.bytes + b'\x00' +
            b'\x00')
        d = HDR + body + b'\x00'
        ver, root = parse_objectstream(d)
        self.assertEqual(root['crc'], 0x1111)
        self.assertEqual(root['ver'], 7)
        self.assertEqual(root['val'], b'abc')
        self.assertEqual(root['ch'][0]['crc'], 0x2222)
        self.assertEqual(encode_objectstream(root), d)   # byte-exact re-encode


if __name__ == '__main__':
    unittest.main()
