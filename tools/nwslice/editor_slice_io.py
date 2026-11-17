#!/usr/bin/env python3
"""In-O3DE slice open/save bridge — run inside the Editor via pyRunFile.

  open_slice(slice_path, prefab_path)
      .dynamicslice -> .prefab via slice2prefab, then InstantiatePrefab:
      every slice entity lands in the level with the real editor gizmos,
      hierarchy and property inspector. Structural edits (add/delete)
      stay in the standalone editor (tools/nwslice/slice_editor.py).

  save_slice(slice_path, out_path=None)
      reads the live entities' world transforms by name and patches the
      ORIGINAL slice through prefab2slice: untouched entities stay
      byte-exact, moved entities get a surgical m_worldTM update.

Stateless by design: entities match by name, so the same functions work
in any later editor session.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import azlmbr.bus as bus
import azlmbr.components as components
import azlmbr.editor as editor
import azlmbr.entity as entity
import azlmbr.legacy.general as general

import prefab2slice
from osv3 import parse_objectstream
from slice2prefab import _entities
import river_io

import json


def open_slice(slice_path, prefab_path):
    """Convert slice_path to prefab_path, then open it as the current
    level. Returns True if the level opened. Run from a tick callback;
    entities appear over the next frames."""
    raw = open(slice_path, 'rb').read()
    name = os.path.splitext(os.path.basename(slice_path))[0]
    from slice2prefab import convert as s2p
    pf, skipped = s2p(raw, name)
    os.makedirs(os.path.dirname(prefab_path), exist_ok=True)
    with open(prefab_path, 'w') as f:
        json.dump(pf, f, indent=2)
    print('nw open_slice: %s -> %s (%d entities, %d skipped comp types)'
          % (slice_path, prefab_path, len(pf.get('Entities', {})),
             len(skipped)))
    return general.open_level_no_prompt(prefab_path)


def _slice_entity_names(slice_path):
    _, root = parse_objectstream(open(slice_path, 'rb').read())
    return [n for n, _ in _entities(root)]


def save_slice(slice_path, out_path=None):
    """Patch slice_path's transforms from the live level; write out_path
    (default: slice_path itself). Returns the prefab2slice report."""
    names = set(n for n in _slice_entity_names(slice_path) if n)
    search = entity.SearchFilter()
    ids = entity.SearchBus(bus.Broadcast, 'SearchEntities', search)
    pf_ents = {}
    i = 0
    for eid in ids:
        name = editor.EditorEntityInfoRequestBus(
            bus.Event, 'GetName', eid)
        if name not in names:
            continue
        i += 1
        tr = components.TransformBus(
            bus.Event, 'GetWorldTranslation', eid)
        rot = components.TransformBus(
            bus.Event, 'GetWorldRotation', eid)
        td = {'Translate': [float(tr.x), float(tr.y), float(tr.z)]}
        if rot is not None:
            td['Rotate'] = [float(math.degrees(rot.x)),
                            float(math.degrees(rot.y)),
                            float(math.degrees(rot.z))]
        key = 'Entity_[%d]' % i
        pf_ents[key] = {
            'Id': key, 'Name': name,
            'Components': {'Component_[0]': {'Transform Data': td}},
        }
    prefab_dom = {'Entities': pf_ents}
    raw = open(slice_path, 'rb').read()
    out, report = prefab2slice.convert(raw, prefab_dom)
    dst = out_path or slice_path
    with open(dst, 'wb') as f:
        f.write(out)
    parse_objectstream(out)  # round-trip check
    print('nw save_slice: %d live entities -> %s (%d patched, %d unmatched)'
          % (len(pf_ents), dst, report['updated'],
             len(report['unmatched_prefab'])))
    return report
