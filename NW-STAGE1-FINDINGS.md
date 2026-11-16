# Stage 1 findings: CryLegacy spike, .adb/.cgfheap deltas, v1 scope options

Working notes for `prj_147a0f93` steps 1.3 and 1.4. Sources are cited; Lumberyard
paths are read-only leads, never copied.

## 1.3 CryLegacy compile spike — verdict: wholesale port is infeasible

Test: transitive `#include` closure over all 542 `*.cpp` in
`/home/lachlan/development/lumberyard/dev/Gems/CryLegacy/Code` (waf-built, no CMake),
resolved against three header universes: the gem itself, this O3DE tree, and the
Lumberyard tree (`dev/Code`).

Result:

- **0 / 542 translation units resolve against O3DE + the gem alone.** Every TU pulls
  Lumberyard-only headers transitively (all via `CryLegacy_precompiled.h`).
- **325 unique Lumberyard-only headers required** — the CryEngine interface layer that
  O3DE's CryCommon cull removed. O3DE ships ~80 CryCommon headers (math, ISystem,
  IRenderer, ISerialize, IXml); Lumberyard ships ~587.
- **227 unresolved-everywhere includes** are platform-conditionals (`Xenia/`,
  `Provo/`, `Salem/` console `.inl` files, `sys/socket.h`, `new.h`) — dead on Linux,
  not real blockers.

Heaviest missing interfaces (inclusion count across the closure):

| Header | refs | What it is | O3DE candidate |
|---|---|---|---|
| IAgent.h / IAISystem.h / IAIObject*.h / IAIActor.h / IAIGroup.h / INavigationSystem.h / IPathfinder.h / ICover.h (implied) | ~19k | CryAISystem interface layer | No O3DE AI system; RecastNavigation gem covers navmesh only. Out of scope for a content dev kit |
| IEntitySystem.h / IEntity.h / IEntityPoolManager.h / Components/IComponent*.h | ~4k | Cry entity/component model | `AZ::Entity` + `AZ::Component` (AzCore) — different component model entirely |
| IGameFramework.h / ICryAction.h / IGameRulesSystem.h / IGameObject.h / IActorSystem.h | ~4k | CryAction game framework | `AzFramework::Application`, `GameState` gem |
| ICryAnimation.h / IAnimation.h | ~3k | CryAnimation interfaces | EMotionFX gem (`EMotionFX` actors/motions) or a standalone NW format loader |
| IPhysics.h / RayCastQueue.h | ~2.3k | CryPhysics interfaces | PhysX5 gem (`AzPhysics`) |
| I3DEngine.h / IRenderAuxGeom.h / IViewSystem.h / IVisionMap.h | ~3k | Cry3DEngine + view/vision | Atom RPI; `AuxGeomFeatureProcessor` for debug draws |
| ICryPak.h / IStreamEngine.h | ~2k | Cry pak/VFS | `AZ::IO::Archive`, `AZ::IO::VirtualFileSystem` |
| ICryMannequin.h | ~600 | Mannequin animation DB | EMotionFX `AnimGraph` (state machines); .adb is XML (see §1.4) |
| Serialization/*, CryArray.h, STLPoolAllocator.h, FixedPoint.h, CGFContent.h, NameCRCHelper.h, IScriptSystem.h, ITimer.h, ISerialize helpers | — | Support substrate | `AZStd` containers, `AZ::SerializeContext`, `AZ::ITime`, `AZ::ScriptSystem` |

Error classification (per the step's taxonomy): overwhelmingly **removed API**
(deleted subsystems), not renamed API. Semantic drift exists too in headers O3DE
kept (e.g. `ISystem`, `IRenderer`, `Cry_Math` are AZ-ified), but it is irrelevant
while the interface layer is absent.

**Recommendation: do not port the gem.** Use CryLegacy as a semantic reference and
extract only the loaders the dev kit needs (`.caf`/`.skin` via `LoaderTCB.cpp`,
`.adb` via `AnimationDatabase*.cpp`, CGF via `CGF/CGFLoader.cpp` semantics) into
O3DE components that feed EMotionFX/Atom assets — the route already named in step
4.3. The formats are simple enough (XML, chunk table + flat heap) that the loaders
need math/serialization primitives, not the Cry engine.

## 1.4 Format deltas

### .adb — same schema, extended vocabulary (delta is bounded)

- NW `.adb` files are **plain XML** in the stock Mannequin container:
  `<AnimDB FragDef="…" TagDef="…">` with `<SubADBs>`, `<FragmentList>`,
  `<Fragment>` (`Tags`, `BlendOutDuration`), `<AnimLayer>`/`<Blend>`/`<Animation name=…>`,
  `<ProcLayer>`/`<Procedural>`/`<ProceduralParams>`, plus tag/fragment definition
  sections (`<Condition>`, `<Input>`, `<Element>`, `<Name>`). 31 files in the dump,
  ~16 MB total (player.adb 3.0 MB).
- Lumberyard's `CAnimationDatabase`/Mannequin XML reader loads this container
  unchanged.
- **Delta = procedural-clip vocabulary.** NW uses ~30 proprietary `Type="…Context"`
  clip classes (Damage, HitStun, Grit, CastSpell, SpawnSlice, PayStamina/Mana,
  Homing, Invulnerability, CritWindow, DisableCollision, DisableStaminaRegen,
  CharacterEvent, ParticleEffect, MaterialOverride, Transition, WeaponEffects,
  RangedAttack, RunFxScript, SetAnimByTag, Audio/CAudioPreload/CShakeCamera,
  HandToWeaponIK_, ConsumeLoadedAmmo, AttackHeightRetargeting, AI* targeting
  family, NamedContext, UsePaperdollItem). CryLegacy's `CProceduralClipFactory`
  registers ~12 stock types (AimPose, LookPose, ParticleEffect, PlaySound, Event,
  AnimManipulation, Positioning, ForceFeedback, AISignal, Props, LookAround,
  AimAround) — NW types will fail `CreateProceduralClip` unless implemented/stubbed.
- Consequence: the **schema parses as-is**; fragments load but their proc layers
  drop NW-specific clips. Full fidelity needs the ~30 `*Context` clip classes
  re-implemented (they carry gameplay semantics — SlayerScript's domain) or
  deliberately stubbed for the dev-kit editor.

### .cgf/.cgfheap — evolved 0x746 container + external heap (parser lift is partial)

- `.cgf` signature `CrChF` (5 bytes), version 7, 16-byte header
  (`sig[5] ver? count@8 tableOff@12`), then a 0x746-compatible chunk table:
  16-byte entries `<u16 type, u16 ver, u32 id, u32 size, u32 offset>` — same layout
  as Lumberyard `ChunkFile::ChunkTableEntry_0x746`
  (Cry3DEngine/CGF/ChunkFileComponents.h:157).
- Chunk types observed in a sample: 0x1000 Mesh, 0x100b Node (object id @+64,
  16-float matrix @+84), 0x1014 MtlName, 0x1015 ExportFlags, 0x1017 MeshSubsets,
  0x300b **heap-stream descriptor** (5 u32: kind, offset, size, stride — offsets
  resolve into the sibling `.cgfheap` file, not the .cgf). 0x300b is beyond
  Lumberyard's `ChunkTypes` enum (CryHeaders.h:32, ends 0x3009) — it is the
  NW-specific cooked-geometry indirection.
- `.cgfheap` is a flat blob (no header): stream kind 0 = index buffer (u16/u32),
  kind 1 = positions (f32 stride ≥12, or half-float stride 16/8). Mesh chunks carry
  a 64-u32 header (`[2]`=nVerts, `[3]`=nIndices, `[4..63]`=referenced stream
  descriptor chunk ids). Working parser: Lockstep `tools/arena_floor_bake.py:399-489`
  (`read_cgf`), exercised on the arena bake; `tools/cgf_physproxy.py` for physics
  proxies.
- Consequence: Lumberyard's `CGFLoader.cpp`/`ChunkFileReaders` can be used as a
  **structural reference** (node/mesh/subset semantics) but cannot read NW files
  unchanged — different signature/version, external heap, and a new chunk type.
  The delta vs stock CGF is small at the container level; the stream-descriptor
  + heap split is the real work (streaming-optimized packaging Amazon added).

### v1 scope options (owner decision — see step 1.4)

- **A. Place/edit existing** (presumed minimum): load region root slices + assets,
  move/duplicate/delete entities, edit named component fields, write back.
  Needs: stage 2 codec+stubs, stage 3 terrain/streaming, stage 4 mesh preview.
  Animation/materials read-only.
- **B. A + visual fidelity**: add material/mesh conversion (4.1, 4.2) so scenes
  render recognizably; animation still read-only (.caf preview optional).
- **C. A + authored content**: allow creating new slices/entities (new IDs, new
  components from the schema dump), not just editing shipped ones. Larger editor
  surface (palette, serialization defaults, client acceptance of new IDs).
- **D. B + animation authoring**: add .adb/Mannequin editing incl. the ~30 NW
  proc-clip classes. Largest; depends on CryLegacy extraction outcome.
