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
