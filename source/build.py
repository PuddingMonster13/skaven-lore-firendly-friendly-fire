"""Builds the mod packs.

    python build.py <out_dir> [--debug]

Writes into <out_dir>:
  skaven_lore_friendly_fire.pack          the mod (what goes to the Workshop): battle script, main menu check, MCT settings
  release.battle.lua, debug.battle.lua, frontend.lua    the filled scripts, for mocktest.py
Only with --debug, for hunting a problem (never upload, remove from the game folder afterwards):
  !skaven_lore_friendly_fire_debug.pack   test add-on: the same battle script WITH the diagnostics (lines marked --@debug
                                     in battle.lua.tpl). Enabled together with the mod it wins, its name sorts first.

Sources next to this file: battle.lua.tpl, frontend.lua.tpl, gamecode.inc.lua (shared block, put into both scripts),
mct_settings.lua, cave.py (machine code and patterns).
"""
import os
import re
import struct
import sys

import cave

VERSION = '0.9'  # set by the user on 2026-10-13: do not change it unless the user says so
HERE = os.path.dirname(os.path.abspath(__file__))
BATTLE_PATH = 'script/battle/mod/skaven_lore_friendly_fire.lua'
FRONTEND_PATH = 'script/frontend/mod/skaven_lore_friendly_fire_check.lua'
MCT_PATH = 'script/mct/settings/skaven_lore_friendly_fire.lua'


def lua_bytes(b):
    return ''.join('\\%03d' % c for c in b)


VALUES = {
    'VERSION': VERSION,
    'P_SITE': cave.P_SITE, 'SITE_OFF': cave.SITE_OFF,
    'P_RET': cave.P_RET, 'RET_OFF': cave.RET_OFF,
    'P_UID': cave.P_UID, 'UID_OFF': cave.UID_OFF,
    'AT_SITE': lua_bytes(cave.EXPECT_AT_SITE), 'AT_RET': lua_bytes(cave.EXPECT_AT_RET),
    'CAVE_A': lua_bytes(cave.CAVE_A), 'CAVE_B': lua_bytes(cave.CAVE_B), 'CAVE_C': lua_bytes(cave.CAVE_C),
    'TABLE_SIZE': cave.TABLE_SIZE, 'OFF_ENABLE': cave.OFF_ENABLE, 'OFF_ALL': cave.OFF_ALL, 'OFF_COUNT': cave.OFF_COUNT,
    'OFF_SHOOTERS': cave.OFF_SHOOTERS, 'OFF_BLOCKERS': cave.OFF_BLOCKERS,
    'MAX_SHOOTERS': cave.MAX_SHOOTERS, 'MAX_BLOCKERS': cave.MAX_BLOCKERS,
}


def strip_debug(lua):
    """Removes '--@debug-begin' ... '--@debug-end' blocks and single lines ending in '--@debug'."""
    out, skipping = [], False
    for line in lua.split('\n'):
        mark = line.strip()
        if mark == '--@debug-begin':
            assert not skipping
            skipping = True
        elif mark == '--@debug-end':
            assert skipping
            skipping = False
        elif not skipping and not line.rstrip().endswith('--@debug'):
            out.append(line)
    assert not skipping
    lua = '\n'.join(out)
    assert '@debug' not in lua and 'debug_state' not in lua and 'io.open' not in lua
    return lua


def fill(template, debug=True):
    lua = open(os.path.join(HERE, template), encoding='utf8').read()
    assert lua.count('--GAMECODE--') == 1, template
    lua = lua.replace('--GAMECODE--', open(os.path.join(HERE, 'gamecode.inc.lua'), encoding='utf8').read().rstrip())
    if not debug:
        lua = strip_debug(lua)
    for name, value in VALUES.items():
        lua = lua.replace('--%s--' % name, str(value))
    left = re.findall(r'--[A-Z_0-9]+--', lua)
    assert not left, (template, left)
    return lua.encode('utf8')


def write_pack(path, files):
    idx = b''
    data = b''
    for name in sorted(files):
        idx += struct.pack('<I', len(files[name])) + b'\0' + name.replace('/', chr(92)).encode('utf8') + b'\0'
        data += files[name]
    with open(path, 'wb') as f:
        f.write(b'PFH5' + struct.pack('<6I', 3, 0, 0, len(files), len(idx), 0) + idx + data)
    print('%s  %d bytes  %s' % (os.path.basename(path), os.path.getsize(path), ', '.join(sorted(files))))


def build(out_dir, with_debug_pack=False):
    release = fill('battle.lua.tpl', debug=False)
    debug = fill('battle.lua.tpl', debug=True)
    frontend = fill('frontend.lua.tpl')
    mct = open(os.path.join(HERE, 'mct_settings.lua'), 'rb').read()
    print('version', VERSION)
    write_pack(os.path.join(out_dir, 'skaven_lore_friendly_fire.pack'), {BATTLE_PATH: release, FRONTEND_PATH: frontend, MCT_PATH: mct})
    if with_debug_pack:
        write_pack(os.path.join(out_dir, '!skaven_lore_friendly_fire_debug.pack'), {BATTLE_PATH: debug})
    for name, content in (('release.battle.lua', release), ('debug.battle.lua', debug), ('frontend.lua', frontend)):
        with open(os.path.join(out_dir, name), 'wb') as f:
            f.write(content)
    print('battle script: release %d lines, test build %d lines' % (release.count(b'\n'), debug.count(b'\n')))


if __name__ == '__main__':
    build(sys.argv[1], with_debug_pack='--debug' in sys.argv[2:])
