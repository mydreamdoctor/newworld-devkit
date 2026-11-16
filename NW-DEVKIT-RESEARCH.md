# New World dev kit on O3DE — research notes

> Compiled 2026-11-16 from a read-only investigation of the Lockstep project
> (`/mnt/dev_scratch/newworld`), this O3DE 2.8.0 source tree, and the local
> Lumberyard source (`/home/lachlan/development/lumberyard`). No changes were
> made to any project during the research.

## Goal

A dev kit letting users visually create New World content (map extensions, new
dungeons) with Unreal-Editor-like simplicity. The owner does **not** want an
import/export workflow — NW formats should be native to the tool. O3DE is the
candidate base because it descends from Lumberyard, New World's engine ancestor.
The local Lumberyard source may reduce effort.

## Prior art already in the repo

`docs/discussions/lumberyard-editor.md` (2026-10-17) assessed this before:

- Data edits (datasheets, Lua) are realistic; a full world editor is a large
  project; Lumberyard source is mainly a format reference.
- Key enabler identified: the client exe registers every component with
  SerializeContext → export schema → stub components → editor can load/save
  NW slices.
- Recommended a dedicated slice editor over the Lumberyard editor stack.
- Noted O3DE diverged further and removed CryPhysics/CryAnimation.
- Legal caveat: Amazon IP — private-server edits vs. distributing modified
  assets are different questions.

## What the Lockstep project already has (the foundation is strong)

All paths under `/mnt/dev_scratch/newworld`:

- **Slice codec (read side):** `tools/btdecode/btdecode.py` — full decoder for
  New World's binary AZ ObjectStream v3 (`.dynamicslice`, `.behaviortree`).
  `tools/xlate/player_slice_character_component.py` walks entities/elements and
  resolves field names; `scripts/decode_player_slice.py` is the earlier walk.
- **Component schema:** `tools/ghidra/index_mcp/az_serialize_names.json` —
  **4,362 classes / 11,716 fields** dumped from the client exe's
  SerializeContext registrations, plus `data_objects` (6,650) and
  `class_fields`. `tools/btdecode/uuid_names.json` (77 entries) and
  `crc_names.json` map type/field IDs to names.
- **Asset catalog:** `tools/assets/asset_catalog.py`; client manifest
  `data/clientdump/MANIFEST.json` (5,361 files indexed, partial extraction).
- **World formats mapped by the physics project:**
  - Terrain: `region.heightmap` is a **TIFF**; `terrain.json` holds generator
    params (Heightmap generator, mountainHeight 2048, oceanLevel 40,
    worldMaterialAssetPath). Terrain tiles are 160 m wide on a 128 m stride.
  - World streaming: **Coatlicue** streams regions `r_+XX_+YY`; region
    "capital" entries are root slices (`docs/discussions/physics-4.37-*`).
  - Water/rivers: spline-based `.dynamicslice` files
    (`slices/terrain_water/...`), bit-exact rebuild already achieved by
    `tools/physics/check_water.py`.
  - Collision bodies come from slices + `.rnr` files; `tools/level_bake.py`,
    `arena_floor_bake.py`, `tools/physics/level_colliders.py` already produce
    what the Go server consumes.
- **Server paks:** `data/serverpak/assets/` has official server DataStrm
  parts + `Server.pak` (9.9 GB local); depot manifest
  `manifest_1063731_3129454692625577733.txt` (196 files, ~80 GB depot).
- **Animation RE:** `tools/caf_pose_export.py`, `caf_rootmotion_export.py`,
  `tools/anim_db/`, playbook docs on `.adb`/`.caf` formats.

## O3DE inventory (this tree, v2.8.0)

- Editor: `Code/Editor` (Qt-based CryEdit descendant), Asset Processor in
  `Code/Tools/AssetProcessor`.
- Relevant gems: `Prefab` (Slice/Prefab = ObjectStream lineage), `Terrain`,
  `Vegetation`, `PhysX`, `EMotionFX`, `ScriptCanvas`, `LyShine`, `Multiplayer`,
  `LandscapeCanvas`, `WhiteBox`, `SceneProcessing`.
- **O3DE removed the CryEngine legacy** (`Code/CryEngine` is absent) — the
  asset readers for CGF/legacy animation/CryPhysics are gone.
- `.slice` files here are XML `<ObjectStream version="3">`; `.dynamicslice` is
  the cooked binary — same container family as NW's cooked slices.
- Reference clone: `data/o3de-ref` in the repo = shallow clone of
  github.com/o3de/o3de @ 74006f5.

## Lumberyard inventory (`/home/lachlan/development/lumberyard/dev`)

The full pre-O3DE tree, including what O3DE deleted:

- `Code/CryEngine/`: **Cry3DEngine, CryPhysics, CrySystem, RenderDll,
  CryNetwork, CryCommon** — the legacy engine intact.
- `Code/CryEngine/Cry3DEngine/CGF/CGFLoader.cpp` + `CGFSaver.cpp`,
  `CryCommon/CGFContent.*` — CGF mesh format readers/writers.
- **`Gems/CryLegacy/`** — a self-contained gem holding `CryAnimation/*`
  (LoaderTCB, DynamicController, Command_Buffer) and
  `CryAction/Mannequin/AnimationDatabase*.cpp` — the Mannequin/.adb lineage.
- `Gems/CryLegacyAnimation/` — asset-processor side of legacy animation.
- `Gems/EMotionFX/`, `LmbrCentral` Mannequin components, Sandbox Mannequin
  editor (`Code/Sandbox/Editor/Mannequin/`).
- Same gem.json/AzCore structure as O3DE → porting surface is API drift, not
  architecture.

## Analysis: O3DE base + Lumberyard grafts, native NW support

"Native" = the editor's save format IS the NW asset/pak; users never see
import/export. Achieved via Asset Processor plugins that recognize NW
extensions and build O3DE runtime assets automatically.

| NW format | Source of truth | Approach |
|---|---|---|
| `.dynamicslice`/`.slice` | `btdecode` + schema dump | Write-side serializer + stub components from 4,362-class schema; no port needed |
| `.cgf`/`.cgfheap`/`.skin` | `CGFLoader.cpp`, `CGFContent` | Lift parser into an AP builder → O3DE mesh assets |
| `.caf`/`.anims`/`.adb` | `Gems/CryLegacy` (CryAnimation + Mannequin) | Port CryLegacy gem into O3DE or extract loaders; `.adb` is Amazon-modified → residual RE |
| Physics `.rnr`/collision | CryPhysics headers (not portable wholesale) | Shape serialization only; Go physics project is authoritative spec |
| Materials/shaders | RenderDll material system | Convert to Atom materials via AP builder |
| Terrain/vegetation/UI | O3DE gems already cover | Add NW-format layers (TIFF heightmap + terrain.json; foliage/water slices) |
| Coatlicue streaming, Javelin components | — | Custom gem; component stubs from schema |

### Effort ranking

- **Cheap:** slice write-side codec + round-trip test, schema stubs, terrain
  params/heightmap import.
- **Medium:** CGF AP builder, material conversion, foliage/water slice
  editing — independent bounded jobs.
- **Hard:** CryLegacy port under O3DE (API drift unknown until attempted),
  `.adb` residual gaps, collision authoring, pak packaging.
- **Not needed:** porting CryPhysics or the CryEngine renderer.

### First de-risking spike

**Does `Gems/CryLegacy` compile under O3DE?** Highest-value, highest-uncertainty
item. If it builds with modest fixes, animation support collapses from "format
RE project" to "integration work."

## Open questions

1. Does the local Lumberyard tree still build on a modern toolchain? (Phase-0
   spike if Lumberyard-base is ever reconsidered.)
2. How much of `.adb` does CryLegacy's Mannequin code cover vs. Amazon's
   modifications?
3. `.cgfheap` — NW-modified CGF variant; how large is the delta from stock
   CGFLoader?
4. Legal posture on distributing modified Amazon assets.
5. Scope: is authoring brand-new meshes/anims in-engine required, or is
   placing/editing existing NW assets enough for v1?
