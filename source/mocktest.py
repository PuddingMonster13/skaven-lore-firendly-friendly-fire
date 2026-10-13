"""Offline test of everything build.py produced (Lua 5.1 through lupa, no game needed).

    python mocktest.py <out_dir of build.py>      -> must end with ALL PASS

The battle script (release build and test build) runs against a fake memreader Plus and fake armies. The table it
fills is then handed to the REAL cave machine code (run natively in this process) to check the final decisions end to
end. The main menu check runs against a fake UI, the MCT settings file against a fake MCT.
"""
import ctypes
import os
import struct
import sys
import tempfile

import lupa.lua51 as lupa

import cave

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(sys.argv[1])
SCRIPTS = {name: open(os.path.join(OUT, name), encoding='utf8').read() for name in ('release.battle.lua', 'debug.battle.lua', 'frontend.lua')}
MCT = open(os.path.join(HERE, 'mct_settings.lua'), encoding='utf8').read()
LOG_NAME = 'skaven_lore_friendly_fire_log.txt'

MOCK = r'''
SITE, RET, UID, FUNC = 0x143159819 + SITE_OFF, 0x143159cfa + RET_OFF, 0x142f169c3 + UID_OFF, 0x1431597a0
UID_FIELD = 0x3ea0
UNIT_AT = 8
mem, ptrs, caves, logs = {}, {}, {}, {}
next_alloc = 0x20000000000
pattern_counts = {}
function P(addr) local p = ptrs[addr]; if not p then p = { addr = addr, is_ptr = true }; ptrs[addr] = p end; return p end
local function put(addr, bytes) for i = 1, #bytes do mem[addr + i - 1] = string.byte(bytes, i) end end
local function get(addr, n) local t = {}; for i = 0, n - 1 do t[#t + 1] = string.char(mem[addr + i] or 0) end; return table.concat(t) end
local function le(value, n) local t = {}; for i = 1, n do t[i] = string.char(value % 256); value = math.floor(value / 256) end; return table.concat(t) end
local function num(addr, n) local v = 0; for i = n - 1, 0, -1 do v = v * 256 + (mem[addr + i] or 0) end; return v end
function alloc_block(n) local a = next_alloc; next_alloc = next_alloc + math.ceil(n / 16) * 16 + 16; return a end
put(SITE, AT_SITE); put(RET, AT_RET); put(UID, le(UID_FIELD, 4))

function new_mr()
	local mr = { plus_version = '0.10.0-mock' }
	mr.add = function(p, n) return P(p.addr + n) end
	mr.is_null = function(p) return p.addr == 0 end
	mr.tostring = function(p) return string.format('%012X', p.addr) end
	mr.uint32 = function(v) return { u32 = v } end
	mr.read = function(p, off, n) return get(p.addr + off, n) end
	mr.read_original = mr.read
	mr.read_pointer = function(p, off) return P(num(p.addr + (off or 0), 8)) end
	mr.read_uint32 = function(p, off) return num(p.addr + (off or 0), 4) end
	mr.write = function(p, off, v)
		if type(v) == 'string' then put(p.addr + off, v)
		elseif v.is_ptr then put(p.addr + off, le(v.addr, 8))
		elseif v.u32 then put(p.addr + off, le(v.u32, 4))
		else error('mock write: unsupported value') end
	end
	mr.find_pattern = function(pattern)
		local address
		if pattern == P_SITE then address = SITE - SITE_OFF elseif pattern == P_RET then address = RET - RET_OFF elseif pattern == P_UID then address = UID - UID_OFF end
		local count = pattern_counts[pattern] or (address and 1 or 0)
		if count == 0 then return nil, 0 end
		return P(address), count
	end
	mr.function_start = function(p) if p.addr >= FUNC and p.addr < FUNC + 0x700 then return P(FUNC) end return nil end
	mr.hook_info = function(p) return caves[p.addr] end
	mr.code_cave = function(p, bytes)
		if caves[p.addr] then error('refused: the address already has a hook') end
		local a = alloc_block(#bytes); put(a, bytes)
		caves[p.addr] = { kind = 'cave', cave = P(a), size = #bytes }
		return P(a)
	end
	mr.game_alloc = function(n) return P(alloc_block(n)) end
	mr.alloc = mr.game_alloc
	mr.ud_topointer = function(unit) return P(unit._iface) end
	return mr
end

-- fake battle ------------------------------------------------------------------------------------------------------
local uid_counter = 1000
function new_unit(key, ammo, break_id)
	uid_counter = uid_counter + 1
	local iface, obj = alloc_block(64), alloc_block(UID_FIELD + 16)
	put(iface + UNIT_AT, le(obj, 8)); put(obj + UID_FIELD, le(uid_counter, 4))
	local unit = { _iface = iface, _obj = obj, _key = key, _uid = uid_counter + (break_id and 1 or 0), _ammo = ammo or 0 }
	function unit:type() return self._key end
	function unit:unique_ui_id() return self._uid end
	function unit:starting_ammo() return self._ammo end
	function unit:is_infantry() return string.find(self._key, '_inf_', 1, true) ~= nil end
	return unit
end
local function collection(list) return { count = function() return #list end, item = function(_, i) return list[i] end } end
function new_army(subculture, units, reinforcements)
	local army = { _units = units }
	function army:subculture_key() return subculture end
	function army:units() return collection(self._units) end
	function army:num_reinforcement_units() return reinforcements and 1 or 0 end
	function army:get_reinforcement_units(i) return collection(reinforcements) end
	return army
end
function new_battle(alliances)
	local callbacks = { phases = {}, timers = {} }
	local battle = {}
	function battle:alliances()
		if alliances == 'broken' then error('armies not ready') end
		local list = {}
		for i, armies in ipairs(alliances) do list[i] = { armies = function() return collection(armies) end } end
		return collection(list)
	end
	bm = { battle = battle, _cb = callbacks }
	function bm:register_phase_change_callback(phase, f) callbacks.phases[phase] = callbacks.phases[phase] or {}; table.insert(callbacks.phases[phase], f) end
	function bm:repeat_callback(f, ms, name) callbacks.timers[name] = f end
	function bm:remove_callback(name) callbacks.timers[name] = nil end
	function phase(name) for _, f in ipairs(callbacks.phases[name] or {}) do f() end end
	function tick() for _, f in pairs(callbacks.timers) do f() end end
	function set_alliances(a) alliances = a end
	function timer_count() local n = 0; for _ in pairs(callbacks.timers) do n = n + 1 end; return n end
end
function ModLog(text) logs[#logs + 1] = text end
function log_text() return table.concat(logs, '\n') end
function log_lines() return #logs end
function clear_logs() logs = {} end

-- fake MCT -----------------------------------------------------------------------------------------------------------
mct_values = nil
function install_mct(values)
	mct_values = values
	if not values then get_mct = nil return end
	get_mct = function()
		return { get_mod_by_key = function(_, key)
			if key ~= 'skaven_lore_friendly_fire' then return nil end
			return { get_option_by_key = function(_, k)
				if mct_values[k] == nil then return nil end
				return { get_finalized_setting = function() return mct_values[k] end }
			end }
		end }
	end
end
function table_addr() local c = caves[SITE]; if not c then return nil end; return num(c.cave.addr + CAVE_A_LEN, 8) end
function cave_bytes() local c = caves[SITE]; return get(c.cave.addr, c.size) end
function table_bytes() return get(table_addr(), TABLE_SIZE) end
function read_u32(addr) return num(addr, 4) end
'''

MCT_MOCK = r'''
local options, listeners = {}, {}
local order = {}
local function new_option(mod_key, key)
	local o = { _key = key, _selected = nil }
	function o:set_default_value(v) self._default = v; self._selected = v end
	function o:set_text(t) self._text = t end
	function o:set_tooltip_text(t) self._tip = t end
	function o:get_key() return self._key end
	function o:get_mod_key() return mod_key end
	function o:get_selected_setting() return self._selected end
	function o:set_selected_setting(v)
		self._selected = v
		for _, l in pairs(listeners) do
			local context = { option = function() return o end, setting = function() return v end }
			if l.condition == true or l.condition(context) then l.callback(context) end
		end
	end
	return o
end
function get_mct()
	return { register_mod = function(_, mod_key)
		local m = {}
		function m:set_title(t) mct_title = t end
		function m:set_author(a) end
		function m:set_description(d) end
		function m:add_new_section(k, t) mct_section = t end
		function m:add_new_option(key, kind) assert(kind == 'checkbox'); local o = new_option(mod_key, key); options[key] = o; order[#order + 1] = key; return o end
		function m:get_option_by_key(key) return options[key] end
		return m
	end }
end
core = {}
function core:add_listener(name, event, condition, callback, persistent) assert(event == 'MctOptionSelectedSettingSet'); listeners[name] = { condition = condition, callback = callback } end
function core:remove_listener(name) listeners[name] = nil end
function opt(key) return options[key] end
function option_order() return table.concat(order, ',') end
function foreign_option_event() -- an option of another mod with the same key must not move our boxes
	local o = new_option('some_other_mod', 'sst_all')
	o:set_selected_setting(true)
end
function broken_event() for _, l in pairs(listeners) do l.callback({ option = function() error('boom') end }) end end
'''

UI_MOCK = r'''
-- fake main menu: core, UI components, saved flags (svr survives "returning to the main menu", not a game restart)
svr = svr or {}
boxes, listeners, timers, ui_callbacks = {}, {}, {}, {}
frontend = true
local function component(name)
	local c = { _name = name, _children = {}, _visible = true }
	function c:SetStateText(text) self._text = text end
	function c:SetVisible(v) self._visible = v end
	function c:PropagatePriority(n) self._priority = n end
	function c:LockPriority() self._locked = true end
	function c:UnLockPriority() self._locked = false end
	function c:Destroy() boxes[self._name] = nil; self._destroyed = true end
	return c
end
local root = {}
function root:CreateComponent(name, layout)
	assert(layout == 'UI/Common UI/dialogue_box')
	local box = component(name)
	for _, child in ipairs({ 'DY_text', 'both_group', 'ok_group' }) do box._children[child] = component(child) end
	boxes[name] = box
	return box
end
function UIComponent(x) return x end
function find_uicomponent(parent, name)
	if parent == root then return boxes[name] end
	return parent._children[name]
end
function uicomponent_descended_from(c, name) return c._inside == name end
core = {}
function core:is_frontend() return frontend end
function core:get_ui_root() return root end
function core:add_ui_created_callback(f) ui_callbacks[#ui_callbacks + 1] = f end
function core:get_tm() return { real_callback = function(_, f, ms) timers[#timers + 1] = f end } end
function core:svr_load_bool(k) return svr[k] == true end
function core:svr_save_bool(k, v) svr[k] = v end
function core:add_listener(name, event, condition, callback, persistent) assert(event == 'ComponentLClickUp'); listeners[name] = { condition = condition, callback = callback } end
function core:remove_listener(name) listeners[name] = nil end
function ui_created() for _, f in ipairs(ui_callbacks) do f() end; ui_callbacks = {}; local t = timers; timers = {}; for _, f in ipairs(t) do f() end end
function click(inside)
	local context = { component = { _inside = inside }, string = 'button_tick' }
	for _, l in pairs(listeners) do if l.condition(context) then l.callback(context) end end
end
function box() return boxes['skaven_lore_friendly_fire_alert'] end
function box_text() local b = box(); return b and b._children.DY_text._text end
function listener_count() local n = 0; for _ in pairs(listeners) do n = n + 1 end; return n end
'''

STANDARD = r'''
ratling  = new_unit('wh2_dlc12_skv_inf_ratling_gun_0', 30)
jezzail  = new_unit('wh2_dlc12_skv_inf_warplock_jezzails_0', 20)
modgun   = new_unit('modded_new_gunners', 25)                      -- unknown key, has ammo, in a Skaven army
slaves   = new_unit('wh2_main_skv_inf_skavenslaves_0', 0)
slaves2  = new_unit('wh2_main_skv_inf_skavenslaves_0', 0)
slingers = new_unit('wh2_main_skv_inf_skavenslave_slingers_0', 15) -- expendable AND a shooter
pusbags  = new_unit('wh3_dlc29_skv_inf_pusbags', 0)
clanrats = new_unit('wh2_main_skv_inf_clanrat_spearmen_1', 0)
vermin   = new_unit('wh2_main_skv_inf_stormvermin_0', 0)
ogres    = new_unit('wh2_main_skv_mon_rat_ogres', 0)
mutant   = new_unit('wh2_dlc16_skv_mon_rat_ogre_mutant', 0)        -- single monster, not "monster infantry"
fiends   = new_unit('wh3_dlc29_skv_mon_stormfiend_ratling_cannons', 40)
warlord  = new_unit('wh2_main_skv_cha_warlord_0', 0)
monks    = new_unit('wh2_main_skv_inf_plague_monks', 0)
enemy_gun   = new_unit('wh_main_emp_inf_handgunners', 20)
enemy_sword = new_unit('wh_main_emp_inf_swordsmen', 0)
enemy_slaves = new_unit('wh2_main_skv_inf_skavenslaves_0', 0)     -- Skaven slaves on the other side
enemy_rat_gun = new_unit('wh2_dlc12_skv_inf_ratling_gun_0', 30)
skaven_army = new_army('wh2_main_sc_skv_skaven', { ratling, jezzail, modgun, slaves, slaves2, slingers, pusbags, clanrats, vermin, ogres, mutant, fiends, warlord, monks })
empire_army = new_army('wh_main_sc_emp_empire', { enemy_gun, enemy_sword })
enemy_skaven = new_army('wh2_main_sc_skv_skaven', { enemy_slaves, enemy_rat_gun })
'''

# --- native cave ---------------------------------------------------------------------------------------------------
k32 = ctypes.windll.kernel32
k32.VirtualAlloc.restype = ctypes.c_void_p
k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
PRE = bytes.fromhex('57' '4156' '4989ce' '4889d7')  # push rdi; push r14; mov r14,rcx; mov rdi,rdx
FALL = bytes.fromhex('b801000000' '415e' '5f' 'c3')  # game goes on with its check
RET0 = bytes.fromhex('31c0' '415e' '5f' 'c3')  # "no hit"
native_table = (ctypes.c_ubyte * cave.TABLE_SIZE)()
native_mem = k32.VirtualAlloc(None, 0x1000, 0x3000, 0x40)
BLOCKED, THROUGH = 1, 0


def native_decider(g):
    """Takes the cave bytes the SCRIPT installed (not the builder's), re-points table and exit, returns run(shooter, blocker)."""
    installed = bytes(ord(c) for c in g.cave_bytes())
    a, b = len(cave.CAVE_A), len(cave.CAVE_B)
    assert installed[:a] == cave.CAVE_A and installed[a + 8:a + 8 + b] == cave.CAVE_B and installed[a + 16 + b:] == cave.CAVE_C
    assert struct.unpack('<Q', installed[a + 8 + b:a + 16 + b])[0] == g.RET, 'cave exit is not the no-hit address'
    ret0 = native_mem + len(PRE) + len(installed) + len(FALL)
    code = PRE + installed[:a] + struct.pack('<Q', ctypes.addressof(native_table)) + installed[a + 8:a + 8 + b] + struct.pack('<Q', ret0) + installed[a + 16 + b:] + FALL + RET0
    ctypes.memmove(native_mem, code, len(code))
    tb = bytes(ord(c) for c in g.table_bytes())
    ctypes.memmove(native_table, tb, len(tb))
    return ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint64)(native_mem)


checks = 0


def expect(name, got, want=True):
    global checks
    checks += 1
    assert got == want, '%s: got %r, want %r' % (name, got, want)


def fresh():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True, encoding='latin-1')
    g = lua.globals()
    g.SITE_OFF, g.RET_OFF, g.UID_OFF = cave.SITE_OFF, cave.RET_OFF, cave.UID_OFF
    g.P_SITE, g.P_RET, g.P_UID = cave.P_SITE, cave.P_RET, cave.P_UID
    g.AT_SITE = cave.EXPECT_AT_SITE.decode('latin-1')
    g.AT_RET = cave.EXPECT_AT_RET.decode('latin-1')
    g.CAVE_A_LEN, g.TABLE_SIZE = len(cave.CAVE_A), cave.TABLE_SIZE
    lua.execute(MOCK)
    return lua, g


def table_state(g):
    t = g.table_addr()
    return g.read_u32(t + cave.OFF_ENABLE), g.read_u32(t + cave.OFF_ALL)


def obj(g, name):
    return g[name]['_obj']


def test_battle_script(flavour):
    script = SCRIPTS[flavour + '.battle.lua']
    debug = flavour == 'debug'
    tag = flavour + ' '
    os.chdir(tempfile.mkdtemp(prefix='sst_mock_'))  # the test build writes its log file into the working directory

    def load(lua, deploy=True):
        """Runs the battle script as the game does while a battle loads, then (normally) starts the deployment phase."""
        lua.execute('clear_logs()')
        lua.execute(script)
        if deploy:
            lua.execute('phase("Deployment")')

    def said(g, text, debug_only=False):
        """Text is in the log; for a debug-only line: there in the test build and absent in the release build."""
        return (text in g.log_text()) == (debug or not debug_only)

    # the release build has no diagnostics code at all
    if not debug:
        for word in ('io.open', 'os.date', 'TEST BUILD', '@debug', 'key_counts', 'OFF_COUNT)'):
            expect(tag + 'no %s in the release script' % word, word in script, False)

    # 1. memreader missing
    lua, g = fresh()
    lua.execute(STANDARD + 'new_battle({ { skaven_army }, { empire_army } })')
    load(lua)
    expect(tag + 'no memreader: says so', said(g, 'OFF for this battle: memreader Plus is not loaded'))
    expect(tag + 'no memreader: no cave', g.table_addr(), None)
    expect(tag + 'no memreader: no timers', g.timer_count(), 0)

    # 2. game code not found / found twice
    for count in (0, 2):
        lua, g = fresh()
        lua.execute(STANDARD + 'new_battle({ { skaven_army }, { empire_army } }); _G.memreader_plus = new_mr()')
        g.pattern_counts[cave.P_SITE] = count
        load(lua)
        expect(tag + 'pattern count %d: off' % count, said(g, 'OFF for this battle') and said(g, 'found %d times, expected 1' % count))
        expect(tag + 'pattern count %d: no cave' % count, g.table_addr(), None)
        expect(tag + 'pattern count %d: no timers' % count, g.timer_count(), 0)

    # 3. no Skaven in the battle: the game code is not touched at all
    lua, g = fresh()
    lua.execute(STANDARD + 'new_battle({ { empire_army }, { new_army("wh_main_sc_emp_empire", { new_unit("wh_main_emp_inf_spearmen_0", 0) }) } }); _G.memreader_plus = new_mr()')
    load(lua)
    lua.execute('phase("Deployment"); phase("Deployed"); tick(); tick()')
    expect(tag + 'no skaven: no cave', g.table_addr(), None)
    expect(tag + 'no skaven: not off', 'OFF for this battle' in g.log_text(), False)
    if not debug:
        expect(tag + 'no skaven: release build logs nothing', g.log_lines(), 0)

    # 4. standard battle, default settings (no MCT)
    lua, g = fresh()
    lua.execute(STANDARD + 'new_battle({ { skaven_army }, { empire_army, enemy_skaven } }); _G.memreader_plus = new_mr()')
    load(lua, deploy=False)
    expect(tag + 'default: nothing is installed while the battle loads', g.table_addr(), None)
    lua.execute('phase("Deployment")')
    expect(tag + 'default: no failure', 'OFF for this battle' in g.log_text(), False)
    expect(tag + 'default: enabled, not all', table_state(g), (1, 0))
    expect(tag + 'default: ON line', said(g, 'ON: 6 Skaven shooters, shooting through 5 units'))
    run = native_decider(g)
    S = lambda n: obj(g, n)
    for shooter in ('ratling', 'jezzail', 'modgun', 'fiends', 'slingers'):
        for blocker in ('slaves', 'slaves2', 'pusbags'):
            expect(tag + 'default: %s through %s' % (shooter, blocker), run(S(shooter), S(blocker)), THROUGH)
    expect(tag + 'default: ratling through slave slingers', run(S('ratling'), S('slingers')), THROUGH)
    for blocker in ('clanrats', 'vermin', 'ogres', 'mutant', 'warlord', 'monks', 'jezzail', 'fiends'):
        expect(tag + 'default: ratling blocked by %s' % blocker, run(S('ratling'), S(blocker)), BLOCKED)
    expect(tag + 'default: empire gun blocked by slaves', run(S('enemy_gun'), S('slaves')), BLOCKED)
    expect(tag + 'default: empire gun blocked by own swordsmen', run(S('enemy_gun'), S('enemy_sword')), BLOCKED)
    expect(tag + 'default: enemy ratling through enemy slaves', run(S('enemy_rat_gun'), S('enemy_slaves')), THROUGH)
    expect(tag + 'default: non-shooter slaves as shooter', run(S('slaves'), S('slaves2')), BLOCKED)
    expect(tag + 'default: blocker unknown', run(S('ratling'), 0), BLOCKED)
    lines_after_load = g.log_lines()
    lua.execute('phase("Deployment"); phase("Deployed"); for i = 1, 40 do tick() end')
    if not debug:
        expect(tag + 'release build: one line for the whole battle so far', (lines_after_load, g.log_lines()), (1, 1))

    # 5. settings from MCT, changed during the battle
    lua.execute('install_mct({ sst_expendable = true, sst_clanrats = true, sst_infantry = false, sst_monstrous = false, sst_all = false })')
    lua.execute('tick()')
    run = native_decider(g)
    expect(tag + 'clanrats on: through clanrats', run(S('ratling'), S('clanrats')), THROUGH)
    expect(tag + 'clanrats on: blocked by stormvermin', run(S('ratling'), S('vermin')), BLOCKED)
    lua.execute('install_mct({ sst_expendable = false, sst_clanrats = false, sst_infantry = true, sst_monstrous = true, sst_all = false }); tick()')
    run = native_decider(g)
    # "All infantry" covers every infantry unit, whatever the boxes of the single groups say
    for blocker in ('slaves', 'clanrats', 'vermin', 'monks', 'jezzail'):
        expect(tag + 'infantry+monstrous: through %s' % blocker, run(S('ratling'), S(blocker)), THROUGH)
    expect(tag + 'infantry+monstrous: blocked by the warlord (no infantry)', run(S('ratling'), S('warlord')), BLOCKED)
    expect(tag + 'infantry+monstrous: through rat ogres', run(S('ratling'), S('ogres')), THROUGH)
    expect(tag + 'infantry+monstrous: through stormfiends', run(S('jezzail'), S('fiends')), THROUGH)
    expect(tag + 'infantry+monstrous: blocked by the single rat ogre mutant', run(S('ratling'), S('mutant')), BLOCKED)
    lua.execute('install_mct({ sst_expendable = true, sst_clanrats = true, sst_infantry = true, sst_monstrous = true, sst_all = true }); tick()')
    expect(tag + 'all: flags', table_state(g), (1, 1))
    run = native_decider(g)
    for blocker in ('slaves', 'clanrats', 'warlord', 'monks', 'jezzail', 'mutant'):
        expect(tag + 'all: ratling through %s' % blocker, run(S('ratling'), S(blocker)), THROUGH)
    expect(tag + 'all: empire gun still blocked', run(S('enemy_gun'), S('enemy_sword')), BLOCKED)
    expect(tag + 'all: non-shooter still not a shooter', run(S('warlord'), S('slaves')), BLOCKED)
    lua.execute('install_mct({ sst_expendable = false, sst_clanrats = false, sst_infantry = false, sst_monstrous = false, sst_all = false }); tick()')
    expect(tag + 'everything unticked: disabled', table_state(g)[0], 0)
    run = native_decider(g)
    expect(tag + 'everything unticked: blocked', run(S('ratling'), S('slaves')), BLOCKED)
    lua.execute('install_mct({ sst_expendable = true, sst_clanrats = false, sst_infantry = false, sst_monstrous = false, sst_all = false }); tick()')
    expect(tag + 'ticked again: enabled', table_state(g), (1, 0))
    lua.execute('get_mct = function() error("mct broken") end; tick()')
    expect(tag + 'MCT broken: falls back to defaults, still on', table_state(g), (1, 0))
    lua.execute('install_mct({ sst_expendable = true })')

    # 6. a unit summoned later is picked up by the timer; a list that shrinks ends at the right place
    lua.execute('summoned = new_unit("wh2_main_skv_inf_skavenslave_spearmen_0_summoned", 0); table.insert(skaven_army._units, summoned)')
    run = native_decider(g)
    expect(tag + 'summon: not yet known', run(S('ratling'), S('summoned')), BLOCKED)
    lua.execute('tick()')
    run = native_decider(g)
    expect(tag + 'summon: known after refresh', run(S('ratling'), S('summoned')), THROUGH)
    lua.execute('table.remove(skaven_army._units)  table.remove(skaven_army._units, 4)  tick()')  # summoned and slaves gone
    run = native_decider(g)
    expect(tag + 'shrink: removed unit no longer listed', run(S('ratling'), S('summoned')), BLOCKED)
    expect(tag + 'shrink: removed unit no longer listed 2', run(S('ratling'), S('slaves')), BLOCKED)
    expect(tag + 'shrink: others still listed', run(S('ratling'), S('pusbags')), THROUGH)

    # 7. battle ends
    lua.execute('phase("Complete")')
    expect(tag + 'complete: disabled', table_state(g)[0], 0)
    expect(tag + 'complete: timer removed', g.timer_count(), 0)
    lua.execute('install_mct(nil)')
    if debug:
        text = open(LOG_NAME, encoding='latin-1').read()
        for part in ('TEST BUILD', 'code cave installed', 'Skaven shooters (6): 2x wh2_dlc12_skv_inf_ratling_gun_0', 'shoot through (5): 3x wh2_main_skv_inf_skavenslaves_0',
                     'sst_expendable=true', 'shoot through: every friendly unit', 'nothing to do', 'line-of-fire checks answered "shoot through" so far: 0', 'battle complete'):
            expect(tag + 'log file has: ' + part, part in text)
    else:
        expect(tag + 'release build writes no log file', os.path.exists(LOG_NAME), False)
        expect(tag + 'release build: still one line for the whole battle', g.log_lines(), 1)

    # 8. next battle in the same game session: cave is reused, old units are forgotten first
    old_table = g.table_addr()
    old_ratling = S('ratling')
    lua.execute(STANDARD + 'new_battle({ { empire_army }, { skaven_army } }); _G.memreader_plus = new_mr()')
    load(lua)
    expect(tag + 'second battle: same table', g.table_addr(), old_table)
    expect(tag + 'second battle: reuse noted', said(g, 'reusing it', debug_only=True))
    expect(tag + 'second battle: enabled', table_state(g), (1, 0))
    run = native_decider(g)
    expect(tag + 'second battle: new units work', run(S('ratling'), S('slaves')), THROUGH)
    expect(tag + 'second battle: old unit forgotten', run(old_ratling, S('slaves')), BLOCKED)

    # 9. third battle without Skaven: the old cave is switched off straight away
    lua.execute('new_battle({ { empire_army }, { new_army("wh_main_sc_emp_empire", { new_unit("wh_main_emp_inf_spearmen_0", 0) }) } }); _G.memreader_plus = new_mr()')
    load(lua)
    expect(tag + 'third battle: disabled', table_state(g)[0], 0)

    # 9b. fourth battle: the game code is suddenly not found -> off, and the old cave must not stay on
    lua.execute(STANDARD + 'new_battle({ { skaven_army }, { empire_army } }); _G.memreader_plus = new_mr()')
    load(lua)
    expect(tag + 'fourth battle: on', table_state(g)[0], 1)
    lua.execute('phase("Complete")')

    # 10. a unit whose game object cannot be confirmed switches the mod off, the game code is never touched
    for name, setup in (('bad unit', STANDARD + 'bad = new_unit("wh2_main_skv_inf_skavenslaves_0", 0, true); table.insert(skaven_army._units, bad)'),
                        ('other layout', 'UNIT_AT = 0x10 ' + STANDARD)):
        lua, g = fresh()
        lua.execute(setup)
        lua.execute('new_battle({ { skaven_army }, { empire_army } }); _G.memreader_plus = new_mr()')
        load(lua)
        expect(tag + name + ': off', said(g, 'could not be confirmed') and said(g, 'OFF for this battle: Deployment'))
        lua.execute('tick(); phase("Deployed")')
        expect(tag + name + ': game code never touched', g.table_addr(), None)

    # 11. the armies are not looked at while the battle loads; without a deployment phase the timer starts the mod
    lua, g = fresh()
    lua.execute(STANDARD + 'new_battle("broken"); _G.memreader_plus = new_mr()')
    load(lua, deploy=False)
    expect(tag + 'early: not dead', 'OFF for this battle' in g.log_text(), False)
    lua.execute('set_alliances({ { skaven_army }, { empire_army } }); tick()')
    expect(tag + 'early: enabled by the timer', table_state(g), (1, 0))

    # 11b. everything unticked in MCT from the start: the game code is never touched
    lua, g = fresh()
    lua.execute(STANDARD + 'new_battle({ { skaven_army }, { empire_army } }); _G.memreader_plus = new_mr()')
    lua.execute('install_mct({ sst_expendable = false, sst_clanrats = false, sst_infantry = false, sst_monstrous = false, sst_all = false })')
    load(lua)
    lua.execute('phase("Deployed"); for i = 1, 5 do tick() end; phase("Complete")')
    expect(tag + 'all unticked: no cave', g.table_addr(), None)
    expect(tag + 'all unticked: not off', 'OFF for this battle' in g.log_text(), False)

    # 12. something else sits on the cave site
    lua, g = fresh()
    lua.execute(STANDARD + 'new_battle({ { skaven_army }, { empire_army } }); _G.memreader_plus = new_mr(); caves[SITE] = { kind = "site" }')
    load(lua)
    expect(tag + 'foreign hook: off', said(g, 'something else already hooks'))
    expect(tag + 'foreign hook: no timers', g.timer_count(), 0)

    # 13. memreader refuses the cave: off, nothing enabled
    lua, g = fresh()
    lua.execute(STANDARD + 'new_battle({ { skaven_army }, { empire_army } }); _G.memreader_plus = new_mr(); _G.memreader_plus.code_cave = function() error("refused: test") end')
    load(lua)
    lua.execute('phase("Deployment")')
    expect(tag + 'refused cave: off', said(g, 'OFF for this battle') and said(g, 'refused: test'))
    expect(tag + 'refused cave: nothing installed', g.table_addr(), None)

    # 14. a failure in the middle of a battle switches the table off
    lua, g = fresh()
    lua.execute(STANDARD + 'new_battle({ { skaven_army }, { empire_army } }); _G.memreader_plus = new_mr()')
    load(lua)
    expect(tag + 'mid-battle failure: on before', table_state(g)[0], 1)
    lua.execute('ratling.starting_ammo = function() error("api changed") end; tick()')
    expect(tag + 'mid-battle failure: off', said(g, 'OFF for this battle: refresh') and said(g, 'api changed'))
    expect(tag + 'mid-battle failure: disabled', table_state(g)[0], 0)
    lua.execute('ratling.starting_ammo = function() return 30 end; tick(); phase("Deployed")')
    expect(tag + 'mid-battle failure: stays disabled', table_state(g)[0], 0)

    # 15. reinforcement units
    lua, g = fresh()
    lua.execute(STANDARD + 'late = new_unit("wh2_main_skv_inf_skavenslaves_0", 0); skaven_army = new_army("wh2_main_sc_skv_skaven", { ratling }, { late })')
    lua.execute('new_battle({ { skaven_army }, { empire_army } }); _G.memreader_plus = new_mr()')
    load(lua)
    run = native_decider(g)
    expect(tag + 'reinforcements: listed', run(obj(g, 'ratling'), obj(g, 'late')), THROUGH)

    # 16. too many units: lists are cut, the table is never overrun
    lua, g = fresh()
    lua.execute('many = {}; for i = 1, 700 do many[#many + 1] = new_unit("wh2_main_skv_inf_skavenslave_slingers_0", 10) end')
    lua.execute('new_battle({ { new_army("wh2_main_sc_skv_skaven", many) } }); _G.memreader_plus = new_mr()')
    load(lua)
    expect(tag + 'many: enabled', table_state(g), (1, 0))
    tb = bytes(ord(c) for c in g.table_bytes())
    n_shooters = len([1 for i in range(cave.OFF_SHOOTERS, cave.OFF_BLOCKERS, 8) if tb[i:i + 8] != bytes(8)])
    n_blockers = len([1 for i in range(cave.OFF_BLOCKERS, 0x1000, 8) if tb[i:i + 8] != bytes(8)])
    expect(tag + 'many: shooter list capped', n_shooters, cave.MAX_SHOOTERS)
    expect(tag + 'many: blocker list capped', n_blockers, cave.MAX_BLOCKERS)
    expect(tag + 'many: zero slot before blocker list', tb[cave.OFF_BLOCKERS - 8:cave.OFF_BLOCKERS], bytes(8))
    expect(tag + 'many: nothing written past the lists', tb[0x1000 - 8:], bytes(cave.TABLE_SIZE - 0x1000 + 8))
    run = native_decider(g)
    expect(tag + 'many: works', run(g.many[1]['_obj'], g.many[2]['_obj']), THROUGH)
    expect(tag + 'many: beyond the cap keeps normal behaviour', run(g.many[700]['_obj'], g.many[1]['_obj']), BLOCKED)


def test_frontend_check():
    script = SCRIPTS['frontend.lua']

    def menu(setup=''):
        lua, g = fresh()
        lua.execute(UI_MOCK)
        lua.execute(setup)
        lua.execute('clear_logs()')
        lua.execute(script)
        return lua, g

    # game build fits: no message box, no log line, the game code is not touched
    lua, g = menu('_G.memreader_plus = new_mr()')
    expect('menu: nothing before the UI exists', g.box(), None)
    lua.execute('ui_created()')
    expect('menu fits: no box', g.box(), None)
    expect('menu fits: nothing logged', g.log_lines(), 0)
    expect('menu fits: no cave', g.table_addr(), None)
    expect('menu fits: no listener left', g.listener_count(), 0)

    # game build does not fit
    cases = {
        'not found': ('pattern_counts[P_SITE] = 0', 'found 0 times'),
        'found twice': ('pattern_counts[P_RET] = 2', 'found 2 times'),
        'uid not found': ('pattern_counts[P_UID] = 0', 'unit id code was found 0 times'),
    }
    for name, (setup, reason) in cases.items():
        lua, g = menu('_G.memreader_plus = new_mr(); ' + setup)
        lua.execute('ui_created()')
        text = g.box_text()
        expect('menu %s: box shown' % name, text is not None)
        expect('menu %s: says mismatch' % name, 'does not match this version of the game' in text and 'switched off' in text)
        expect('menu %s: gives the reason' % name, reason in text)
        expect('menu %s: names the version' % name, 'Skaven lore-firendly (no) friendly fire 0.' in text)
        expect('menu %s: ok group visible, both group hidden' % name, (g.box()['_children']['ok_group']['_visible'], g.box()['_children']['both_group']['_visible']), (True, False))
        expect('menu %s: no cave' % name, g.table_addr(), None)
        expect('menu %s: one log line' % name, g.log_lines(), 1)
    # click outside does nothing, click inside closes and cleans up
    lua.execute('click("something_else")')
    expect('menu: click outside keeps the box', g.box() is not None)
    lua.execute('click("skaven_lore_friendly_fire_alert")')
    expect('menu: click inside closes', g.box(), None)
    expect('menu: listener removed', g.listener_count(), 0)
    # back to the main menu in the same game session: logged again, not shown again
    lua.execute('clear_logs(); ui_callbacks = {}')
    lua.execute(script)
    lua.execute('ui_created()')
    expect('menu again: not shown twice', g.box(), None)
    expect('menu again: still logged', 'does not match this version of the game' in g.log_text())

    # memreader Plus missing / too old
    lua, g = menu('')
    lua.execute('ui_created()')
    expect('menu no memreader: box', 'needs the mod memreader Plus, which is not loaded' in (g.box_text() or ''))
    lua, g = menu('_G.memreader_plus = new_mr(); _G.memreader_plus.code_cave = nil')
    lua.execute('ui_created()')
    expect('menu old memreader: box', 'needs a newer memreader Plus' in (g.box_text() or '') and 'code_cave' in g.box_text())

    # the script does nothing outside the main menu
    lua, g = menu('frontend = false; pattern_counts[P_SITE] = 0; _G.memreader_plus = new_mr()')
    lua.execute('ui_created()')
    expect('not frontend: nothing', g.box(), None)

    # a broken UI must not raise out of the script
    lua, g = menu('pattern_counts[P_SITE] = 0; _G.memreader_plus = new_mr(); find_uicomponent = function() error("ui changed") end')
    lua.execute('ui_created()')
    expect('broken ui: error is logged, not raised', 'ui changed' in g.log_text())


def test_mct_settings():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    lua.execute(MCT_MOCK)
    lua.execute(MCT)
    expect('mct: title', g.mct_title, 'Skaven lore-firendly (no) friendly fire')
    expect('mct: section', g.mct_section, 'Shoot through')
    expect('mct: order', g.option_order(), 'sst_expendable,sst_clanrats,sst_infantry,sst_monstrous,sst_all')
    val = lambda k: g.opt(k)['_selected']
    others = ('sst_expendable', 'sst_clanrats', 'sst_infantry', 'sst_monstrous')
    expect('mct: defaults', [val(k) for k in others] + [val('sst_all')], [True, False, False, False, False])
    lua.execute('opt("sst_all"):set_selected_setting(true)')
    expect('mct: all ticks all', [val(k) for k in others] + [val('sst_all')], [True] * 5)
    lua.execute('opt("sst_clanrats"):set_selected_setting(false)')
    expect('mct: unticking one unticks All only', [val(k) for k in others] + [val('sst_all')], [True, False, True, True, False])
    lua.execute('opt("sst_clanrats"):set_selected_setting(true)')
    expect('mct: ticking the four does not tick All', val('sst_all'), False)
    lua.execute('opt("sst_all"):set_selected_setting(true); opt("sst_all"):set_selected_setting(false)')
    expect('mct: all unticks all', [val(k) for k in others] + [val('sst_all')], [False] * 5)
    lua.execute('foreign_option_event()')
    expect('mct: other mod with same option key is ignored', [val(k) for k in others], [False] * 4)
    lua.execute('broken_event()')  # must not raise
    lua.execute('opt("sst_all"):set_selected_setting(true)')
    expect('mct: still works after a broken event', [val(k) for k in others] + [val('sst_all')], [True] * 5)
    lua.execute(MCT)  # loaded a second time: no double listeners, still works
    lua.execute('opt("sst_all"):set_selected_setting(true)')
    expect('mct: reload', [val(k) for k in others] + [val('sst_all')], [True] * 5)


test_battle_script('release')
test_battle_script('debug')
test_frontend_check()
test_mct_settings()
print('%d checks' % checks)
print('ALL PASS')
