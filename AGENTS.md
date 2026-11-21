# Rules for this repo (NW dev kit on O3DE)

- 🔴 **Store ALL facts in graphiti.** Every fact learned about this repo, the NW
  formats, the client, the build, or the project's decisions MUST be persisted to
  the graphiti MCP server (`mcp__graphiti__add_memory`) with
  `group_id: "newworld-devkit"`. Do not keep findings only in chat, plan logs or
  docs — if it is worth remembering, it goes into the graph.
- 🔴 **Query graphiti first.** Before answering questions about this repo or
  starting a step, search the store: `search_nodes` / `search_memory_facts` with
  `group_ids: "newworld-devkit"`.
- Repo boundary: change files only inside this repo; writes outside need owner
  permission. Lumberyard/CryEngine sources are leads-only (cite file:line,
  never copy).
- 🟢 **Standing owner grants** (do not re-ask): the owner has pre-authorized
  (a) reads+writes+deletes under `/tmp`, (b) launching the local O3DE
  `Editor`/`AssetProcessor*` binaries from `build/linux/bin`, (c) committing
  and pushing this repo to `development` after each plan step. These are
  standing permissions, not one-time approvals.
- Build/test layout: everything under `build/` (gitignored). Verified recipe and
  stage-1 findings are in the graphiti store and in `NW-STAGE1-FINDINGS.md`.
- 🔴 **Check free RAM before launching the Editor or AssetProcessor.** This host
  is shared with other heavy work and the machine has OOM-crashed once already.
  Run `free -g` first; if free+cache is under ~24 GiB, do not launch — tell the
  owner instead. One editor + one AP at a time; kill stragglers (`pgrep -af
  'profile/(Editor|AssetProcessor)'`) before a new run.
- Plan of record: project-mcp `prj_147a0f93` (dashboard http://127.0.0.1:8090).
- **Headless editor runs.** Do NOT run the Editor on the owner's desktop
  (`DISPLAY=:0`) — it steals focus and screenshots disturb the session. Run it
  on a private gamescope display instead (method from the Lockstep overseer's
  tutorial `/tmp/claude-1000/.../background-client-tutorial.md`):
  `env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS
  XDG_RUNTIME_DIR=$RUN setsid gamescope --backend headless -W 1920 -H 1080 -w
  1920 -h 1080 --force-windows-fullscreen -- $RUN/holder.sh` where holder.sh
  records `$DISPLAY` into `$RUN/display` and sleeps forever; then launch the
  Editor with `env -u WAYLAND_DISPLAY -u XAUTHORITY DISPLAY=$D
  XDG_RUNTIME_DIR=$RUN setsid ./build/linux/bin/profile/Editor ...`. Input:
  `DISPLAY=$D xdotool windowactivate --sync <win>` then `xdotool key/click`
  WITHOUT `--window` (XTEST; `--window` sends XSendEvent which engines ignore).
  Screenshots: `DISPLAY=$D import -window <winid> out.png` per-window works;
  the Xwayland ROOT window stays BLACK under headless gamescope (x11grab/
  import -window root both fail to show content). The editor may open at a
  small size — `xdotool windowsize <win> 1920 1080` fixes it. Clean up:
  `xdotool windowclose`, SIGTERM the editor, kill gamescope, rm -rf $RUN.
- **Edit-mode blank-viewport bug (FIXED 2026-11-17).** The editor opened a
  level showing only sky/HDRI+icons+auxgeom — no meshes or terrain — until a
  game-mode round trip. Root cause: `Scene::RebuildPipelineStatesLookup`
  runs while parts of the pass tree are not yet attached, so early
  `m_pipelineStatesLookup` lookups lack `forward`/`depth`/`shadow`;
  `MeshDrawPacket::DoUpdate` and `TerrainMeshManager::RebuildDrawPackets`
  silently drop draw items for missing tags and never retry (upstream O3DE
  defect, worth filing). Fix: `OnPipelineStateLookupRebuilt` handlers in
  `MeshFeatureProcessor` (sets `m_forceRebuildDrawPackets`) and
  `TerrainFeatureProcessor` (calls `m_meshManager.SetRebuildDrawPackets()`),
  plus temporary `NWDBG` logging in `Scene.cpp`. Validated: nw_arena renders
  terrain+meshes in edit mode with no round trip.
  `build/nw_open_arena.py` automates: open level → wait → enter game mode →
  exit → set camera → capture. Also: `set_current_view_position` is applied
  to the async level load — set the camera only after the level finishes or
  the level's saved view overwrites it.
- 🟢 **Run the Editor/GameLauncher in the background on a private headless
  display, never on the owner's desktop.** Recipe (from the Lockstep
  overseer's `background-client-tutorial.md`):
  ```bash
  RUN=/run/user/$UID/devkit1           # short path, mode 700
  mkdir -p -m 700 "$RUN"
  printf '#!/bin/bash\necho "$DISPLAY" >"%s/display"\nexec sleep infinity\n' "$RUN" >"$RUN/holder.sh"
  chmod 700 "$RUN/holder.sh"
  env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS \
    XDG_RUNTIME_DIR="$RUN" setsid gamescope --backend headless \
    -W 1920 -H 1080 -w 1920 -h 1080 --force-windows-fullscreen \
    -- "$RUN/holder.sh" >"$RUN/gamescope.log" 2>&1 </dev/null &
  echo $! >"$RUN/gamescope.pid"
  # wait for $RUN/display to appear, then D=$(cat $RUN/display)
  env -u WAYLAND_DISPLAY -u XAUTHORITY DISPLAY=$D XDG_RUNTIME_DIR="$RUN" \
    setsid ./Editor --regset="...project_path..." --skipWelcomeScreenDialog \
    --runpython /abs/path/script.py >"$RUN/editor.log" 2>&1 </dev/null &
  echo $! >"$RUN/editor.pid"
  ```
  Editor startup scripting: `--runpython file.py` (positional `.py` arg +
  flag; `--runpythonargs` for args), or `--exec_line "pyRunFile /path"`.
  Screenshot the private display with `DISPLAY=$D import -window root out.png`;
  drive input with `DISPLAY=$D xdotool` (XTEST, no `--window` on key/click).
  A long-lived display at `/run/user/1000/devkit1` (DISPLAY `:2`) may already
  exist — reuse it. Always kill Editor + gamescope when done.

- 🔴 **THE KIT IS A ROUND TRIP, NOT A VIEWER (owner, 2026-11-21).** Users
  import New World assets, edit them in the editor, and export them back to
  New World. That second half is as critical as the first, so **the pipeline
  must not invent, move or reinterpret anything on the way through**: no
  synthetic entities, no repositioned terrain, no re-derived transforms, no
  "make it look right" content. If the editor shows it, it can be written
  back, and a fabricated value becomes a broken game asset. When the game
  has something we cannot yet import, the honest answer is a named gap and
  a decoder for the real data — never a stand-in.
  Concretely: `tools/nwslice/prefab2slice.py` (the save path) re-parses the
  ORIGINAL .dynamicslice and patches only GameTransformComponent m_worldTM
  and SplineComponent vertices; prefab entities that match no slice entity
  are reported and left untouched, and slice entities the prefab dropped are
  reported, not deleted. It never adds entities. So an O3DE-only entity
  (sun, sky, fog, camera) is harmless to the export — but any *transform*
  difference in the view is written back, which is why positions must never
  be nudged for looks.
- **Ground-cover vegetation (2026-11-21).** The arena's own slice data holds
  only ~140 artist-placed ground-cover clumps; the dense carpet in the game
  comes from Coatlicue's procedural vegetation system, whose data is
  `sharedassets/coatlicue/<level>/regions/r_+00_+00/region.vegetation`
  (162 MB, quantised, undocumented format, in `VegetationStrm*.pak`). The
  level's `resourcelist.txt` names it; `leveldata/vegetationmap.dat` is a dev
  asset and is not shipped.
  `tools/nwlevel/nwveg.py` rebuilds the cover from data we can read: it
  collects the ground-cover models (`*groundcover*`, `*flatgreens*`, `*fern*`)
  the level's foliage slices place, writes one single-mesh prefab per model to
  `<project>/nwveg/`, resolves each prefab's spawnable asset id from
  `Cache/assetdb.sqlite`, and adds an `nw_vegetation` entity to the level
  prefab. `nwlevel.py` calls it at the end of a level build.
  **The project must enable the `Vegetation` gem** (`gem_names` in the
  project's `project.json`) or the components will not resolve.
  O3DE's Vegetation gem spawns *prefabs*, not meshes, and only samples
  `SurfaceData` — i.e. terrain. Vegetation therefore does not appear on the
  arena's raised floor deck (mesh geometry ~1-3 m above the terrain); that
  needs `SurfaceDataMeshComponent` on the floor meshes or explicit
  placements. Instance density is the gem's own system setting (sector point
  density 20 per 16 m sector = ~1.56 instances/m^2 by default).
- **Deferred fog is a horizontal LAYER, not a global volume (2026-11-21).**
  `AZ::Render::DeferredFogComponentConfig` (Gems/Atom/Feature/Common/Code/
  Include/Atom/Feature/ScreenSpace/DeferredFogParams.inl) defaults to
  `FogMinHeight=0.01`, `FogMaxHeight=1.0`, i.e. a one-metre slab at world
  Z 0..1. A level whose ground sits at Z~100 therefore renders **no fog at
  all** however the colour/distances are set — that was the "zero fog" bug.
  `nwlevel._aux_ents` now emits `nw_fog` with `FogMinHeight=-1000`,
  `FogMaxHeight=3000`; widen those for any level outside that band. The
  entity also needs an `EditorPostFxLayerComponent` for `PostFXLayerService`.
- **Ground cover on a mesh deck (2026-11-21).** O3DE's Vegetation gem samples
  `SurfaceData`, which is terrain only. `nwveg.bake_deck_cover()` therefore
  writes `Levels/<level>/chunks/chunk_99_veg.prefab` with ground-cover
  clumps standing on the level's own `*floor*`/`*stairs*` mesh pieces (3 per
  piece, jittered, random yaw, 0.75-1.3 scale). Chunk entities are local to
  that chunk's `SlicePlacement`, so the baker adds the placement translate
  to reach world space. The level loader picks the file up through its
  `chunks/chunk_*.prefab` glob.
- **Fog comes from the time-of-day file, not the level (2026-11-21).** The
  `<Fog ViewDistance="14336">` in `mission_mission0.xml` is a **culling**
  distance, not the visual fog. New World's actual fog is in
  `libs/timeofday/modes/<level>.xml` (in `GameData.pak`, named by the
  level's `resourcelist.txt`) as `<Variable Name="...">` entries whose
  `Value`/`Color` attribute is already evaluated at the level's `Time`.
  For `nw_arena_3v3_04` at t=8.83: `Fog color` 0.217/0.411/0.686,
  `Fog height (bottom)` 0, `Fog layer density (bottom)` 0.05,
  `Fog height (top)` 400, `Fog layer density (top)` 0.02, plus a second
  volumetric layer at heights 90..500 with albedo 0.521/0.939/0.982.
  That is the *same shape* as O3DE's deferred fog (a slab between two world
  heights with a density), and both engines' heights are absolute world Z,
  so `nwenv.read_timeofday()` / `nwenv.fog_config()` pass the game's own
  numbers through: `FogMinHeight`/`FogMaxHeight` 0/400, `FogColor` the TOD
  colour, `FogMode` 1 (Exponential), `FogDensity` the bottom-layer density.
  Nothing here is invented — it is the level's own data, which is why it is
  safe to keep in the level's fog entity (the save path never writes
  `mission_mission0.xml` or the TOD).
  `GameData.pak` entries are Oodle-compressed (zip method 15); read them
  with `tools/nwpak/nwpak._read_entry`, not `zipfile.read`.
- **Two-layer fog: design of record (owner decision 2026-11-21).** The owner
  wants New World's two fog layers rendered as they are in the game, so the
  work is split deliberately:
  1. **Render (engine):** extend the existing `DeferredFogPass` rather than
     write a new pass. Its SRG constants are generated from
     `Gems/Atom/Feature/Common/Code/Include/Atom/Feature/ScreenSpace/
     DeferredFogParams.inl` through the `AZ_GFX_*_PARAM` macros, which also
     produce the settings members, the serialize context and the editor
     component's data elements — so new fields cost one line each in that
     file plus a UI element in
     `AtomLyIntegration/CommonFeatures/.../EditorDeferredFogComponent.cpp`.
     Missing SRG bindings are tolerated (`if (MemberName##SrgIndex.IsValid())`),
     so params can land before the shader uses them.
     Shader: `Gems/Atom/Feature/Common/Assets/Shaders/ScreenSpace/DeferredFog.azsl`.
     The pass is a `FullscreenTrianglePass`; `MainPS` already computes the
     ray/slab intersection, so a second layer means running that math for a
     second (minHeight, maxHeight) and compositing
     `a = 1-(1-a1)(1-a2)`, `c = (c1*a1 + c2*a2*(1-a1))/a`.
     New params needed: `FogColorTop`, `FogDensityTop` (layer 1 ramp),
     `FogLayer2Enabled`, `FogColor2`, `FogColorTop2`, `FogMinHeight2`,
     `FogMaxHeight2`, `FogDensity2`, `FogDensityTop2`. Default the ramps to
     their bottom values and layer 2 to off so existing levels do not change.
  2. **Data/authoring (gem `NWFog`):** a component whose fields are NW's TOD
     fog variables one-for-one (no O3DE concepts), TOD import on load,
     TOD write-back on export into an overlay pak (see `tools/nwpak/nwpak.py`),
     and a bus that drives the fog pass for preview. The TOD is spline-based:
     default behaviour is to edit the value at the level's `Time` by
     inserting/replacing that key, not to rewrite the whole day.
  What cannot be matched, and must be stated in the UI: NW's second layer is
  ray-marched volumetric fog with sun/ambient shadowing, per-source
  anisotropy, in-scattering and extinction, and a zenith fade. O3DE's pass is
  analytic and screen-space. Two-layer analytic fog reproduces the TOD's
  heights, density ramps and colours; it does not reproduce the scattering.
