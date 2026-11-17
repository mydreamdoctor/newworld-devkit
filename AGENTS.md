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
