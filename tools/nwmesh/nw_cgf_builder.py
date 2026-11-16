"""Python asset builder: NW .cgf/.skin -> intermediate .glb.

Runs inside AssetBuilder (PythonAssetBuilder gem). Converts each
.cgf/.skin source to a .glb emitted as an IntermediateAsset product;
the AP then treats the .glb as a new source and Scene Builder turns it
into .azmodel/.actor products.

The .cgfheap sibling is declared a source dependency so heap changes
retrigger the job.
"""
import os
import sys

import azlmbr.asset.builder
import azlmbr.bus
import azlmbr.math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cgf2glb

BUS_ID = azlmbr.math.Uuid_CreateString('{C6F1A2B3-4D5E-6F70-8192-A3B4C5D6E7F8}')
JOB_KEY = 'NW CGF to GLB'
handler = None


def _glb_asset_type():
    # Unknown/none asset type is fine for intermediate products; the
    # AP re-scans the file as a source.
    return azlmbr.math.Uuid_CreateString('{00000000-0000-0000-0000-000000000000}')


def on_create_jobs(args):
    request = args[0]
    response = azlmbr.asset.builder.CreateJobsResponse()
    jobs = []
    for platformInfo in request.enabledPlatforms:
        jobDesc = azlmbr.asset.builder.JobDescriptor()
        jobDesc.jobKey = JOB_KEY
        # intermediate products must target the common platform
        jobDesc.set_platform_identifier('common')
        jobs.append(jobDesc)
    response.createJobOutputs = jobs
    # the .cgfheap sibling feeds the mesh streams; retrigger on change
    if request.sourceFile.lower().endswith('.cgf'):
        dep = azlmbr.asset.builder.SourceFileDependency(
            request.sourceFile + 'heap', azlmbr.math.Uuid(), 0)
        response.sourceFileDependencyList = [dep]
    response.result = azlmbr.asset.builder.CreateJobsResponse_ResultSuccess
    return response


def on_process_job(args):
    request = args[0]
    response = azlmbr.asset.builder.ProcessJobResponse()
    if not request.jobDescription.jobKey.startswith(JOB_KEY):
        return response
    src = request.fullPath
    base = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(request.tempDirPath, base + '.glb')
    try:
        cgf2glb.convert(src, dst)
    except Exception as e:
        print('cgf2glb failed on %s: %s' % (src, e))
        return response
    null_type = azlmbr.math.Uuid_CreateString(
        '{00000000-0000-0000-0000-000000000000}')
    product = azlmbr.asset.builder.JobProduct(dst, null_type, 0)
    product.outputFlags = azlmbr.asset.builder.JobProduct_IntermediateAsset
    response.outputProducts = [product]
    response.dependenciesHandled = True
    response.resultCode = azlmbr.asset.builder.ProcessJobResponse_Success
    return response


def on_shutdown(args):
    global handler
    if handler is not None:
        handler.disconnect()
    handler = None


def register():
    desc = azlmbr.asset.builder.AssetBuilderDesc()
    desc.name = 'NW CGF Builder'
    desc.busId = BUS_ID
    desc.version = 1
    pats = []
    for pat in ('*.cgf', '*.skin'):
        p = azlmbr.asset.builder.AssetBuilderPattern()
        p.pattern = pat
        p.type = azlmbr.asset.builder.AssetBuilderPattern_Wildcard
        pats.append(p)
    desc.patterns = pats
    outcome = azlmbr.asset.builder.PythonAssetBuilderRequestBus(
        azlmbr.bus.Broadcast, 'RegisterAssetBuilder', desc)
    if not outcome.IsSuccess():
        print('nw_cgf_builder: registration failed')
        return None
    h = azlmbr.asset.builder.PythonBuilderNotificationBusHandler()
    h.connect(BUS_ID)
    h.add_callback('OnCreateJobsRequest', on_create_jobs)
    h.add_callback('OnProcessJobRequest', on_process_job)
    h.add_callback('OnShutdown', on_shutdown)
    print('nw_cgf_builder: registered for *.cgf / *.skin')
    return h


handler = register()
