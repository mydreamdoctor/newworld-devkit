"""Convert a parsed New World .adb into an O3DE EMotionFX .animgraph.

Mannequin categories map to animgraph states: each category becomes an
AnimGraphMotionNode playing the first animation of its first fragment.
Fragment selection rules (tags, priorities, blends) are a New-World
Mannequin concept with no EMotionFX equivalent yet — itemized as a gap.

The emitted XML mirrors the AZ ObjectStream layout of the EMotionFX test
assets; motion ids are the .caf basenames, resolved by the engine's
motion library.
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adb  # noqa: E402

_T = ('<Class name="{name}" field="{field}" version="{ver}" '
      'type="{typ}">')
_TV = ('<Class name="{name}" field="{field}" value="{val}" '
       'type="{typ}"/>')

_STR = '{03AAAB3F-5C47-5A66-9EBC-D5FA4DB353C9}'
_INT = '{72039442-EB38-4D42-A1AD-CB68F7E0EEF6}'
_U64 = '{D6597933-47CD-4FC8-B911-63F3E2B0993A}'
_BOOL = '{A0CA880C-AFE4-43CB-926C-59AC48496112}'
_UINT = '{43DA906B-7DEF-4CA8-9790-854106D3F983}'
_FLOAT = '{EA2C3E90-AFBE-44D4-A90D-FAAF79BAF93D}'
_U8 = '{72B9409A-7D1A-4831-9CFE-FCB3FADD3426}'


def _uid(name):
    return struct_u64(name)


def struct_u64(name):
    return int.from_bytes(hashlib.sha1(name.encode()).digest()[:8], 'little')


def _motion_node(name, motion_id, x, y):
    uid = struct_u64(name)
    s = []
    s.append('<Class name="AnimGraphMotionNode" field="element" version="3" '
             'type="{B8B8AAE6-E532-4BF8-898F-3D40AA41BC82}">')
    s.append('\t<Class name="AnimGraphNode" field="BaseClass1" version="1" '
             'type="{7F1C0E1D-4D32-4A6D-963C-20193EA28F95}">')
    s.append('\t\t<Class name="AnimGraphObject" field="BaseClass1" '
             'version="1" type="{532F5328-9AE3-4793-A7AA-8DEB0BAC9A9E}"/>')
    s.append('\t\t' + _TV.format(name='AZ::u64', field='id', val=uid,
                                 typ=_U64))
    s.append('\t\t' + _TV.format(name='AZStd::string', field='name',
                                 val=name, typ=_STR))
    s.append('\t\t' + _TV.format(name='int', field='posX', val=x, typ=_INT))
    s.append('\t\t' + _TV.format(name='int', field='posY', val=y, typ=_INT))
    s.append('\t\t' + _TV.format(name='unsigned int',
                                 field='visualizeColor', val=4292040122,
                                 typ=_UINT))
    for f in ('isDisabled', 'isCollapsed', 'isVisEnabled'):
        s.append('\t\t' + _TV.format(name='bool', field=f, val='false',
                                     typ=_BOOL))
    s.append('\t\t<Class name="AZStd::vector" field="childNodes" '
             'type="{E952D946-FF2C-5624-B72A-E02718B8CB09}"/>')
    s.append('\t\t<Class name="AZStd::vector" field="connections" '
             'type="{79810215-6320-5ED4-BA2C-CD3D5F2BFFE4}"/>')
    s.append('\t\t<Class name="TriggerActionSetup" field="actionSetup" '
             'version="1" type="{7B4E270C-2C7F-41C4-BFA5-FE6104B789BF}">')
    s.append('\t\t\t<Class name="AZStd::vector" field="actions" '
             'type="{51C7563D-C7C7-5975-9359-21A4869DE695}"/>')
    s.append('\t\t</Class>')
    s.append('\t</Class>')
    s.append('\t<Class name="AZStd::vector" field="motionIds" '
             'type="{134FD5CF-69EB-5AB1-8B2B-2AF461B7DFC5}">')
    s.append('\t\t<Class name="AZStd::pair" field="element" '
             'type="{E0838406-1905-5904-83F9-D2764B4402BC}">')
    s.append('\t\t\t' + _TV.format(name='AZStd::string', field='value1',
                                    val=motion_id, typ=_STR))
    s.append('\t\t\t' + _TV.format(name='float', field='value2',
                                    val='1.0000000', typ=_FLOAT))
    s.append('\t\t</Class>')
    s.append('\t</Class>')
    for f, v in (('loop', 'true'), ('retarget', 'true'),
                 ('reverse', 'false'), ('emitEvents', 'true'),
                 ('mirrorMotion', 'false'), ('motionExtraction', 'true'),
                 ('inPlace', 'false')):
        s.append('\t' + _TV.format(name='bool', field=f, val=v, typ=_BOOL))
    s.append('\t' + _TV.format(name='float', field='playSpeed',
                               val='1.0000000', typ=_FLOAT))
    s.append('\t' + _TV.format(name='unsigned char', field='indexMode',
                               val='0', typ=_U8))
    for f in ('nextMotionAfterLoop', 'rewindOnZeroWeight'):
        s.append('\t' + _TV.format(name='bool', field=f, val='false',
                                   typ=_BOOL))
    s.append('</Class>')
    return '\n'.join(s), uid


def convert(adb_bytes, dst, entry='Idle'):
    """adb_bytes -> .animgraph ObjectStream at dst. Returns (n_states,
    entry_state_name)."""
    parsed = adb.parse_adb(adb_bytes)
    states = []
    for cat, frags in parsed['categories'].items():
        anim = None
        for fr in frags:
            if fr['anims']:
                anim = fr['anims'][0]['name']
                break
        states.append((cat, anim or ''))

    nodes_xml, ids = [], {}
    cols = 6
    for i, (cat, anim) in enumerate(states):
        x, y = 290 + 320 * (i % cols), 260 + 160 * (i // cols)
        xml, uid = _motion_node(cat, anim, x, y)
        nodes_xml.append(xml)
        ids[cat] = uid
    entry_id = ids.get(entry) or next(iter(ids.values()))

    out = ['<ObjectStream version="3">',
           '\t<Class name="AnimGraph" version="1" '
           'type="{BD543125-CFEE-426C-B0AC-129F2A4C6BC8}">',
           '\t\t<Class name="GroupParameter" field="rootGroupParameter" '
           'version="1" type="{6B42666E-82D7-431E-807E-DA789C53AF05}">',
           '\t\t\t<Class name="Parameter" field="BaseClass1" version="1" '
           'type="{4AF0BAFC-98F8-4EA3-8946-4AD87D7F2A6C}">',
           '\t\t\t\t' + _TV.format(name='AZStd::string', field='name',
                                    val='', typ=_STR),
           '\t\t\t\t' + _TV.format(name='AZStd::string', field='description',
                                    val='', typ=_STR),
           '\t\t\t</Class>',
           '\t\t\t<Class name="AZStd::vector" field="childParameters" '
           'type="{496E6454-2F91-5CDC-9771-3B589F3F8FEB}"/>',
           '\t\t</Class>',
           '\t\t<Class name="AnimGraphStateMachine" '
           'field="rootStateMachine" version="1" '
           'type="{272E90D2-8A18-46AF-AD82-6A8B7EC508ED}">',
           '\t\t\t<Class name="AnimGraphNode" field="BaseClass1" '
           'version="1" type="{7F1C0E1D-4D32-4A6D-963C-20193EA28F95}">',
           '\t\t\t\t<Class name="AnimGraphObject" field="BaseClass1" '
           'version="1" type="{532F5328-9AE3-4793-A7AA-8DEB0BAC9A9E}"/>',
           '\t\t\t\t' + _TV.format(name='AZ::u64', field='id',
                                    val=struct_u64('__root__'), typ=_U64),
           '\t\t\t\t' + _TV.format(name='AZStd::string', field='name',
                                    val='Root', typ=_STR),
           '\t\t\t\t' + _TV.format(name='int', field='posX', val='0',
                                    typ=_INT),
           '\t\t\t\t' + _TV.format(name='int', field='posY', val='0',
                                    typ=_INT),
           '\t\t\t\t' + _TV.format(name='unsigned int',
                                    field='visualizeColor',
                                    val=4287660144, typ=_UINT),
           '\t\t\t\t' + _TV.format(name='bool', field='isDisabled',
                                    val='false', typ=_BOOL),
           '\t\t\t\t' + _TV.format(name='bool', field='isCollapsed',
                                    val='false', typ=_BOOL),
           '\t\t\t\t' + _TV.format(name='bool', field='isVisEnabled',
                                    val='false', typ=_BOOL),
           '\t\t\t\t<Class name="AZStd::vector" field="childNodes" '
           'type="{E952D946-FF2C-5624-B72A-E02718B8CB09}">',
           '\n'.join(nodes_xml),
           '\t\t\t\t</Class>',
           '\t\t\t\t<Class name="AZStd::vector" field="connections" '
           'type="{79810215-6320-5ED4-BA2C-CD3D5F2BFFE4}"/>',
           '\t\t\t\t<Class name="TriggerActionSetup" field="actionSetup" '
           'version="1" type="{7B4E270C-2C7F-41C4-BFA5-FE6104B789BF}">',
           '\t\t\t\t\t<Class name="AZStd::vector" field="actions" '
           'type="{51C7563D-C7C7-5975-9359-21A4869DE695}"/>',
           '\t\t\t\t</Class>',
           '\t\t\t</Class>',
           '\t\t\t' + _TV.format(name='AZ::u64', field='entryStateId',
                                  val=entry_id, typ=_U64),
           '\t\t\t<Class name="AZStd::vector" field="transitions" '
           'type="{7BE4AF47-DDD5-5B41-9BE0-6739C8A2694E}"/>',
           '\t\t\t' + _TV.format(name='bool', field='alwaysStartInEntryState',
                                  val='true', typ=_BOOL),
           '\t\t</Class>',
           '\t\t<Class name="AZStd::vector" field="nodeGroups" '
           'type="{9A7148E6-1DCA-5BDA-80D7-5FF35D43170E}"/>',
           '\t\t<Class name="AnimGraphGameControllerSettings" '
           'field="gameControllerSettings" version="1" '
           'type="{05DF1B3B-2073-4E6D-B5B6-7B87F46CCCB7}">',
           '\t\t\t' + _TV.format(name='unsigned int',
                                  field='activePresetIndex',
                                  val=4294967295, typ=_UINT),
           '\t\t\t<Class name="AZStd::vector" field="presets" '
           'type="{7EF271EC-720F-5899-B522-39F46AEC02F1}"/>',
           '\t\t</Class>',
           '\t\t' + _TV.format(name='bool', field='retarget', val='false',
                               typ=_BOOL),
           '\t</Class>',
           '</ObjectStream>', '']
    with open(dst, 'w') as f:
        f.write('\n'.join(out))
    return len(states), entry if entry in ids else states[0][0]


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, 'rb') as f:
        n, e = convert(f.read(), dst)
    print('%s -> %s (%d states, entry %s)' % (src, dst, n, e))
