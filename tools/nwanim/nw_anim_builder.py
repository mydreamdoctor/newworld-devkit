"""Python asset builder: NW animation sources -> O3DE products.

  *.caf  -> intermediate .glb (skeleton nodes + animation channels)
            which Scene Builder then turns into an EMotionFX .motion.
            Bone names are resolved from the project's .chr/.skin
            CompiledBones records (controllerId -> name); unresolved
            ids keep numeric node names.
  *.adb  -> <name>.adb.json product: the parsed Mannequin index
            (categories/fragments/animation refs/procedural clips),
            plus an intermediate .animgraph state machine (one
            AnimGraphMotionNode per Mannequin category).
  *.chr  -> intermediate .glb holding the skeleton node hierarchy
            (bind-pose TRS) for Scene Builder.

Runs inside AssetBuilder (PythonAssetBuilder gem).
"""
import json
import os
import sys

import azlmbr.asset.builder
import azlmbr.bus
import azlmbr.math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adb as nwadb
import adb2animgraph
import caf as nwcaf
import caf2glb

BUS_ID = azlmbr.math.Uuid_CreateString('{A1B2C3D4-5E6F-7081-92A3-B4C5D6E7F801}')
JOB_KEY = 'NW Anim'
handler = None
_skel_cache = {}


def _scan_root(request):
    full = request.fullPath.replace('\\', '/')
    rel = request.sourceFile.replace('\\', '/')
    if full.endswith(rel):
        return full[:-len(rel)]
    return os.path.dirname(full)


def _skel_index(scan_root):
    """[(path, frozenset ctrlIds)] for every .chr/.skin under the project."""
    if scan_root in _skel_cache:
        return _skel_cache[scan_root]
    idx = []
    for dirpath, _, files in os.walk(scan_root):
        for fn in files:
            if not fn.lower().endswith(('.chr', '.skin')):
                continue
            p = os.path.join(dirpath, fn)
            try:
                with open(p, 'rb') as f:
                    idx.append((p, frozenset(
                        b['id'] for b in nwcaf.parse_bones(f.read()))))
            except Exception:
                pass
    _skel_cache[scan_root] = idx
    return idx


def _best_skel(scan_root, ctrl_ids):
    """Path of the skeleton file covering the most ctrlIds."""
    best, best_n = None, 0
    want = set(ctrl_ids)
    for p, ids in _skel_index(scan_root):
        n = len(ids & want)
        if n > best_n:
            best, best_n = p, n
    return best


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
    if request.sourceFile.lower().endswith('.caf'):
        try:
            scan_root = _scan_root(request)
            with open(request.fullPath, 'rb') as f:
                data = f.read()
            cids = nwcaf.parse_controllers(
                data, nwcaf.chunk_table(data)).keys()
            skel = _best_skel(scan_root, cids)
            if skel:
                deps.append(azlmbr.asset.builder.SourceFileDependency(
                    os.path.relpath(skel, scan_root).replace(os.sep, '/'),
                    null, 0))
        except Exception as e:
            print('nw_anim_builder dep scan failed: %s' % e)
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
    null_type = azlmbr.math.Uuid_CreateString(
        '{00000000-0000-0000-0000-000000000000}')

    if src.lower().endswith('.adb'):
        try:
            parsed = nwadb.parse_adb(open(src, 'rb').read())
        except Exception as e:
            print('adb parse failed on %s: %s' % (src, e))
            return response
        dst = os.path.join(request.tempDirPath, base + '.adb.json')
        with open(dst, 'w') as f:
            json.dump(parsed, f, indent=1)
        products = [azlmbr.asset.builder.JobProduct(dst, null_type, 0)]
        try:
            ag = os.path.join(request.tempDirPath, base + '.animgraph')
            adb2animgraph.convert(open(src, 'rb').read(), ag)
            products.append(azlmbr.asset.builder.JobProduct(ag, null_type, 1))
        except Exception as e:
            print('adb->animgraph failed on %s: %s' % (src, e))
        for p in products:
            p.outputFlags = azlmbr.asset.builder.JobProduct_IntermediateAsset
        response.outputProducts = products
        response.dependenciesHandled = True
        response.resultCode = azlmbr.asset.builder.ProcessJobResponse_Success
        return response

    # .caf / .chr -> intermediate .glb
    dst = os.path.join(request.tempDirPath, base + '.glb')
    try:
        data = open(src, 'rb').read()
        if src.lower().endswith('.chr'):
            bones = nwcaf.parse_bones(data)
            # emit a skeleton-only glb (nodes + bind pose, no animation)
            g = caf2glb.Gltf()
            node_of = {}
            for i, b in enumerate(bones):
                t, q = caf2glb.local_trs(b, bones)
                par = bones[b['parent']]['id'] if b['parent'] is not None else None
                node_of[b['id']] = g.node(
                    b['name'], rotation=q, translation=t,
                    parent=g.root if par is None else node_of[par])
            g.write(dst)
        else:
            scan_root = _scan_root(request)
            a = nwcaf.parse_caf(data)
            skel = _best_skel(scan_root, a['controllers'].keys())
            skel_data = open(skel, 'rb').read() if skel else None
            caf2glb.convert(data, skel_data, dst, anim_name=base)
    except Exception as e:
        print('nw_anim_builder failed on %s: %s' % (src, e))
        return response
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
    desc.name = 'NW Anim Builder'
    desc.busId = BUS_ID
    desc.version = 3
    pats = []
    for pat in ('*.caf', '*.adb', '*.chr'):
        p = azlmbr.asset.builder.AssetBuilderPattern()
        p.pattern = pat
        p.type = azlmbr.asset.builder.AssetBuilderPattern_Wildcard
        pats.append(p)
    desc.patterns = pats
    outcome = azlmbr.asset.builder.PythonAssetBuilderRequestBus(
        azlmbr.bus.Broadcast, 'RegisterAssetBuilder', desc)
    if not outcome.IsSuccess():
        print('nw_anim_builder: registration failed')
        return None
    h = azlmbr.asset.builder.PythonBuilderNotificationBusHandler()
    h.connect(BUS_ID)
    h.add_callback('OnCreateJobsRequest', on_create_jobs)
    h.add_callback('OnProcessJobRequest', on_process_job)
    h.add_callback('OnShutdown', on_shutdown)
    print('nw_anim_builder: registered for *.caf / *.adb / *.chr')
    return h


handler = register()
