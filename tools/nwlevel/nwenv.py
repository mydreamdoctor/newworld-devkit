"""New World level environment import.

CryEngine levels store their environment settings in
``mission_mission0.xml`` inside ``level.pak``:

    <Environment>
      <Fog ViewDistance="14336" .../>
      <SkyBox Material="EngineAssets/Materials/Sky/Sky" .../>
      <Lighting SunRotation="170" SunHeight="80" ShadowIntensity="100"
                SunVector="0.10418899,-0.59088469,-0.79999995"/>
    </Environment>

This module parses that block and converts it to the values our level
builder needs (sun rotation/colour/intensity, fog distance), so every
imported level is lit from the game's own data instead of guessed
defaults.
"""

import math
import os
import sys
import zipfile
import xml.etree.ElementTree as ET


DEFAULT_SUN_INTENSITY = 2.5
DEFAULT_SUN_COLOR = (1.0, 0.96, 0.88)


def _floats(s):
    return tuple(float(x) for x in s.split(','))


def sun_rotation_from_vector(v):
    """CryEngine SunVector (light travel direction) -> O3DE euler.

    O3DE yaw 0 points +Y, yaw 90 points +X; pitch is negative looking
    down. The light points along its forward (-Z) axis, so the euler is
    derived straight from the travel direction."""
    x, y, z = v
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    x, y, z = x / n, y / n, z / n
    yaw = math.degrees(math.atan2(x, y))
    pitch = -math.degrees(math.asin(max(-1.0, min(1.0, -z))))
    return (round(pitch, 2), 0.0, round(yaw, 2))


def parse_environment_xml(xml_bytes):
    """Extract the <Environment> block into a plain dict."""
    root = ET.fromstring(xml_bytes)
    env = root if root.tag == 'Environment' else root.find('.//Environment')
    if env is None:
        return {}
    out = {}
    light = env.find('Lighting')
    if light is not None:
        if light.get('SunVector'):
            out['sun_vector'] = _floats(light.get('SunVector'))
        for k in ('SunRotation', 'SunHeight', 'ShadowIntensity'):
            if light.get(k) is not None:
                out[k.lower()] = float(light.get(k))
    fog = env.find('Fog')
    if fog is not None:
        if fog.get('ViewDistance'):
            out['fog_view_distance'] = float(fog.get('ViewDistance'))
        if fog.get('LDRGlobalDensMult'):
            out['fog_density_mult'] = float(fog.get('LDRGlobalDensMult'))
    sky = env.find('SkyBox')
    if sky is not None and sky.get('Material'):
        out['sky_material'] = sky.get('Material')
    return out


def read_level_environment(level_pak):
    """Parse a level.pak's environment block; {} when absent."""
    try:
        with zipfile.ZipFile(level_pak) as z:
            name = next((n for n in z.namelist()
                         if n.lower() == 'mission_mission0.xml'), None)
            if name is None:
                return {}
            return parse_environment_xml(z.read(name))
    except (OSError, zipfile.BadZipFile, ET.ParseError):
        return {}


def find_level_pak(level_dir, level_name=None):
    """Locate a level.pak for a level dir/name.

    Checks the level dir itself, then a sibling directory named after
    the game level, then common client asset roots."""
    cands = [os.path.join(level_dir, 'level.pak')]
    base = level_name or os.path.basename(level_dir.rstrip('/'))
    if base:
        parent = os.path.dirname(level_dir.rstrip('/'))
        cands.append(os.path.join(parent, base, 'level.pak'))
        for root in ('/home/lachlan/nwclient-frozen-20261022/assets/levels',
                     '/home/lachlan/nwclient-c2/assets/levels'):
            cands.append(os.path.join(root, base, 'level.pak'))
    return next((p for p in cands if os.path.isfile(p)), None)


CLIENT_ASSET_ROOTS = ('/home/lachlan/nwclient-frozen-20261022/assets',
                      '/home/lachlan/nwclient-c2/assets')

# Fog variables in a CryEngine time-of-day file. NW's fog is a height
# layer: a density at the bottom height and another at the top height,
# plus a colour at each. The <Fog ViewDistance> in mission_mission0.xml
# is a culling distance, not the visual fog.
TOD_FOG_VARS = {
    'fog_color': 'Fog color',
    'fog_color_top': 'Fog color (top)',
    'fog_height_bottom': 'Fog height (bottom)',
    'fog_height_top': 'Fog height (top)',
    'fog_density_bottom': 'Fog layer density (bottom)',
    'fog_density_top': 'Fog layer density (top)',
    'vol_density': 'Volumetric fog: Global density',
    'vol_ramp_start': 'Volumetric fog: Ramp start',
    'vol_ramp_end': 'Volumetric fog: Ramp end',
    'vol2_height_bottom': 'Volumetric fog 2: Fog height (bottom)',
    'vol2_height_top': 'Volumetric fog 2: Fog height (top)',
    'vol2_density_bottom': 'Volumetric fog 2: Fog layer density (bottom)',
    'vol2_density_top': 'Volumetric fog 2: Fog layer density (top)',
    'vol2_ramp_start': 'Volumetric fog 2: Ramp start',
    'vol2_ramp_end': 'Volumetric fog 2: Ramp end',
    'vol2_albedo': 'Volumetric fog 2: Fog albedo color (atmosphere)',
}


def _find_pak_entry(entry, roots=None):
    """(pak path, bytes) for the first pak that carries `entry`."""
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'nwpak'))
    import nwpak
    for root in (roots or CLIENT_ASSET_ROOTS):
        if not os.path.isdir(root):
            continue
        for pak in sorted(os.listdir(root)):
            if not pak.lower().endswith('.pak'):
                continue
            path = os.path.join(root, pak)
            try:
                return path, nwpak._read_entry(path, entry)
            except (KeyError, OSError, zipfile.BadZipFile, RuntimeError):
                continue
    return None, None


def read_timeofday(level_name, roots=None):
    """Fog settings from the level's own time-of-day file.

    NW names it in the level's resourcelist as
    ``libs/timeofday/modes/<level>.xml``; the file lives in GameData.pak.
    Each ``<Variable>`` carries the value already evaluated at the level's
    ``Time``, so no spline evaluation is needed.
    """
    entry = 'libs/timeofday/modes/%s.xml' % level_name
    _pak, data = _find_pak_entry(entry, roots)
    if not data:
        return {}
    try:
        root = ET.fromstring(data.decode('utf8', 'replace'))
    except ET.ParseError:
        return {}
    out = {'time': root.get('Time')}
    for key, name in TOD_FOG_VARS.items():
        for v in root.iter('Variable'):
            if v.get('Name') != name:
                continue
            raw = v.get('Color') or v.get('Value')
            if raw is None:
                continue
            try:
                out[key] = (_floats(raw) if ',' in raw else float(raw))
            except ValueError:
                pass
            break
    return out


def fog_config(tod):
    """NW time-of-day fog -> the values our level's fog entity carries.

    The primary layer is NW's ``Fog`` height layer; O3DE's deferred fog is
    the same shape (a slab between two world heights with a density), so
    the game's own numbers go straight through.
    """
    if not tod:
        return {}
    out = {}
    if 'fog_height_bottom' in tod and 'fog_height_top' in tod:
        out['fog_min_height'] = tod['fog_height_bottom']
        out['fog_max_height'] = tod['fog_height_top']
    if 'fog_color' in tod:
        out['fog_color'] = tod['fog_color']
    if 'fog_density_bottom' in tod:
        out['fog_density'] = tod['fog_density_bottom']
    for key in ('vol2_albedo', 'vol2_height_bottom', 'vol2_height_top',
                'vol_ramp_start', 'vol_ramp_end', 'time'):
        if key in tod:
            out[key] = tod[key]
    return out


def lighting_config(env, sun_color=DEFAULT_SUN_COLOR,
                    sun_intensity=DEFAULT_SUN_INTENSITY):
    """Environment dict -> (sun_rotation, sun_color, sun_intensity, fog)."""
    rot = (-55.0, 0.0, 25.0)
    if env.get('sun_vector'):
        rot = sun_rotation_from_vector(env['sun_vector'])
    return {
        'sun_rotation': rot,
        'sun_color': tuple(sun_color),
        'sun_intensity': sun_intensity,
        'fog_view_distance': env.get('fog_view_distance'),
        'sky_material': env.get('sky_material'),
    }
