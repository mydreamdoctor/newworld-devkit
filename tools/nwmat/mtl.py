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
                    idx.setdefault(n, []).append((p, m))
    _global_idx[root] = idx
    return idx


def find_mtl_for_mesh(mesh_path, mat_names):
    """Locate the .mtl that defines a mesh's sub-materials.

    mesh_path: path to the .cgf/.skin on disk.
    mat_names: iterable of sub-material names from the mesh's MtlName chunk.
    Returns (mtl_path, Mtl) or (None, None). Scans every .mtl beside the
    mesh file and picks the one covering the most requested names; if no
    local .mtl covers any name, falls back to a project-wide index (shared
    library materials like stonekit/generic live away from the meshes).
    """
    want = set(mat_names)
    best, best_hits, best_mtl = None, 0, None
    d = os.path.dirname(mesh_path)
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not fn.lower().endswith('.mtl'):
            continue
        try:
            mtl = Mtl.load(os.path.join(d, fn))
        except Exception:
            continue
        hits = len(want & set(mtl.by_name))
        if hits > best_hits:
            best, best_hits, best_mtl = os.path.join(d, fn), hits, mtl
    if best_hits == 0:
        idx = _global_index(_scan_root(mesh_path))
        for n in want:
            for p, mtl in idx.get(n, []):
                hits = len(want & set(mtl.by_name))
                if hits > best_hits:
                    best, best_hits, best_mtl = p, hits, mtl
    if best_hits == 0:
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
    return None
