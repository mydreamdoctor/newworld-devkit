"""New World .mtl (CryEngine XML material) parser.

A .mtl file is a material library: a root <Material> whose <SubMaterials>
element holds one or more named <Material> children. Each sub-material
carries a Cry shader name, render flags, color/scalar params, a <Textures>
list of named texture slots and an optional <PublicParams> block.

SubMaterial fields:
    name, shader, genmask, string_genmask, surface_type,
    diffuse, specular, emittance  (rgba float tuples),
    opacity, shininess, alpha_test (floats),
    mtl_flags, vert_modif (ints),
    textures   {Map: File} e.g. {'Diffuse': 'objects/.../foo_diff.dds'},
    public_params {name: raw string}
"""
import os
import re
import xml.etree.ElementTree as ET


def _color(s, n=4):
    try:
        v = [float(x) for x in s.split(',')]
    except Exception:
        return None
    if len(v) < n:
        v += [1.0] * (n - len(v))
    return tuple(v[:n])


def _float(s, default=None):
    try:
        return float(s)
    except Exception:
        return default


def _int(s, default=0):
    try:
        return int(s)
    except Exception:
        return default


class SubMaterial(object):
    def __init__(self, el):
        a = el.attrib
        self.name = a.get('Name', '')
        self.shader = a.get('Shader', '')
        self.genmask = a.get('GenMask', '')
        self.string_genmask = a.get('StringGenMask', '')
        self.surface_type = a.get('SurfaceType', '')
        self.diffuse = _color(a.get('Diffuse', ''))
        self.specular = _color(a.get('Specular', ''))
        self.emittance = _color(a.get('Emittance', ''))
        self.opacity = _float(a.get('Opacity'), 1.0)
        self.shininess = _float(a.get('Shininess'), 0.0)
        self.alpha_test = _float(a.get('AlphaTest'), 0.0)
        self.mtl_flags = _int(a.get('MtlFlags'))
        self.vert_modif = _int(a.get('vertModifType'))
        self.textures = {}
        self.public_params = {}
        for child in el:
            if child.tag == 'Textures':
                for tex in child:
                    if tex.tag == 'Texture':
                        m = tex.attrib.get('Map', '')
                        f = tex.attrib.get('File', '')
                        if m and f:
                            self.textures[m] = f
            elif child.tag == 'PublicParams':
                self.public_params = dict(child.attrib)


class Mtl(object):
    """One parsed .mtl file."""

    def __init__(self):
        self.subs = []          # list[SubMaterial]
        self.by_name = {}

    @classmethod
    def parse(cls, data):
        m = cls()
        root = ET.fromstring(data)
        if root.tag != 'Material':
            raise ValueError('not a Material document')
        subs = root.find('SubMaterials')
        if subs is not None:
            for el in subs:
                if el.tag == 'Material':
                    sm = SubMaterial(el)
                    m.subs.append(sm)
                    m.by_name[sm.name] = sm
        else:
            # single-material .mtl (terrain layers etc.): textures live
            # on the root element
            sm = SubMaterial(root)
            m.subs.append(sm)
            if sm.name:
                m.by_name[sm.name] = sm
        return m

    @classmethod
    def load(cls, path):
        with open(path, 'rb') as f:
            return cls.parse(f.read())


_global_idx = {}


def _scan_root(mesh_path):
    """Project scan root above a mesh path: the nearest ancestor holding
    project.json, else the dir itself."""
    d = os.path.dirname(os.path.abspath(mesh_path))
    for _ in range(10):
        if os.path.isfile(os.path.join(d, 'project.json')):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.abspath(mesh_path))


def _global_index(root):
    """sub-material name -> [(mtl_path, Mtl)] for every .mtl under the
    project root plus the extracted client material library at
    <project>/../arena_src/assets (kept outside the project so the AP
    does not schedule ~28k material source jobs)."""
    if root in _global_idx:
        return _global_idx[root]
    idx = {}
    roots = [root,
             os.path.normpath(os.path.join(root, '..', 'arena_src',
                                           'assets'))]
    for base in roots:
        if not os.path.isdir(base):
            continue
        for r, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in
                       ('Cache', 'user', '.git', 'build', 'engineassets')]
            for fn in files:
                if not fn.lower().endswith('.mtl'):
                    continue
                p = os.path.join(r, fn)
                try:
                    m = Mtl.load(p)
                except Exception:
                    continue
                for n in m.by_name:
                    idx.setdefault(sub_key(n), []).append((p, m))
    _global_idx[root] = idx
    return idx


_NOISY_SUB = re.compile(
    r'^(coll|collision|shadow|prox|phys|obstruct|nocollide|bend|nocam|_coll'
    r'|col\d|submtl|proxy|occl|geo$|mesh$|object$|default$)',
    re.IGNORECASE)


def sub_key(name):
    """Normalise a sub-material name for matching: lowercase, trailing
    digits stripped ('legion_ruins_wall_02_b1' == 'legion_ruins_wall_02_b',
    'leaves1' == 'Leaves')."""
    return re.sub(r'\d+$', '', (name or '').lower())


def sub_noisy(name):
    """Physics/editor helper subs — never drive material matching."""
    return not name or bool(_NOISY_SUB.match(name))


_slice_mtl_map_cache = {}


_PAK_TOP = ('objects/', 'materials/', 'textures/', 'libs/',
            'sharedassets/', 'engineassets/')


def _slice_mtl_map(mesh_path):
    """pak-relative cgf path -> per-entity .mtl assignment, read from
    cgf_mtl_map.json beside the extracted 'assets' tree (generated from
    the level's dynamicslice records). The slice states which material a
    placed mesh uses, which beats name-matching when several sibling
    .mtl files cover different sub-material sets (e.g. glowing_mat vs
    glowing_wleaves_mat)."""
    ap = os.path.abspath(mesh_path).replace(os.sep, '/')
    rel = None
    if '/assets/' in ap:
        arena_src = ap.split('/assets/')[0]
        rel = ap[ap.index('/assets/') + len('/assets/'):]
    else:
        # sources live under the project root; the pak-relative path
        # starts at a top-level asset dir (objects/...).
        arena_src = os.path.normpath(
            os.path.join(_scan_root(mesh_path), '..', 'arena_src'))
        for top in _PAK_TOP:
            i = ap.find('/' + top)
            if i >= 0:
                rel = ap[i + 1:]
                break
    if rel is None:
        return None
    if arena_src not in _slice_mtl_map_cache:
        p = os.path.join(arena_src, 'cgf_mtl_map.json')
        try:
            import json
            _slice_mtl_map_cache[arena_src] = json.load(open(p))
        except Exception:
            _slice_mtl_map_cache[arena_src] = {}
    hit = _slice_mtl_map_cache[arena_src].get(rel)
    if hit is None:
        # LOD cgfs (foo_lod1.cgf) are not placed entities; they inherit the
        # base cgf's per-entity material assignment.
        hit = _slice_mtl_map_cache[arena_src].get(
            re.sub(r'_lod\d+\.cgf$', '.cgf', rel))
    return hit


def find_mtl_for_mesh(mesh_path, mat_names):
    """Locate the .mtl that defines a mesh's sub-materials.

    mesh_path: path to the .cgf/.skin on disk.
    mat_names: iterable of sub-material names from the mesh's MtlName chunk.
    Returns (mtl_path, Mtl) or (None, None). Scans every .mtl beside the
    mesh file and picks the one covering the most requested names; if no
    local .mtl covers any name, falls back to a project-wide index (shared
    library materials like stonekit/generic live away from the meshes).
    """
    # match on normalised sub names (case + trailing digits folded);
    # '' and physics/editor helper subs are excluded — they only match
    # stray ''/'coll' subs in unrelated library materials (impostor
    # atlases etc.) and produce junk assignments.
    want = {sub_key(n) for n in mat_names if not sub_noisy(n)}

    # the level assigns a material file per placed entity; honour it
    # when it covers at least one of this mesh's sub-materials.
    assigned = _slice_mtl_map(mesh_path)
    if assigned:
        assets_root = os.path.normpath(os.path.join(
            _scan_root(mesh_path), '..', 'arena_src', 'assets'))
        mtl_path = os.path.join(assets_root, assigned)
        if os.path.isfile(mtl_path):
            try:
                m = Mtl.load(mtl_path)
                if want & {sub_key(sn) for sn in m.by_name}:
                    return mtl_path, m
            except Exception:
                pass

    def _score(m):
        return len(want & {sub_key(sn) for sn in m.by_name})

    mesh_stem = os.path.splitext(os.path.basename(mesh_path))[0].lower()

    def _prefix(a, b):
        i = 0
        while i < min(len(a), len(b)) and a[i] == b[i]:
            i += 1
        return i

    def _rank(path, m, local):
        mstem = os.path.splitext(os.path.basename(path))[0].lower()
        pref = _prefix(mstem, mesh_stem)
        for n in mat_names:
            pref = max(pref, _prefix(mstem, (n or '').lower()))
        # most sub hits, then same-dir mtl beats any global at equal
        # score, then closest name match, then shortest stem
        return (_score(m), int(local), pref, -len(mstem))

    best, best_rank, best_mtl = None, (0, 0, 0, 0), None
    d = os.path.dirname(mesh_path)
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not fn.lower().endswith('.mtl'):
            continue
        try:
            mtl = Mtl.load(os.path.join(d, fn))
        except Exception:
            continue
        p = os.path.join(d, fn)
        r = _rank(p, mtl, True)
        if r > best_rank:
            best, best_rank, best_mtl = p, r, mtl
    idx = _global_index(_scan_root(mesh_path))
    seen = set()
    for n in want:
        for p, mtl in idx.get(n, []):
            if p in seen:
                continue
            seen.add(p)
            r = _rank(p, mtl, False)
            if r > best_rank:
                best, best_rank, best_mtl = p, r, mtl
    if best_rank[0] == 0:
        # last resort for meshes whose subs are all '': same-dir mtl
        # whose stem shares the longest common prefix with the mesh stem.
        # 'legion_ruins_doorframe_01_c' -> 'legion_doorframe_01_c_mat'
        # style conventions drop filler tokens, so also try a relaxed
        # stem (ruins/lod/trailing variant letter removed).
        relaxed = re.sub(r'_lod\d+$', '', mesh_stem)
        relaxed = re.sub(r'_ruins_', '_', relaxed)
        stems = {mesh_stem, relaxed, re.sub(r'_[a-z]$', '', relaxed)}
        clen, cand = (0, 0), None
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not fn.lower().endswith('.mtl'):
                continue
            i = max(_prefix(fn[:-4].lower(), s) for s in stems)
            if (i, -len(fn)) > clen:
                clen, cand = (i, -len(fn)), os.path.join(d, fn)
        if clen[0] >= 8:
            try:
                best, best_mtl = cand, Mtl.load(cand)
            except Exception:
                pass
        else:
            return None, None
    return best, best_mtl


def resolve_texture(file_ref, mesh_dir):
    """Find a texture file on disk for an mtl File reference.

    file_ref is pak-relative ('objects/.../foo_diff.dds') and may name a
    .tif whose shipped form is .dds. Tries, in order: path relative to
    each ancestor of mesh_dir, basename under mesh_dir/textures, then the
    same candidates with the extension swapped to .dds.
    Returns an absolute path or None.
    """
    ref = file_ref.replace('\\', '/').lstrip('/')
    base = os.path.basename(ref)
    stem = os.path.splitext(base)[0]
    cands = []
    anc = mesh_dir
    for _ in range(8):
        cands.append(os.path.join(anc, ref))
        anc = os.path.dirname(anc)
        if not anc or anc == '/':
            break
    cands.append(os.path.join(mesh_dir, 'textures', base))
    cands.append(os.path.join(mesh_dir, base))
    more = []
    for c in cands:
        more.append(os.path.splitext(c)[0] + '.dds')
        more.append(os.path.join(os.path.dirname(c), stem + '.dds'))
    for c in cands + more:
        if os.path.isfile(c):
            return c
    # season/tier variants: the client swaps 'foo_diff.dds' and
    # 'foo_t00_summ01_diff.dds' for whatever season ships
    # ('foo_t00_fall01_diff.dds'). Normalise the _tNN_<season>NN token
    # out of the ref and of each candidate in the referenced directory.
    season = re.compile(r'_t\d+_(?:summ|fall|wint|spri|autu|spr)\d+',
                        re.IGNORECASE)
    loose = season.sub('_', stem)
    kind = loose.rsplit('_', 1)[-1] if '_' in loose else loose
    prefix = loose[:len(loose) - len(kind)]
    refdir = os.path.dirname(ref)
    for anc_n in range(8):
        anc = mesh_dir
        for _ in range(anc_n):
            anc = os.path.dirname(anc)
        d = os.path.join(anc, refdir) if refdir else anc
        if not os.path.isdir(d):
            continue
        hits = sorted(
            fn for fn in os.listdir(d)
            if fn.lower().endswith('.dds')
            and (season.sub('_', os.path.splitext(fn)[0]) == loose
                 or (fn.startswith(prefix) and kind in fn)))
        if hits:
            return os.path.join(d, hits[0])
    return None
