"""Python asset builder: NW .cgf/.skin -> intermediate .glb.

Runs inside AssetBuilder (PythonAssetBuilder gem). Converts each
.cgf/.skin source to a .glb emitted as an IntermediateAsset product;
the AP then treats the .glb as a new source and Scene Builder turns it
into .azmodel/.actor products.

The .cgfheap sibling is declared a source dependency so heap changes
retrigger the job.
"""
import json
import os
import shutil
import sys

import azlmbr.asset.builder
import azlmbr.bus
import azlmbr.math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              '..', 'nwmat'))
import cgf
import cgf2glb
import dds as nwdds
import mtl as nwmtl

BUS_ID = azlmbr.math.Uuid_CreateString('{C6F1A2B3-4D5E-6F70-8192-A3B4C5D6E7F8}')
JOB_KEY = 'NW CGF to GLB'
handler = None


def _glb_asset_type():
    # Unknown/none asset type is fine for intermediate products; the
    # AP re-scans the file as a source.
    return azlmbr.math.Uuid_CreateString('{00000000-0000-0000-0000-000000000000}')


def _scan_root(request):
    full = request.fullPath.replace('\\', '/')
    rel = request.sourceFile.replace('\\', '/')
    if full.endswith(rel):
        return full[:-len(rel)]
    return os.path.dirname(full)


def _mesh_materials(mesh_path):
    """Returns (mtl_path, {sub_name: {Map: abs_tex_path}}) or (None, {})."""
    try:
        c = cgf.load(mesh_path)
    except Exception:
        return None, {}
    mtl_path, m = nwmtl.find_mtl_for_mesh(mesh_path, c.mtl_subs or [c.mtl])
    if not m:
        return mtl_path, {}
    mesh_dir = os.path.dirname(mesh_path)
    out = {}
    for sub in m.subs:
        tex = {}
        for mp, ref in sub.textures.items():
            p = nwmtl.resolve_texture(ref, mesh_dir)
            if p:
                tex[mp] = p
        out[sub.name] = tex
    return mtl_path, out


def _rel(path, scan_root):
    return os.path.relpath(path, scan_root).replace(os.sep, '/')


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
    deps = []
    null = azlmbr.math.Uuid()
    # the .cgfheap sibling feeds the mesh streams; retrigger on change
    if request.sourceFile.lower().endswith('.cgf'):
        deps.append(azlmbr.asset.builder.SourceFileDependency(
            request.sourceFile + 'heap', null, 0))
    # declare the .mtl and its textures as source dependencies
    try:
        full = getattr(request, 'fullPath', None)
        if not full:
            raise RuntimeError('no fullPath')
        scan_root = _scan_root(request)
        mtl_path, mats = _mesh_materials(full)
        def _in_root(p):
            r = _rel(p, scan_root)
            return r if not r.startswith('..') else None
        if mtl_path:
            mr = _in_root(mtl_path)
            if mr:
                deps.append(azlmbr.asset.builder.SourceFileDependency(
                    mr, null, 0))
            for tex in mats.values():
                for p in tex.values():
                    for dp in [p] + nwdds.mip_parts(p):
                        dr = _in_root(dp)
                        if dr:
                            deps.append(azlmbr.asset.builder.SourceFileDependency(
                                dr, null, 0))
    except Exception as e:
        print('nw_cgf_builder dep scan failed: %s' % e)
    response.sourceFileDependencyList = deps
    response.result = azlmbr.asset.builder.CreateJobsResponse_ResultSuccess
    return response


def on_process_job(args):
    request = args[0]
    response = azlmbr.asset.builder.ProcessJobResponse()
    if not request.jobDescription.jobKey.startswith(JOB_KEY):
        return response
    src = request.fullPath
    base = os.path.splitext(os.path.basename(src))[0]

    # .cgfheap is a companion heap: emit a manifest so it registers as a
    # processed source (Asset Browser visibility), no scene products.
    if src.lower().endswith('.cgfheap'):
        try:
            import cgf as _cgf
            chunks = len(_cgf.chunk_table(open(src, 'rb').read()))
        except Exception:
            chunks = -1
        man = os.path.join(request.tempDirPath, base + '.cgfheap.json')
        with open(man, 'w') as f:
            json.dump({'cgfheap': os.path.basename(src),
                       'size': os.path.getsize(src), 'chunks': chunks}, f)
        null_type = azlmbr.math.Uuid_CreateString(
            '{00000000-0000-0000-0000-000000000000}')
        p = azlmbr.asset.builder.JobProduct(man, null_type, 0)
        p.outputFlags = azlmbr.asset.builder.JobProduct_IntermediateAsset
        p.dependenciesHandled = True
        response.outputProducts = [p]
        response.resultCode = azlmbr.asset.builder.ProcessJobResponse_Success
        return response

    dst = os.path.join(request.tempDirPath, base + '.glb')

    # resolve the sibling .mtl into a texture map; copy textures beside
    # the .glb so AssImp resolves the image URIs, and emit them as
    # intermediate products so ImageBuilder makes streamingimages.
    texmap = {}
    tex_products = {}
    try:
        _, mats = _mesh_materials(src)
        for sub_name, tex in mats.items():
            t = {}
            for mp, p in tex.items():
                if mp not in ('Diffuse', 'Bumpmap'):
                    continue
                # prefix with the mesh stem: intermediate products land
                # beside the .glb and must not collide across jobs.
                fname = '%s__%s' % (base, os.path.basename(p))
                if fname in tex_products:
                    t['baseColor' if mp == 'Diffuse' else 'normal'] = fname
                    continue
                outp = os.path.join(request.tempDirPath, fname)
                if p.lower().endswith('.dds'):
                    with open(outp, 'wb') as f:
                        f.write(nwdds.reassemble(p))
                else:
                    shutil.copyfile(p, outp)
                t['baseColor' if mp == 'Diffuse' else 'normal'] = fname
                tex_products[fname] = outp
            if t:
                texmap[sub_name] = t
    except Exception as e:
        print('nw_cgf_builder mtl resolve failed: %s' % e)

    try:
        cgf2glb.convert(src, dst, texmap=texmap)
    except Exception as e:
        print('cgf2glb failed on %s: %s' % (src, e))
        return response
    null_type = azlmbr.math.Uuid_CreateString(
        '{00000000-0000-0000-0000-000000000000}')
    products = []
    product = azlmbr.asset.builder.JobProduct(dst, null_type, 0)
    product.outputFlags = azlmbr.asset.builder.JobProduct_IntermediateAsset
    product.dependenciesHandled = True
    products.append(product)
    for i, tp in enumerate(tex_products.values()):
        p = azlmbr.asset.builder.JobProduct(tp, null_type, i + 1)
        p.outputFlags = azlmbr.asset.builder.JobProduct_IntermediateAsset
        p.dependenciesHandled = True
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
    desc.name = 'NW CGF Builder'
    desc.busId = BUS_ID
    desc.version = 12
    pats = []
    for pat in ('*.cgf', '*.cgfheap', '*.skin'):
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
