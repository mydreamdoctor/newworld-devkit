"""Python asset builder: NW terrain.json -> O3DE products.

  *terrain.json  -> intermediate <dirname>.prefab: the terrain level
                   (TerrainWorld + one TerrainSpawner/HeightGradient
                   pair per region heightmap). Dev-kit layout: the
                   terrain.json sits in a level dir with sibling
                   heightmaps/<r_+xx_+yy>.tif image sources (staged by
                   tools/nwterrain/nw2level.py from the raw NW
                   regions/<r>/region.heightmap files). The prefab
                   intermediate compiles to a .spawnable, so the level
                   opens natively.

Save-back: tools/nwterrain/nwexport.py writes edited heightmaps back
to NW regions/<r>/region.heightmap + terrain.json.

Runs inside AssetBuilder (PythonAssetBuilder gem).
"""
import json
import os
import sys

import azlmbr.asset.builder
import azlmbr.bus
import azlmbr.math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import terrainjson as _tj
import nw2level

BUS_ID = azlmbr.math.Uuid_CreateString('{C3D4E5F6-7081-92A3-B4C5-D6E7F8010203}')
JOB_KEY = 'NW Terrain'
handler = None


def _regions(level_dir, source_rel_dir):
    """[(name,(ix,iy),size,mh,tif-path,img-hint)] for heightmaps/*.tif."""
    out = []
    hdir = os.path.join(level_dir, 'heightmaps')
    tj = _tj.load(os.path.join(level_dir, 'terrain.json'))
    mh = float(tj.get('mountainHeight', 2048.0))
    for fn in sorted(os.listdir(hdir)) if os.path.isdir(hdir) else []:
        if not fn.endswith('.tif'):
            continue
        rname = fn[:-4]
        ix, iy = nw2level.region_index(rname)
        hint = '%s/heightmaps/%s.tif' % (source_rel_dir, rname)
        out.append((rname, (ix, iy), 0, mh,
                    os.path.join(hdir, fn), hint))
    return out, mh


def on_create_jobs(args):
    request = args[0]
    response = azlmbr.asset.builder.CreateJobsResponse()
    jobs = []
    for platformInfo in request.enabledPlatforms:
        jobDesc = azlmbr.asset.builder.JobDescriptor()
        jobDesc.jobKey = JOB_KEY
        jobDesc.set_platform_identifier('common')
        jobs.append(jobDesc)
    response.createJobOutputs = jobs
    deps = []
    null = azlmbr.math.Uuid()
    try:
        level_dir = os.path.dirname(request.fullPath)
        rel_dir = os.path.dirname(request.sourceFile.replace('\\', '/'))
        regs, _ = _regions(level_dir, rel_dir)
        for rname, _, _, _, tif, _ in regs:
            deps.append(azlmbr.asset.builder.SourceFileDependency(
                os.path.relpath(tif, level_dir).replace(os.sep, '/'),
                null, 0))
    except Exception as e:
        print('nw_terrain_builder dep scan failed: %s' % e)
    response.sourceFileDependencyList = deps
    response.result = azlmbr.asset.builder.CreateJobsResponse_ResultSuccess
    return response


def on_process_job(args):
    request = args[0]
    response = azlmbr.asset.builder.ProcessJobResponse()
    if not request.jobDescription.jobKey.startswith(JOB_KEY):
        return response
    src = request.fullPath
    level_dir = os.path.dirname(src)
    rel_dir = os.path.dirname(request.sourceFile.replace('\\', '/'))
    level = os.path.basename(level_dir) or 'level'
    try:
        from heightmap import decode
        regs, mh = _regions(level_dir, rel_dir)
        sized = []
        for rname, (ix, iy), _, mh2, tif, hint in regs:
            hm = decode(open(tif, 'rb').read())
            sized.append((rname, (ix, iy), hm.w, mh2, hint))
        prefab = nw2level.build_prefab(level, sized)
    except Exception as e:
        print('nw_terrain_builder failed on %s: %s' % (src, e))
        return response
    null_type = azlmbr.math.Uuid_CreateString(
        '{00000000-0000-0000-0000-000000000000}')
    pf = os.path.join(request.tempDirPath, level + '.prefab')
    with open(pf, 'w') as f:
        json.dump(prefab, f, indent=1)
    p = azlmbr.asset.builder.JobProduct(pf, null_type, 0)
    p.dependenciesHandled = True
    p.outputFlags = azlmbr.asset.builder.JobProduct_IntermediateAsset
    response.outputProducts = [p]
    response.resultCode = azlmbr.asset.builder.ProcessJobResponse_Success
    return response


def on_shutdown(args):
    global handler
    if handler is not None:
        handler.disconnect()
    handler = None


def register():
    desc = azlmbr.asset.builder.AssetBuilderDesc()
    desc.name = 'NW Terrain Builder'
    desc.busId = BUS_ID
    desc.version = 2
    pats = []
    for pat in ('*terrain.json',):
        p = azlmbr.asset.builder.AssetBuilderPattern()
        p.pattern = pat
        p.type = azlmbr.asset.builder.AssetBuilderPattern_Wildcard
        pats.append(p)
    desc.patterns = pats
    outcome = azlmbr.asset.builder.PythonAssetBuilderRequestBus(
        azlmbr.bus.Broadcast, 'RegisterAssetBuilder', desc)
    if not outcome.IsSuccess():
        print('nw_terrain_builder: registration failed')
        return None
    h = azlmbr.asset.builder.PythonBuilderNotificationBusHandler()
    h.connect(BUS_ID)
    h.add_callback('OnCreateJobsRequest', on_create_jobs)
    h.add_callback('OnProcessJobRequest', on_process_job)
    h.add_callback('OnShutdown', on_shutdown)
    print('nw_terrain_builder: registered for *terrain.json')
    return h


handler = register()
