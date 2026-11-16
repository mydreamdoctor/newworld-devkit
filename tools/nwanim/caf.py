"""New World .caf animation decoder.

.caf is a CrChF container (same file family as .cgf/.skin). Chunks:

  0x3002  MotionParams (NW ver 0x925 == Lumberyard MotionParams905, 132 bytes):
          assetFlags, compression, ticksPerFrame, secsPerTick, startTick,
          endTick, 5 motion f32s, StartLocation QuatT, EndLocation QuatT,
          8 heel/toe f32s.
  0x100d  Controller chunk, ver 0x831 == CONTROLLER_CHUNK_DESC_0831:
          u32 controllerId (crc32 of bone name, resolved via skeleton
          CompiledBones records), u32 flags, u16 nRotKeys, u16 nPosKeys,
          u8 rotFmt, u8 rotTimeFmt, u8 posFmt, u8 posKeysInfo, u8 posTimeFmt,
          u8 tracksAligned.

Payload after the 18-byte header is 4-byte aligned; each section starts on a
4-byte boundary: rot values, rot times, pos values, pos times.
posKeysInfo == 0 (eKeyTimeRotation) means position keys share the rotation
key times; == 1 means an own position time array follows.

Formats seen in the NW corpus:
  rotation: 5 = SmallTree48BitQuat (6 B), 8 = SmallTree64BitExtQuat (8 B).
            0 = no rotation track.
  position: 2 = Vec3 f32x3 (12 B). 0 = no position track.
  times:    0 = f32, 1 = u16, 2 = u8; all in ticks
            (seconds = ticks * secsPerTick).

SmallTree quats drop the largest-magnitude component (always reconstructed
positive) and pack the other three components:
  fmt 5: three 15-bit fields at bits 0/15/30, 2-bit dropped index at bit 46,
         component = field/MAX_15BITf - RANGE_15BIT.
  fmt 8: 21-bit, 21-bit, 20-bit fields at bits 0/21/42, index at bit 62,
         components scaled by MAX_21BITf / MAX_20BITf.
(Layout and constants from Lumberyard QuatQuantization.h, leads-only;
verified against NW chunk sizes.)
"""

import math
import struct

C_AF_TYPE = 0x100d
C_TIMING = 0x3002
C_BONES = 0x2000

MAX_15BIT = 23170.0
RANGE_15BIT = 0.707106781186
MAX_21BIT = 1482909.0
RANGE_21BIT = 0.707106781186
MAX_20BIT = 741454.0
RANGE_20BIT = 0.707106781186

_ROT_SIZE = {1: 16, 3: 8, 4: 4, 5: 6, 6: 8, 7: 8, 8: 8}
_POS_SIZE = {0: 12, 1: 12, 2: 12}
_TIME_SIZE = {0: 4, 1: 2, 2: 1}


class CafError(Exception):
    pass


class UnsupportedFormat(CafError):
    pass


def _al4(n):
    return (n + 3) & ~3


def chunk_table(data):
    """CrChF chunk table, same layout as tools/nwmesh/cgf.py."""
    if data[:5] != b"CrChF":
        raise CafError("not a CrChF file")
    cnt, off = struct.unpack_from("<II", data, 8)
    chunks = []
    for i in range(cnt):
        typ, ver, cid, size, co = struct.unpack_from("<HHIII", data, off + 16 * i)
        chunks.append({"type": typ, "ver": ver, "off": co, "size": size, "id": cid})
    return chunks


def _q48(m1, m2, m3):
    val = m1 | (m2 << 16) | (m3 << 32)
    idx = (val >> 46) & 3
    comp = [0.0, 0.0, 0.0, 0.0]
    c, ss = 0, 0.0
    for i in range(4):
        if i == idx:
            continue
        packed = (val >> c) & 0x7FFF
        comp[i] = packed / MAX_15BIT - RANGE_15BIT
        ss += comp[i] * comp[i]
        c += 15
    comp[idx] = math.sqrt(max(0.0, 1.0 - ss))
    return comp


def _q64ext(m1, m2):
    val = m1 | (m2 << 32)
    idx = (val >> 62) & 3
    comp = [0.0, 0.0, 0.0, 0.0]
    off = [i for i in range(4) if i != idx]
    comp[off[0]] = (val & 0x1FFFFF) / MAX_21BIT - RANGE_21BIT
    comp[off[1]] = ((val >> 21) & 0x1FFFFF) / MAX_21BIT - RANGE_21BIT
    comp[off[2]] = ((val >> 42) & 0xFFFFF) / MAX_20BIT - RANGE_20BIT
    ss = comp[off[0]] ** 2 + comp[off[1]] ** 2 + comp[off[2]] ** 2
    comp[idx] = math.sqrt(max(0.0, 1.0 - ss))
    return comp


def _rot_keys(buf, n, fmt):
    if fmt == 1:
        return [list(struct.unpack_from("<4f", buf, i * 16)) for i in range(n)]
    if fmt == 5:
        return [_q48(*struct.unpack_from("<HHH", buf, i * 6)) for i in range(n)]
    if fmt == 8:
        return [_q64ext(*struct.unpack_from("<II", buf, i * 8)) for i in range(n)]
    raise UnsupportedFormat("rotation format %d" % fmt)


def _pos_keys(buf, n, fmt):
    if fmt in (0, 1, 2):
        return [list(struct.unpack_from("<3f", buf, i * 12)) for i in range(n)]
    raise UnsupportedFormat("position format %d" % fmt)


def _times(buf, n, fmt):
    if fmt == 0:
        return list(struct.unpack_from("<%df" % n, buf))
    if fmt == 1:
        return list(struct.unpack_from("<%dH" % n, buf))
    if fmt == 2:
        return list(struct.unpack_from("<%dB" % n, buf))
    raise UnsupportedFormat("key-time format %d" % fmt)


def parse_timing(data, chunks):
    """MotionParams905 -> dict with ticksPerFrame, secsPerTick, start, end."""
    ch = [c for c in chunks if c["type"] == C_TIMING]
    if not ch:
        raise CafError("no timing chunk")
    o = ch[0]["off"]
    (flags, comp, tpf, spt, start, end) = struct.unpack_from("<IIifii", data, o)
    return {
        "flags": flags, "compression": comp,
        "ticksPerFrame": tpf, "secsPerTick": spt,
        "start": start, "end": end,
        "duration": (end - start) * spt,
    }


def parse_controllers(data, chunks):
    """-> {controllerId: {'rot': [(t,q)], 'pos': [(t,v)], 'flags': int}}"""
    out = {}
    for c in chunks:
        if c["type"] != C_AF_TYPE:
            continue
        o = c["off"]
        cid, flags, nr, np_ = struct.unpack_from("<IIHH", data, o)
        rf, rtf, pf, pki, ptf, ta = struct.unpack_from("<6B", data, o + 12)
        p = _al4(o + 18) - o
        track = {"flags": flags, "rot": [], "pos": []}
        if nr:
            rsz = _ROT_SIZE.get(rf)
            if rsz is None:
                raise UnsupportedFormat("rotation format %d" % rf)
            rots = _rot_keys(data[o + p:], nr, rf)
            p = _al4(p + nr * rsz)
            rtimes = _times(data[o + p:], nr, rtf)
            p = _al4(p + nr * _TIME_SIZE[rtf])
            track["rot"] = list(zip(rtimes, rots))
        else:
            rtimes = None
        if np_:
            psz = _POS_SIZE.get(pf)
            if psz is None:
                raise UnsupportedFormat("position format %d" % pf)
            poss = _pos_keys(data[o + p:], np_, pf)
            p = _al4(p + np_ * psz)
            if pki == 0:
                ptimes = rtimes if rtimes is not None else []
            else:
                ptimes = _times(data[o + p:], np_, ptf)
            track["pos"] = list(zip(ptimes, poss))
        out[cid] = track
    return out


def parse_bones(data):
    """CompiledBones chunk 0x2000 ver 0x800 -> list of bone dicts.

    Record = 584 bytes: ctrlId, 2x104B physics, mass, W2B Matrix34,
    B2W Matrix34, name[256], limbId, offsetParent, numChildren,
    offsetChildren. Chunk begins with a 32-byte reserved header.
    """
    chunks = chunk_table(data)
    ch = [c for c in chunks if c["type"] == C_BONES]
    if not ch:
        raise CafError("no CompiledBones chunk")
    c = ch[0]
    body = data[c["off"] + 32: c["off"] + c["size"]]
    REC = 584
    if len(body) % REC:
        raise CafError("CompiledBones size %d not multiple of %d" % (len(body), REC))
    bones = []
    for i in range(len(body) // REC):
        b = body[i * REC: (i + 1) * REC]
        cid = struct.unpack_from("<I", b, 0)[0]
        w2b = struct.unpack_from("<12f", b, 216)
        b2w = struct.unpack_from("<12f", b, 264)
        name = b[312:568].split(b"\0")[0].decode("ascii", "replace")
        limb, par, nch, coff = struct.unpack_from("<iiIi", b, 568)
        bones.append({
            "id": cid, "name": name, "limb": limb,
            "parent": i + par if par else None,
            "w2b": w2b, "b2w": b2w,
            "children": (i + coff, nch) if nch else None,
        })
    return bones


def parse_caf(data):
    """Full .caf -> {'timing': ..., 'controllers': {cid: tracks}}."""
    chunks = chunk_table(data)
    return {
        "timing": parse_timing(data, chunks),
        "controllers": parse_controllers(data, chunks),
    }
