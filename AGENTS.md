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
- Build/test layout: everything under `build/` (gitignored). Verified recipe and
  stage-1 findings are in the graphiti store and in `NW-STAGE1-FINDINGS.md`.
- 🔴 **Check free RAM before launching the Editor or AssetProcessor.** This host
  is shared with other heavy work and the machine has OOM-crashed once already.
  Run `free -g` first; if free+cache is under ~24 GiB, do not launch — tell the
  owner instead. One editor + one AP at a time; kill stragglers (`pgrep -af
  'profile/(Editor|AssetProcessor)'`) before a new run.
- Plan of record: project-mcp `prj_147a0f93` (dashboard http://127.0.0.1:8090).
