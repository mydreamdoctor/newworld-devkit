"""New World ground-cover vegetation import.

The game scatters its ground cover with Coatlicue's procedural vegetation
system (``region.vegetation`` inside ``VegetationStrm*.pak``). That file is
a 162 MB undocumented quantised blob, so this module rebuilds the cover
from data we can read: the ground-cover models the level's own foliage
slices place, and the level's terrain.

What it does, per level:

  1. reads every foliage/decals dynamicslice and collects the ground-cover
     models they reference (``*groundcover*``, ``*flatgreens*``, ``*fern*``)
     together with how many instances the artists placed of each,
  2. writes one single-mesh prefab per model under ``<project>/nwveg/``
     (O3DE's Vegetation gem spawns prefabs, not meshes),
  3. resolves each prefab's product asset id from the Asset Processor
     database,
  4. adds (or replaces) a ``nw_vegetation`` entity in the level prefab that
     scatters those prefabs over the terrain inside a box around the level.

The result is a repeatable import: rebuild the level and the cover comes
back with the same models, weights and area.
"""

import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                + '/nwslice')
import slice2prefab  # noqa: E402

TRANSFORM_COMPONENT = '{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0}'
VEG_DIR = 'nwveg'
ENTITY_NAME = 'nw_vegetation'
DECK_ENTITY_NAME = 'nw_vegetation_deck'

# Models the game uses for low ground cover rather than for bushes/trees.
GROUND_COVER = re.compile(r'(groundcover|flatgreens|fern)', re.I)
CGF_RE = re.compile(rb'objects/[a-zA-Z0-9_/\.\-]+\.[Cc][Gg][Ff]')
# Largest scatter box per axis, in metres (see the clamp in apply()).
MAX_BOX = 140.0


def collect_models(slice_paths):
    """{cgf path: instance count} for the level's ground-cover models."""
    counts = {}
    for path in slice_paths:
        try:
            raw = open(path, 'rb').read()
        except OSError:
            continue
        for m in CGF_RE.finditer(raw):
            cgf = m.group(0).decode('utf8', 'replace')
            if GROUND_COVER.search(cgf.rsplit('/', 1)[-1]):
                counts[cgf] = counts.get(cgf, 0) + 1
    return counts


def _instance_counts(slice_paths, models):
    """Per-model placed-instance counts (instanced meshes expanded)."""
    import river_io
    from osv3 import parse_objectstream
    counts = {m: 0 for m in models}
    for path in slice_paths:
        try:
            _ver, root = parse_objectstream(open(path, 'rb').read())
        except Exception:
            continue
        for _name, comps in slice2prefab._entities(root):
            for cel in comps.values():
                asset = slice2prefab._mesh_asset(cel)
                if asset in counts:
                    n = 0
                    for k in slice2prefab._walk(cel):
                        if k.get('crc') == 0xc41bd26a:
                            for t in river_io._kids(k):
                                v = t.get('val')
                                if v and len(v) == 48:
                                    n += 1
                    counts[asset] += max(n, 1)
                    break
    return counts


def model_prefab(cgf_path):
    """One-mesh prefab dict for a ground-cover model."""
    stem = cgf_path[:-4].rsplit('/', 1)[-1]
    name = 'veg_' + stem
    model_asset = slice2prefab._model_asset(cgf_path)
    return name, {
        'ContainerEntity': {
            'Id': 'Entity_[1]', 'Name': name,
            'Components': {
                'Component_[0]': {
                    '$type': TRANSFORM_COMPONENT, 'Id': 2,
                    'Transform Data': {'Translate': [0.0, 0.0, 0.0]},
                    'Parent Entity': ''},
                'Component_[1]': {'$type': 'EditorPrefabComponent',
                                  'Id': 3}}},
        'Entities': {
            'Entity_[2]': {
                'Id': 'Entity_[2]', 'Name': name,
                'Components': {
                    'Component_[0]': {
                        '$type': TRANSFORM_COMPONENT, 'Id': 4,
                        'Transform Data': {'Translate': [0.0, 0.0, 0.0]},
                        'Parent Entity': 'Entity_[1]'},
                    'Component_[1]': {
                        '$type': 'AZ::Render::EditorMeshComponent', 'Id': 5,
                        'Controller': {'Configuration': {
                            'ModelAsset': model_asset}}}}}},
    }


def write_prefabs(project_root, models):
    """Write one prefab per model; returns [(prefab rel path, count)]."""
    out_dir = os.path.join(project_root, VEG_DIR)
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for cgf, count in sorted(models.items()):
        name, prefab = model_prefab(cgf)
        rel = '%s/%s.prefab' % (VEG_DIR, name)
        with open(os.path.join(project_root, rel), 'w') as f:
            json.dump(prefab, f, indent=2)
        written.append((rel, count))
    return written


def asset_id(project_root, prefab_rel):
    """({guid}, subId) for a prefab's spawnable product.

    The guid is AZ::Uuid::CreateName of the source path; the subId is a
    product-side hash, so it is read from the Asset Processor database
    (the prefabs must have been processed before this runs)."""
    guid = slice2prefab._asset_guid(prefab_rel)
    db = os.path.join(project_root, 'Cache', 'assetdb.sqlite')
    product = prefab_rel[:-len('.prefab')] + '.spawnable'
    sub = 0
    if os.path.isfile(db):
        con = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
        try:
            for (name, subid) in con.execute(
                    'select ProductName, SubID from Products '
                    'where ProductName like ?', ('%/' + product,)):
                if name.lower().endswith(product.lower()):
                    sub = subid & 0xffffffff
                    break
        finally:
            con.close()
    return '{%s}' % guid, sub


def descriptors(project_root, written):
    out = []
    for rel, _count in written:
        guid, sub = asset_id(project_root, rel)
        # Only the instance spawner is written: the editor's own serialized
        # form omits the remaining fields, and an enum written as a string
        # here makes the prefab patch fail ("not a valid index").
        out.append({
            'InstanceSpawner': {'SpawnableAsset': {
                'assetId': {'guid': guid, 'subId': sub},
                'assetHint': rel[:-len('.prefab')] + '.spawnable'}}})
    return out


def vegetation_entity(centre, size, descs, lift=0.0):
    """Level entity that scatters `descs` over the terrain in a box.

    `lift` raises every instance by that many metres. It exists because
    O3DE's vegetation only samples SurfaceData, i.e. the terrain, and a
    level whose walkable floor is a mesh deck above the terrain needs the
    cover lifted onto the deck."""
    empty_gradient = {'GradientId': ''}
    return {
        'Name': ENTITY_NAME,
        'Components': {
            'EditorBoxShapeComponent': {
                '$type': 'EditorBoxShapeComponent',
                'BoxShape': {'Configuration': {'Dimensions': list(size)}}},
            'EditorDescriptorListComponent': {
                '$type': 'EditorDescriptorListComponent',
                'Configuration': {'Descriptors': descs}},
            'EditorSpawnerComponent': {
                '$type': 'EditorSpawnerComponent'},
            'EditorPositionModifierComponent': {
                '$type': 'EditorPositionModifierComponent',
                'Configuration': {
                    # A lifted layer must not re-snap to the terrain, or the
                    # lift is cancelled and the instances stay underground.
                    'AutoSnapToSurface': lift == 0.0,
                    'RangeMinX': -0.4, 'RangeMaxX': 0.4, 'GradientX': empty_gradient,
                    'RangeMinY': -0.4, 'RangeMaxY': 0.4, 'GradientY': empty_gradient,
                    'RangeMinZ': lift, 'RangeMaxZ': lift,
                    'GradientZ': empty_gradient}},
            'EditorRotationModifierComponent': {
                '$type': 'EditorRotationModifierComponent',
                'Configuration': {'GradientX': empty_gradient,
                                  'GradientY': empty_gradient,
                                  'GradientZ': empty_gradient}},
            'EditorScaleModifierComponent': {
                '$type': 'EditorScaleModifierComponent',
                'Configuration': {'RangeMin': 0.7, 'RangeMax': 1.35,
                                  'Gradient': empty_gradient}},
            'TransformComponent': {
                '$type': TRANSFORM_COMPONENT,
                'Parent Entity': 'Entity_[1]',
                'Transform Data': {'Translate': list(centre)}},
        }}


def _slice_bounds(slice_paths):
    """World-space XY/Z bounds of the level's placed entities."""
    lo = [1e18, 1e18, 1e18]
    hi = [-1e18, -1e18, -1e18]
    for path in slice_paths:
        try:
            prefab, _skipped = slice2prefab.convert(open(path, 'rb').read())
        except Exception:
            continue
        for ent in prefab['Entities'].values():
            for comp in ent['Components'].values():
                t = comp.get('Transform Data', {}).get('Translate')
                if t:
                    for i in range(3):
                        lo[i] = min(lo[i], t[i])
                        hi[i] = max(hi[i], t[i])
    if lo[0] > hi[0]:
        return None
    return lo, hi


def apply(level_prefab_path, project_root, slice_paths, centre=None,
          size=None, deck_lift=None, deck_size=None):
    """Add the vegetation layer to a level prefab. Returns a summary dict."""
    models = collect_models(slice_paths)
    if not models:
        return {'models': 0, 'entity': None}
    counts = _instance_counts(slice_paths, set(models))
    models = {m: max(counts.get(m, 0), 1) for m in models}
    written = write_prefabs(project_root, models)
    descs = descriptors(project_root, written)
    if centre is None:
        centre = (0.0, 0.0, 0.0)
    if size is None:
        bounds = _slice_bounds(slice_paths)
        if bounds:
            lo, hi = bounds
            # Clamp: the slices also carry markers and sun-blockers far
            # outside the playable area, and the Vegetation gem spawns one
            # instance per ~0.64 m^2, so a huge box would cost millions.
            size = tuple(min(max(hi[i] - lo[i], 40.0), MAX_BOX) for i in range(3))
        else:
            size = (120.0, 120.0, 70.0)

    level = json.load(open(level_prefab_path))
    eid = next((k for k, e in level['Entities'].items()
                if e.get('Name') == ENTITY_NAME), None)
    if eid is None:
        n = 1 + max([int(m.group(1)) for k in level['Entities']
                     for m in [re.search(r'Entity_\[(\d+)\]', k)] if m]
                    + [1])
        eid = 'Entity_[%d]' % n
    ent = vegetation_entity(centre, size, descs)
    ent['Id'] = eid
    level['Entities'][eid] = ent
    layers = [{'entity': eid, 'lift': 0.0, 'size': list(size)}]

    deck_id = next((k for k, e in level['Entities'].items()
                    if e.get('Name') == DECK_ENTITY_NAME), None)
    if deck_lift is not None:
        if deck_id is None:
            n = 1 + max([int(m.group(1)) for k in level['Entities']
                         for m in [re.search(r'Entity_\[(\d+)\]', k)] if m]
                        + [1])
            deck_id = 'Entity_[%d]' % n
        dent = vegetation_entity(centre, deck_size or size, descs,
                                 lift=deck_lift)
        dent['Name'] = DECK_ENTITY_NAME
        dent['Id'] = deck_id
        level['Entities'][deck_id] = dent
        layers.append({'entity': deck_id, 'lift': deck_lift,
                       'size': list(deck_size or size)})
    elif deck_id is not None:
        del level['Entities'][deck_id]

    with open(level_prefab_path, 'w') as f:
        json.dump(level, f, indent=1)
    return {'models': len(written), 'entity': eid,
            'centre': list(centre), 'size': list(size),
            'layers': layers,
            'prefabs': [r for r, _c in written]}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('level_prefab')
    ap.add_argument('--project', required=True, help='O3DE project root')
    ap.add_argument('--slice', required=True, nargs='+')
    ap.add_argument('--at', nargs=3, type=float, default=None)
    ap.add_argument('--deck-lift', type=float, default=None,
                    help='metres to raise a second layer onto a mesh floor '
                         'deck that sits above the terrain')
    ap.add_argument('--deck-size', nargs=3, type=float, default=None)
    a = ap.parse_args()
    print(apply(a.level_prefab, a.project, a.slice,
                tuple(a.at) if a.at else None,
                deck_lift=a.deck_lift,
                deck_size=tuple(a.deck_size) if a.deck_size else None))


if __name__ == '__main__':
    main()
