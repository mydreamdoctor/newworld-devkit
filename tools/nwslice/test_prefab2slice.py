import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prefab2slice
import river_io
from osv3 import parse_objectstream
from slice2prefab import convert as fwd_convert, _entities

SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      '..', '..', 'build', 'nw-corpus', 'player', 'slices',
                      'player.dynamicslice')


def _sample():
    return open(SAMPLE, 'rb').read() if os.path.isfile(SAMPLE) else None


def test_untouched_roundtrip_byte_identical():
    raw = _sample()
    if raw is None:
        return  # corpus not present in this checkout
    prefab, _ = fwd_convert(raw, 'player')
    out, rep = prefab2slice.convert(raw, prefab)
    assert rep['updated'] == 0
    assert out == raw


def test_transform_patch_is_surgical():
    raw = _sample()
    if raw is None:
        return
    prefab, _ = fwd_convert(raw, 'player')
    first = next(iter(prefab['Entities'].values()))
    first['Components']['Component_[0]']['Transform Data']['Translate'] \
        = [1.5, 2.5, 3.5]
    out, rep = prefab2slice.convert(raw, prefab)
    assert rep['updated'] == 1
    # only the patched transform's bytes differ
    diffs = sum(1 for a, b in zip(raw, out) if a != b)
    assert diffs < 64
    assert len(out) == len(raw)
    # new translation is present in the re-parsed output
    _, root = parse_objectstream(out)
    ent = _entities(root)[0]
    tm = river_io._f32s(
        river_io._by_crc(ent[1]['GameTransformComponent'], 'm_worldTM')['val'])
    assert tm[9:12] == [1.5, 2.5, 3.5]
