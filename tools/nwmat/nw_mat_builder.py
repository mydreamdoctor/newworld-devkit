"""Python asset builder: NW .mtl -> intermediate .material JSON.

Each sub-material in the .mtl becomes one .material asset on the
StandardPBR material type (mtl2atom does the field mapping). The
.material files are emitted as IntermediateAsset products; the AP
re-scans them and the MaterialBuilder produces .azmaterial products.
Unmappable Cry params/shader features are logged and embedded in the
material's description.

Referenced textures are declared source dependencies so edits retrigger
the job.
"""
import json
import os
import sys

import azlmbr.asset.builder
import azlmbr.bus
import azlmbr.math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dds as nwdds
import mtl as nwmtl
import mtl2atom

BUS_ID = azlmbr.math.Uuid_CreateString('{D7A2B3C4-5E6F-7081-92A3-B4C5D6E7F8A9}')
JOB_KEY = 'NW MTL to Atom'
handler = None


def _scan_root(request):
    full = request.fullPath.replace('\\', '/')
    rel = request.sourceFile.replace('\\', '/')
    if full.endswith(rel):
        return full[:-len(rel)]
    return os.path.dirname(full)


def _tex_paths(request):
    """{sub_name: {Map: abs path}} for the .mtl at request.fullPath."""
    m = nwmtl.Mtl.load(request.fullPath)
    d = os.path.dirname(request.fullPath)
    out = {}
    for sub in m.subs:
        out[sub.name] = {mp: p for mp, ref in sub.textures.items()
                         if (p := nwmtl.resolve_texture(ref, d))}
    return m, out


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
    try:
        scan_root = _scan_root(request)
        for tex in _tex_paths(request)[1].values():
            for p in tex.values():
                for dp in [p] + nwdds.mip_parts(p):
                    deps.append(azlmbr.asset.builder.SourceFileDependency(
                        os.path.relpath(dp, scan_root).replace(os.sep, '/'),
                        azlmbr.math.Uuid(), 0))
    except Exception as e:
        print('nw_mat_builder dep scan failed: %s' % e)
    response.sourceFileDependencyList = deps
    response.result = azlmbr.asset.builder.CreateJobsResponse_ResultSuccess
    return response


def on_process_job(args):
    request = args[0]
    response = azlmbr.asset.builder.ProcessJobResponse()
    if not request.jobDescription.jobKey.startswith(JOB_KEY):
        return response
    try:
        m, tex = _tex_paths(request)
        scan_root = _scan_root(request)
        products = []
        null_type = azlmbr.math.Uuid_CreateString(
            '{00000000-0000-0000-0000-000000000000}')
        for sub in m.subs:
            tex_rel = {}
            for mp, p in tex.get(sub.name, {}).items():
                rel = mtl2atom.project_rel(p, scan_root)
                if not rel.startswith('..'):
                    tex_rel[mp] = rel
            mat, unmapped = mtl2atom.to_atom(sub, tex_rel)
            stem = os.path.splitext(os.path.basename(request.fullPath))[0]
            # Sub-material names collide across mtls in the same dir even for
            # single-sub mtls (rockspike_*_mat_01 all emit rock_shards), so the
            # mtl stem always prefixes the product name.
            name = stem + '__' + (sub.name or stem)
            dst = os.path.join(request.tempDirPath, name + '.material')
            with open(dst, 'w') as f:
                json.dump(mat, f, indent=4)
            p = azlmbr.asset.builder.JobProduct(dst, null_type, len(products))
            p.outputFlags = azlmbr.asset.builder.JobProduct_IntermediateAsset
            p.dependenciesHandled = True
            products.append(p)
            for u in unmapped:
                print('nw_mat_builder %s/%s: %s' % (stem, name, u))
        response.outputProducts = products
        response.dependenciesHandled = True
        response.resultCode = azlmbr.asset.builder.ProcessJobResponse_Success
    except Exception as e:
        print('nw_mat_builder failed on %s: %s' % (request.fullPath, e))
    return response


def on_shutdown(args):
    global handler
    if handler is not None:
        handler.disconnect()
    handler = None


def register():
    desc = azlmbr.asset.builder.AssetBuilderDesc()
    desc.name = 'NW MTL Builder'
    desc.busId = BUS_ID
    desc.version = 3
    pats = []
    for pat in ('*.mtl',):
        p = azlmbr.asset.builder.AssetBuilderPattern()
        p.pattern = pat
        p.type = azlmbr.asset.builder.AssetBuilderPattern_Wildcard
        pats.append(p)
    desc.patterns = pats
    outcome = azlmbr.asset.builder.PythonAssetBuilderRequestBus(
        azlmbr.bus.Broadcast, 'RegisterAssetBuilder', desc)
    if not outcome.IsSuccess():
        print('nw_mat_builder: registration failed')
        return None
    h = azlmbr.asset.builder.PythonBuilderNotificationBusHandler()
    h.connect(BUS_ID)
    h.add_callback('OnCreateJobsRequest', on_create_jobs)
    h.add_callback('OnProcessJobRequest', on_process_job)
    h.add_callback('OnShutdown', on_shutdown)
    print('nw_mat_builder: registered for *.mtl')
    return h


handler = register()
