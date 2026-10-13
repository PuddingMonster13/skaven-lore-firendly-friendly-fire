-- Skaven lore-firendly (no) friendly fire: settings for the Mod Configuration Tool (MCT).
-- MCT reads this file if it is installed. Without MCT the mod uses its default (expendable units only).
local MOD = 'skaven_lore_friendly_fire'
local ALL = 'sst_all'
local OTHERS = { 'sst_expendable', 'sst_clanrats', 'sst_infantry', 'sst_monstrous' }

local mct = get_mct()

local mct_mod = mct:register_mod(MOD)
mct_mod:set_title('Skaven lore-firendly (no) friendly fire')
mct_mod:set_author('Maquieq')
mct_mod:set_description(
	'Skaven ranged units no longer hold their fire because the chosen friendly units stand in the line of fire. The shots can hit those units. Works for the player and the AI. Needs memreader Plus.'
)

mct_mod:add_new_section('shoot_through', 'Shoot through')

local function add_box(key, text, tooltip, default)
	local option = mct_mod:add_new_option(key, 'checkbox')
	option:set_default_value(default)
	option:set_text(text)
	option:set_tooltip_text(tooltip)
	return option
end

add_box('sst_expendable', 'Expendable units', 'Skavenslaves, Skavenslave Spears, Skavenslave Slingers and Pusbags.', true)
add_box('sst_clanrats', 'Clanrats', 'Clanrats and Clanrat Spearmen, with and without shields.', false)
add_box('sst_infantry', 'All infantry', 'Every infantry unit of the Skaven army: the two groups above, Stormvermin, Plague Monks and all other infantry.', false)
add_box('sst_monstrous', 'Monster infantry', 'Rat Ogres and Stormfiends.', false)
add_box(ALL, 'All', 'Ticks or unticks all options above. While it is ticked, Skaven shoot through every friendly unit, lords and heroes included.', false)

-- "All" ticks or unticks the other boxes; unticking one of the others unticks "All"
local busy = false

local function on_changed(context)
	if busy then return end
	busy = true
	pcall(function()
		local option = context:option()
		if option:get_mod_key() ~= MOD then return end
		local key = option:get_key()
		local ticked = context:setting() == true
		if key == ALL then
			for _, other_key in ipairs(OTHERS) do
				local other = mct_mod:get_option_by_key(other_key)
				if other and other:get_selected_setting() ~= ticked then other:set_selected_setting(ticked) end
			end
		elseif not ticked then
			local all = mct_mod:get_option_by_key(ALL)
			if all and all:get_selected_setting() == true then all:set_selected_setting(false) end
		end
	end)
	busy = false
end

if core and core.add_listener then
	core:remove_listener(MOD .. '_all_box')
	core:add_listener(MOD .. '_all_box', 'MctOptionSelectedSettingSet', true, on_changed, true)
end
