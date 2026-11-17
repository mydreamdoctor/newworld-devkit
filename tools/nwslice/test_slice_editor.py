import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
EDITOR = os.path.join(HERE, 'slice_editor.py')
SAMPLES = [
    os.path.join(HERE, '..', '..', 'build', 'nw-corpus', 'player',
                 'slices', 'player.dynamicslice'),
    os.path.join(HERE, '..', '..', 'build', 'nw-corpus', 'regions', 'slices',
                 'pois', 'territories', 'r_+04_+00_pois.dynamicslice'),
]


def test_slice_editor_selftest(tmp_path):
    if not os.environ.get('DISPLAY'):
        return  # Qt needs the display; CI skips
    ran = False
    for i, sample in enumerate(SAMPLES):
        if not os.path.isfile(sample):
            continue
        ran = True
        src = tmp_path / ('edit%d.dynamicslice' % i)
        shutil.copyfile(sample, src)
        r = subprocess.run(
            [sys.executable, EDITOR, '--selftest', str(src)],
            capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
        assert 'selftest OK' in r.stdout
        assert os.path.isfile(str(src) + '.bak')
    if not ran:
        return  # corpus not present in this checkout
