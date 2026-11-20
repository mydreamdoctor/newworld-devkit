import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nwmat import dds


def test_orient_coverage_mask_kept():
    # leaf-bright mask: mostly dark fill, a few bright leaf clusters
    m = bytes([0] * 900 + [255] * 100)
    out, inv = dds._orient_mask(m)
    assert inv is False and out == m


def test_orient_fill_dominant_mask_flipped():
    # fill-bright mask (velvet mesquite convention): mostly ~0.89, dark leaves
    m = bytes([227] * 700 + [30] * 300)
    out, inv = dds._orient_mask(m)
    assert inv is True
    assert out[0] == 255 - 227 and out[-1] == 255 - 30


def test_orient_uniform_bright_not_flipped():
    # a fully-opaque-ish map (no low content) must not flip
    m = bytes([200] * 1000)
    out, inv = dds._orient_mask(m)
    assert inv is False
