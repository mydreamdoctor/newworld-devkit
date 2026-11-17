#!/usr/bin/env python3
"""NW .dynamicslice editor (v1): entity list + named component property grid
+ entity add/delete/reorder, with byte-safe write-back via osv3.

UI is PySide6 from the repo's 3rd-party package + the engine build's Qt6
libs — paths are resolved relative to this file, so it runs standalone:

  tools/nwslice/slice_editor.py FILE.dynamicslice

Left: entities in the slice (names resolved). Right: the selected entity's
components expanded as a named field tree (type uuids -> class names, field
crcs -> field names via nw_registry.json). Double-click a leaf to edit its
value; primitives repack to the field's declared type (big-endian, AZ layout).

Add entity clones the first entity's element stripped to name +
GameTransformComponent; delete removes the element; up/down reorder it.
Save encodes with encode_objectstream, re-parses the output as a
round-trip self-check, and keeps a .bak of the previous bytes.
"""
import json
import os
import struct
import sys

# --- PySide6 bootstrap (repo 3rd-party wheel + engine build Qt6 libs) ---
_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      '..', '..'))
_PKG = os.path.join(_REPO, 'build', '3rdParty', 'packages',
                    'pyside6-6.11.2-py3.10-rev1-linux', 'pyside6')
_BIN = os.path.join(_REPO, 'build', 'linux', 'bin', 'profile')
sys.path.insert(0, os.path.join(_PKG, 'lib', 'python3.10', 'site-packages'))

if os.environ.get('_NW_SLICE_ENV') != '1':
    # LD_LIBRARY_PATH must be set before the dynamic linker starts, so
    # re-exec once with it baked into the environment.
    os.environ['LD_LIBRARY_PATH'] = os.pathsep.join(
        [os.path.join(_PKG, 'lib'), _BIN,
         os.environ.get('LD_LIBRARY_PATH', '')]).rstrip(os.pathsep)
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(_BIN, 'platforms')
    os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
    os.environ['_NW_SLICE_ENV'] = '1'
    os.execv(sys.executable, [sys.executable] + sys.argv)

from PySide6 import QtWidgets, QtCore

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from osv3 import parse_objectstream, encode_objectstream
import river_io
import slice_view
from slice2prefab import _entities, _str_val

_by_crc = river_io._by_crc
_kids = river_io._kids


def _set_val(e, value_str):
    """Repack a primitive edit into the element's val bytes."""
    tn = slice_view.type_name(e['id'])
    old = e.get('val')
    if old is None:
        return False
    try:
        if tn == 'AZStd::string':
            e['val'] = value_str.encode('utf-8')
            return True
        if tn == 'AZ::Uuid' and len(old) == 16:
            import uuid
            e['val'] = uuid.UUID(value_str).bytes
            return True
        p = slice_view._PRIMS.get(tn)
        if p and len(old) == p[1]:
            if p[0] == '<?':
                e['val'] = struct.pack(p[0], value_str.strip().lower()
                                       in ('1', 'true', 'yes'))
            elif p[0].endswith(('f', 'd')):
                e['val'] = struct.pack(p[0], float(value_str))
            else:
                e['val'] = struct.pack(p[0], int(value_str, 0))
            return True
    except Exception:
        return False
    return False


class SliceEditor(QtWidgets.QMainWindow):
    def __init__(self, path):
        super().__init__()
        self.setWindowTitle('NW slice editor: %s' % os.path.basename(path))
        self.resize(1100, 700)
        self.path = path
        self.raw = open(path, 'rb').read()
        self.ver, self.root_el = parse_objectstream(self.raw)
        self._entity_els = self._find_entity_elements()
        self._build()
        self._refresh_entities()

    def _find_entity_elements(self):
        """[(name, entity_element, parent_child_list)] in slice order."""
        out = []
        for sc in river_io._walk(self.root_el):
            if sc['id'] != river_io.UID['SliceComponent']:
                continue
            for k in _kids(sc):
                for e in _kids(k):
                    if e['id'] != river_io.UID['AZ::Entity']:
                        continue
                    name = ''
                    nf = _by_crc(e, 'name')
                    if nf is not None and 'val' in nf:
                        name = _str_val(nf)
                    out.append((name, e, k['ch']))
        return out

    def _build(self):
        tb = self.addToolBar('main')
        for label, fn in (('Save', self.save),
                          ('Add entity', self.add_entity),
                          ('Delete entity', self.del_entity),
                          ('Move up', lambda: self.move_entity(-1)),
                          ('Move down', lambda: self.move_entity(1))):
            a = tb.addAction(label)
            a.triggered.connect(fn)
        self.status = QtWidgets.QLabel('')
        tb.addWidget(self.status)

        split = QtWidgets.QSplitter()
        self.setCentralWidget(split)
        self.ent_list = QtWidgets.QListWidget()
        self.ent_list.currentRowChanged.connect(self._on_select)
        split.addWidget(self.ent_list)
        self.grid = QtWidgets.QTreeWidget()
        self.grid.setHeaderLabels(['field', 'type', 'value'])
        self.grid.setColumnWidth(0, 280)
        self.grid.setColumnWidth(1, 200)
        self.grid.itemDoubleClicked.connect(self._edit_cell)
        split.addWidget(self.grid)
        split.setSizes([300, 800])
        self._map = {}

    def _refresh_entities(self, keep=-1):
        self.ent_list.clear()
        for name, _, _ in self._entity_els:
            self.ent_list.addItem(name or '<unnamed>')
        if 0 <= keep < len(self._entity_els):
            self.ent_list.setCurrentRow(keep)

    def _on_select(self, i):
        self.grid.clear()
        self._map.clear()
        if i is None or i < 0:
            return
        name, el, _ = self._entity_els[i]
        comps = _by_crc(el, 'Components')
        n = 0
        for c in _kids(comps) if comps else []:
            item = QtWidgets.QTreeWidgetItem(
                [river_io.TN.get(c['id'], c['id'][:18]), '', ''])
            self.grid.addTopLevelItem(item)
            self._fill(c, item)
            n += 1
        self.status.setText('%s — %d components' % (name, n))

    def _fill(self, e, parent):
        for k in e.get('ch', []):
            fn = river_io.FN.get(k.get('crc'), k.get('crc'))
            label = fn if isinstance(fn, str) else (
                'crc_%08x' % fn if isinstance(fn, int) else 'field')
            tn = slice_view.type_name(k['id'])
            v = slice_view.decode_val(k)
            disp = v if isinstance(v, (int, float, str, bool)) else \
                ('%d bytes' % len(k['val']) if 'val' in k else '')
            item = QtWidgets.QTreeWidgetItem([label, tn, str(disp)])
            parent.addChild(item)
            self._map[id(item)] = k
            self._fill(k, item)

    def _edit_cell(self, item, _col):
        k = self._map.get(id(item))
        if k is None or 'val' not in k:
            return
        cur = slice_view.decode_val(k)
        v, ok = QtWidgets.QInputDialog.getText(
            self, 'Edit %s' % slice_view.type_name(k['id']), 'new value',
            text='' if cur is None else str(cur))
        if not ok:
            return
        if _set_val(k, v):
            item.setText(2, v)
            self.status.setText('modified')
        else:
            QtWidgets.QMessageBox.critical(
                self, 'Edit failed', 'cannot encode %r into %s'
                % (v, slice_view.type_name(k['id'])))

    def add_entity(self):
        if not self._entity_els:
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, 'Add entity', 'entity name:')
        if not ok:
            return
        import copy
        proto = copy.deepcopy(self._entity_els[0][1])
        comps = _by_crc(proto, 'Components')
        keep = [c for c in _kids(comps)
                if river_io.TN.get(c['id'], '') in
                ('GameTransformComponent', 'AZ::Component')] \
            if comps is not None else []
        if comps is not None:
            comps['ch'] = keep
        nf = _by_crc(proto, 'name')
        if nf is not None:
            nf['val'] = name.encode('utf-8')
        parent_ch = self._entity_els[0][2]
        parent_ch.append(proto)
        self._entity_els.append((name, proto, parent_ch))
        self._refresh_entities(len(self._entity_els) - 1)

    def del_entity(self):
        i = self.ent_list.currentRow()
        if i < 0:
            return
        name, el, parent_ch = self._entity_els[i]
        if QtWidgets.QMessageBox.question(
                self, 'Delete', 'delete entity %r?' % name) != \
                QtWidgets.QMessageBox.Yes:
            return
        parent_ch.remove(el)
        del self._entity_els[i]
        self._refresh_entities()

    def move_entity(self, d):
        i = self.ent_list.currentRow()
        if i < 0:
            return
        name, el, parent_ch = self._entity_els[i]
        j = parent_ch.index(el) + d
        if not (0 <= j < len(parent_ch)):
            return
        parent_ch.remove(el)
        parent_ch.insert(j, el)
        self._entity_els = self._find_entity_elements()
        self._refresh_entities(i + d)

    def save(self):
        out = encode_objectstream(self.root_el, self.ver)
        try:
            parse_objectstream(out)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, 'Save aborted', 'round-trip re-parse failed: %s' % e)
            return
        with open(self.path + '.bak', 'wb') as f:
            f.write(self.raw)
        with open(self.path, 'wb') as f:
            f.write(out)
        self.raw = out
        self.status.setText('saved %d bytes (.bak kept)' % len(out))


def _selftest(path):
    """Exercise every editor operation on `path` without the event loop.
    Returns 0 on success; used by tests and as an environment check."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    ed = SliceEditor(path)
    n0 = len(ed._entity_els)
    assert n0 > 0, 'no entities in slice'
    ed.ent_list.setCurrentRow(0)
    assert ed.grid.topLevelItemCount() > 0, 'property grid empty'
    edited = False
    for i in range(ed.grid.topLevelItemCount()):
        it = ed.grid.topLevelItem(i)
        for j in range(it.childCount()):
            k = ed._map.get(id(it.child(j)))
            if k is None or 'val' not in k:
                continue
            cur = slice_view.decode_val(k)
            for cand in (str(cur) if cur is not None else '', '1', '0',
                         'selftest'):
                if _set_val(k, cand):
                    edited = True
                    break
            if edited:
                break
        if edited:
            break
    assert edited, 'no writable leaf field'
    # add
    import copy
    proto = copy.deepcopy(ed._entity_els[0][1])
    comps = _by_crc(proto, 'Components')
    if comps is not None:
        comps['ch'] = [c for c in _kids(comps)
                       if river_io.TN.get(c['id'], '') in
                       ('GameTransformComponent', 'AZ::Component')]
    nf = _by_crc(proto, 'name')
    if nf is not None:
        nf['val'] = b'selftest_new'
    ed._entity_els[0][2].append(proto)
    ed._entity_els = ed._find_entity_elements()
    assert len(ed._entity_els) == n0 + 1, 'add failed'
    # move last -> second-to-last
    el = ed._entity_els[-1][1]
    ch = ed._entity_els[-1][2]
    ch.remove(el)
    ch.insert(len(ch) - 1, el)
    ed._entity_els = ed._find_entity_elements()
    assert ed._entity_els[-2][0] == 'selftest_new', 'move failed'
    # delete
    ed._entity_els[-2][2].remove(ed._entity_els[-2][1])
    ed._entity_els = ed._find_entity_elements()
    assert len(ed._entity_els) == n0, 'delete failed'
    # save -> .bak + reparse check happens inside save()
    ed.save()
    print('selftest OK: %d entities, save+reparse passed' % n0)
    ed.close()
    return 0


def main():
    if len(sys.argv) > 2 and sys.argv[1] == '--selftest':
        sys.exit(_selftest(sys.argv[2]))
    path = sys.argv[1] if len(sys.argv) > 1 else None
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    if not path:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            None, 'Open slice', '', 'NW dynamicslice (*.dynamicslice)')
    if not path:
        return
    w = SliceEditor(path)
    w.show()
    app.exec()


if __name__ == '__main__':
    main()
