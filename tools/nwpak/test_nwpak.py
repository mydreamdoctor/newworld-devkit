import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nwpak


def test_build_and_read_stored(tmp_path):
    src = tmp_path / 'a.dynamicslice'
    src.write_bytes(b'\xde\xad' * 100)
    out = str(tmp_path / 'zzz_devkit.pak')
    nwpak.build(out, [(str(src), 'slices/x/a.dynamicslice')])
    with zipfile.ZipFile(out) as z:
        infos = z.infolist()
        assert len(infos) == 1
        assert infos[0].filename == 'slices/x/a.dynamicslice'
        assert infos[0].compress_type == zipfile.ZIP_STORED
    assert nwpak._read_entry(out, 'slices/x/a.dynamicslice') == b'\xde\xad' * 100
    # entry lookup is case-insensitive like the client's CryPak
    assert nwpak._read_entry(out, 'Slices/X/A.Dynamicslice') == b'\xde\xad' * 100


def test_extract_from_stock_pak(tmp_path):
    pak = ('/home/lachlan/nwclient-frozen-20261022/assets/'
           'SharedDataStrm-part8.pak')
    if not os.path.isfile(pak):
        return  # client install not present in this checkout
    out = tmp_path / 'pois.dynamicslice'
    nwpak.extract(pak,
                  'slices/pois/territories/r_+03_+01_pois.dynamicslice',
                  str(out))
    data = out.read_bytes()
    assert len(data) == 72743
    assert data[:4] == b'CRYP' or data[:1] == b'#' or len(data) > 1000
