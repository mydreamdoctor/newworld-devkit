"""Python asset builder: NW .dynamicslice -> O3DE products.

  *.dynamicslice -> intermediate <name>.prefab (entities flattened at
                  their world transforms; mapped components converted)
                  + <name>.sidecar.json (unmapped component inventory)
                  The .prefab intermediate is picked up by PrefabBuilder,
                  so a .dynamicslice opens as a native O3DE level.

Save-back: tools/nwslice/prefab2slice.py patches m_worldTM/splines in
the original slice (byte-exact outside edited fields).

Runs inside AssetBuilder (PythonAssetBuilder gem).
"""
import json
import os
import sys

import azlmbr.asset.builder
import azlmbr.bus
import azlmbr.math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slice2prefab

BUS_ID = azlmbr.math.Uuid_CreateString('{B2C3D4E5-6F70-8192-A3B4-C5D6E7F80102}')
JOB_KEY = 'NW Slice'
handler = None


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
    response.result = azlmbr.asset.builder.CreateJobsResponse_ResultSuccess
    return response


def on_process_job(args):
    request = args[0]
    response = azlmbr.asset.builder.ProcessJobResponse()
    if not request.jobDescription.jobKey.startswith(JOB_KEY):
        return response
    src = request.fullPath
    base = os.path.splitext(os.path.basename(src))[0]
    try:
        prefab, skipped = slice2prefab.convert(open(src, 'rb').read(), base)
    except Exception as e:
        print('nw_slice_builder failed on %s: %s' % (src, e))
        return response
    null_type = azlmbr.math.Uuid_CreateString(
        '{00000000-0000-0000-0000-000000000000}')
    products = []
    pf = os.path.join(request.tempDirPath, base + '.prefab')
    with open(pf, 'w') as f:
        json.dump(prefab, f, indent=2)
    p = azlmbr.asset.builder.JobProduct(pf, null_type, 0)
    p.dependenciesHandled = True
    p.outputFlags = azlmbr.asset.builder.JobProduct_IntermediateAsset
    products.append(p)
    sc = os.path.join(request.tempDirPath, base + '.sidecar.json')
    with open(sc, 'w') as f:
        json.dump({'slice': os.path.basename(src), 'skipped': skipped},
                  f, indent=1)
    p = azlmbr.asset.builder.JobProduct(sc, null_type, 1)
    p.dependenciesHandled = True
    p.outputFlags = azlmbr.asset.builder.JobProduct_IntermediateAsset
    products.append(p)
    response.outputProducts = products
    response.resultCode = azlmbr.asset.builder.ProcessJobResponse_Success
    return response


def on_shutdown(args):
    global handler
    if handler is not None:
        handler.disconnect()
    handler = None


def register():
    desc = azlmbr.asset.builder.AssetBuilderDesc()
    desc.name = 'NW Slice Builder'
    desc.busId = BUS_ID
    desc.version = 2
    pats = []
    for pat in ('*.dynamicslice',):
        p = azlmbr.asset.builder.AssetBuilderPattern()
        p.pattern = pat
        p.type = azlmbr.asset.builder.AssetBuilderPattern_Wildcard
        pats.append(p)
    desc.patterns = pats
    outcome = azlmbr.asset.builder.PythonAssetBuilderRequestBus(
        azlmbr.bus.Broadcast, 'RegisterAssetBuilder', desc)
    if not outcome.IsSuccess():
        print('nw_slice_builder: registration failed')
        return None
    h = azlmbr.asset.builder.PythonBuilderNotificationBusHandler()
    h.connect(BUS_ID)
    h.add_callback('OnCreateJobsRequest', on_create_jobs)
    h.add_callback('OnProcessJobRequest', on_process_job)
    h.add_callback('OnShutdown', on_shutdown)
    print('nw_slice_builder: registered for *.dynamicslice')
    return h


handler = register()
