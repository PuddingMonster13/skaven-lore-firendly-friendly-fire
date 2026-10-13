# Skaven lore-firendly (no) friendly fire

A mod for **Total War: WARHAMMER III**. In the unmodded game, Ratling Guns, Jezzails and Warpfire Throwers hold
their fire whenever Skavenslaves stand in the line of fire. With this mod Skaven shoot straight through the friendly
units you choose. The shots are real, so the units in the way can be hit.

This repository holds the complete source of the mod, its offline tests and the small tools used to inspect the
game's executable, so that everyone can see exactly what the mod does.

## What the mod does in the game

- Skaven units with ammunition (weapon teams, Jezzails, Globadiers, slingers, artillery, lords and heroes) no longer
  treat the chosen friendly units as an obstacle. Other races are not affected.
- Nothing about the projectiles is changed. Only the question "may I fire?" is answered differently.
- No unit, stat or database table is changed. The pack contains three Lua scripts and nothing else.
- Options through the [Mod Configuration Tool](https://steamcommunity.com/sharedfiles/filedetails/?id=2927955021)
  (optional): expendable units (default), Clanrats, all infantry, monster infantry, or every friendly unit.

## Requirements

- [memreader Plus](https://steamcommunity.com/sharedfiles/filedetails/?id=3811098873) by Druwski
  ([source](https://github.com/PKozdra/memreader_plus)). The game has no setting for this behaviour, so the mod
  changes the game's line-of-fire check in memory, and memreader Plus is what makes that possible from a script.

## How it works

Before a unit fires, the game asks for every soldier near the line of fire "would this shot hit you?". One function
answers that question, both for the real flight of a projectile and for the check before firing; for allies in the
pre-fire check it makes the soldier bigger than he is, which is why units refuse to shoot past friends.

1. **Finding the place.** `source/cave.py` holds three byte patterns. Each must match exactly once in the game's
   code. Only struct offsets, data addresses and call targets are wildcards; opcodes, registers and every jump
   distance are fixed. If a game update changes that code, the patterns no longer match and the mod does nothing.
2. **The patch.** At the point where the function has just established "this soldier is an ally, it is the pre-fire
   check, and it is not the shooter's own unit", 93 bytes of machine code are inserted (a "code cave", also in
   `source/cave.py`, written out instruction by instruction). They compare the shooting unit and the unit in the way
   with two short lists. If both are listed, the function answers "no hit". Otherwise the game continues unchanged.
   The cave only compares addresses; it never follows them.
3. **The lists.** The battle script (`source/battle.lua.tpl`) fills the lists from the units in the battle and the
   settings: Skaven units with ammunition on one list, the units they may shoot through on the other. Every unit is
   confirmed against its own id before the game code is touched. The lists are refreshed every two seconds and
   switched off when the battle ends or when anything unexpected happens.
4. **Main menu check.** `source/frontend.lua.tpl` runs the same read-only search when the main menu opens and shows
   one message if this game version does not fit.

## Safety

- The mod only acts on the exact game code it was written for; on anything else it stays off and says so.
- The game code is only patched in a battle that needs it (a Skaven shooter and something to shoot through).
- No network access, no files written, no code loaded from outside the pack. The released pack writes at most two
  short lines per battle to the game's script log.
- The only native code is the 93-byte cave. `source/cavetest.py` runs those exact bytes natively against a table and
  checks every decision.

## Repository layout

| Path | What it is |
|---|---|
| `source/cave.py` | The machine code, the table layout and the byte patterns. Run it to check them against your game. |
| `source/gamecode.inc.lua` | Lua block that locates the game code; put into both scripts by the builder. |
| `source/battle.lua.tpl` | Battle script. Lines marked `--@debug` exist only in the optional test build. |
| `source/frontend.lua.tpl` | Main menu check and message box. |
| `source/mct_settings.lua` | Options for the Mod Configuration Tool. |
| `source/build.py` | Builds the pack. |
| `source/cavetest.py`, `source/mocktest.py` | Offline tests (no game needed). |
| `re/` | Read-only helpers for looking at `Warhammer3.exe` and at pack files. |
| `release_0.9/` | The texts of the Steam Workshop page. |

## Building and testing

Needs Python 3 on Windows with `capstone`, `pefile` and `lupa` (`pip install capstone pefile lupa`).

```
cd source
python cave.py                 # checks the patterns against the installed game (set WARHAMMER3_EXE if needed)
python build.py <out_dir>      # writes skaven_lore_friendly_fire.pack and the filled scripts
python cavetest.py             # must end with ALL PASS
python mocktest.py <out_dir>   # must end with ALL PASS
```

`python build.py <out_dir> --debug` additionally writes a test add-on pack whose battle script logs what it does to
`skaven_lore_friendly_fire_log.txt` in the game folder.

## After a game update

Run `python cave.py`. Three lines with `matches: 1` mean the mod still fits. Anything else means the function was
changed and has to be analysed again before the patterns are updated.

## Credits

- memreader Plus by Druwski, built on the memreader of Cpecific and squeek502.
- Mod Configuration Tool by Groove Wizard.
- Thumbnail artwork on the Workshop page by Kuro; it is not part of this repository.

## Licence

MIT, see [LICENSE](LICENSE). Total War: WARHAMMER III belongs to Creative Assembly and Games Workshop; this
repository contains none of the game's files.
