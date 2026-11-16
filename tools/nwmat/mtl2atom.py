"""NW sub-material -> O3DE Atom .material JSON.

Maps Cry RenderDll material fields onto Atom's StandardPBR material
type. Target is a usable preview, not fidelity:

    Diffuse  color+map  -> baseColor.color / baseColor.textureMap
    Bumpmap  (DDNA)     -> normal.textureMap   (channel layout is an
                          approximation; DDNA packs normal+smoothness)
    Specular map        -> specularF0.textureMap
    Shininess           -> roughness.factor (1 - s/255, clamped)
    Opacity             -> opacity.factor
    AlphaTest > 0       -> opacity.mode 'Cutout'
    Emittance           -> emissive.color (+enable)
    everything else     -> reported in `unmapped` for logging

`tex_rel` maps an mtl Map name to a project-relative texture path
(for textureMap values); callers resolve files with mtl.resolve_texture.
"""
import os

MATERIAL_TYPE = 'Materials/Types/StandardPBR.materialtype'

# Map names we know how to place on StandardPBR.
_HANDLED_MAPS = {'Diffuse', 'Bumpmap', 'Specular', 'Smoothness', 'Emissive',
                 'Opacity', 'Decal'}


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def to_atom(sub, tex_rel):
    """sub: mtl.SubMaterial. tex_rel: {Map: project-relative path}.

    Returns (material_dict, unmapped)."""
    unmapped = []
    props = {}

    if sub.diffuse is not None:
        props['baseColor'] = {'color': [_clamp(c) for c in sub.diffuse]}
    if 'Diffuse' in tex_rel:
        props.setdefault('baseColor', {})['textureMap'] = tex_rel['Diffuse']

    if 'Bumpmap' in tex_rel:
        props['normal'] = {'textureMap': tex_rel['Bumpmap'],
                           'useTexture': True}

    if 'Specular' in tex_rel:
        props['specularF0'] = {'textureMap': tex_rel['Specular'],
                               'useTexture': True}

    shin = sub.shininess or 0.0
    rough = _clamp(1.0 - shin / 255.0, 0.05, 1.0)
    props['roughness'] = {'factor': round(rough, 4)}

    op = {}
    if sub.opacity is not None and sub.opacity < 1.0:
        op['factor'] = _clamp(sub.opacity)
        op['mode'] = 'Blended'
    if sub.alpha_test and sub.alpha_test > 0:
        op['mode'] = 'Cutout'
        op['alphaAffectsSpecular'] = True
    if op:
        props['opacity'] = op

    if sub.emittance and any(c > 0 for c in sub.emittance[:3]):
        props['emissive'] = {'enable': True,
                             'color': [_clamp(c) for c in sub.emittance[:3]]}

    for m in sub.textures:
        if m not in _HANDLED_MAPS:
            unmapped.append('texture slot %s=%s' % (m, sub.textures[m]))
    if sub.shader and sub.shader != 'Illum':
        unmapped.append('shader %s -> StandardPBR' % sub.shader)
    for k in sub.public_params:
        unmapped.append('publicParam %s=%s' % (k, sub.public_params[k]))
    if sub.surface_type and sub.surface_type not in ('', 'mat_default'):
        unmapped.append('surfaceType %s' % sub.surface_type)

    mat = {
        'description': 'NW material %s (shader %s)' % (sub.name, sub.shader),
        'materialType': MATERIAL_TYPE,
        'parentMaterial': '',
        'materialTypeVersion': 5,
        'properties': props,
    }
    if unmapped:
        mat['description'] += '; unmapped: ' + '; '.join(unmapped)
    return mat, unmapped


def project_rel(path, scan_root):
    """Absolute texture path -> path relative to a scan folder root."""
    try:
        rel = os.path.relpath(path, scan_root)
    except ValueError:
        return path
    return rel.replace(os.sep, '/')
