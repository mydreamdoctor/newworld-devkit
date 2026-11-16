#!/usr/bin/env python3
"""NW terrain.json: level-wide generator params. Height scale = mountainHeight/65535.
Known fields: generatorType, heightCrop, mountainRoughness, mountainHeight,
snowMinimumSlope, snowStartHeight, valleyIntensity, oceanLevel,
worldMaterialAssetPath. Unknown keys are preserved verbatim on save."""
import json


class TerrainJson(dict):
    SCALE_DENOM = 65535.0

    @property
    def height_scale(self):
        return self.get('mountainHeight', 2048.0) / self.SCALE_DENOM

    @property
    def ocean_level(self):
        return self.get('oceanLevel', 0.0)

    @property
    def world_material(self):
        return self.get('worldMaterialAssetPath', '')


def load(path):
    with open(path) as f:
        return TerrainJson(json.load(f))


def save(tj, path):
    with open(path, 'w') as f:
        json.dump(tj, f, indent=4, sort_keys=False)
