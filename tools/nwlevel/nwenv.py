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
