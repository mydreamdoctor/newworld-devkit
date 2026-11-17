"""New World .adb (Mannequin animation database) parser.

.adb is plain XML:

  <AnimDB FragDef="..." TagDef="...">
    <FragmentList>
      <Category>                       # e.g. Combat_Idle
        <Fragment Tags="..." BlendOutDuration="...">
          <AnimLayer>
            <Blend StartTime Duration ExitTime CurveType/>
            <Animation name="..."/>    # clip id -> .caf of the same name
          </AnimLayer>
          <ProcLayer>
            <Blend .../>
            <Procedural type="CAGE-..." contextType="...">
              <ProceduralParams><X value="..."/>...</ProceduralParams>
            </Procedural>
          </ProcLayer>
        </Fragment>
      </Category>
    </FragmentList>
    <SubADBs><SubADB Tags="..." priority=".." filename="..."/></SubADBs>
  </AnimDB>

The Procedural clips are New-World-specific clip types; we preserve their
type and parameters verbatim rather than porting their runtime.
"""

import xml.etree.ElementTree as ET


class AdbError(Exception):
    pass


def _blend(el):
    bl = el.find("Blend")
    if bl is None:
        return {}
    def _num(v):
        try:
            return int(v)
        except ValueError:
            try:
                return float(v)
            except ValueError:
                return v
    return {k: _num(v) for k, v in bl.attrib.items()}


def parse_adb(data):
    """bytes/str -> dict describing the animation database."""
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise AdbError("not valid adb xml: %s" % e)
    if root.tag != "AnimDB":
        raise AdbError("root is %s, not AnimDB" % root.tag)

    out = {
        "fragdef": root.get("FragDef"),
        "tagdef": root.get("TagDef"),
        "categories": {},
        "subadbs": [],
    }
    fl = root.find("FragmentList")
    if fl is not None:
        for cat in fl:
            frags = []
            for fr in cat.findall("Fragment"):
                rec = {
                    "tags": fr.get("Tags", ""),
                    "blendOut": float(fr.get("BlendOutDuration", 0)),
                    "anims": [],
                    "procs": [],
                }
                for al in fr.findall("AnimLayer"):
                    for an in al.findall("Animation"):
                        rec["anims"].append({
                            "name": an.get("name"),
                            "blend": _blend(al),
                            "speed": float(an.get("speed", 1)),
                        })
                for pl in fr.findall("ProcLayer"):
                    blend = _blend(pl)
                    for pr in pl.findall("Procedural"):
                        params = {}
                        pp = pr.find("ProceduralParams")
                        if pp is not None:
                            for p in pp:
                                params[p.tag] = p.get("value")
                        rec["procs"].append({
                            "type": pr.get("type", ""),
                            "context": pr.get("contextType", ""),
                            "blend": blend, "params": params,
                        })
                frags.append(rec)
            out["categories"][cat.tag] = frags
    subs = root.find("SubADBs")
    if subs is not None:
        for s in subs.findall("SubADB"):
            out["subadbs"].append(dict(s.attrib))
    return out


def animation_refs(parsed):
    """Flat set of animation clip names referenced by the database."""
    refs = set()
    for frags in parsed["categories"].values():
        for fr in frags:
            for an in fr["anims"]:
                if an["name"]:
                    refs.add(an["name"])
    return refs
