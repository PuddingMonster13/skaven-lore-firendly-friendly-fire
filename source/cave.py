"""Machine code of the code cave and the byte patterns that locate its place in Warhammer3.exe.

Run directly to check everything against the installed game exe:  python cave.py
"""
import os
import re
import struct
import sys

# ---------------------------------------------------------------------------------------------------------------
# Table the cave reads (allocated by the Lua script with game_alloc, zeroed = mod off)
# ---------------------------------------------------------------------------------------------------------------
TABLE_SIZE = 0x1080
OFF_ENABLE = 0x000  # dword: 0 = cave does nothing
OFF_ALL = 0x004  # dword: 1 = every allied unit lets shots through
# dword: how often the cave let a shot through (read by the test build only). Kept more than a cache line away from
# everything the cave reads, so counting on one thread never slows the reads of the others down.
OFF_COUNT = 0x1040
OFF_SHOOTERS = 0x010  # qword Unit* list, 0-terminated
OFF_BLOCKERS = 0x400  # qword Unit* list, 0-terminated
MAX_SHOOTERS = (OFF_BLOCKERS - OFF_SHOOTERS) // 8 - 2  # always leaves zero slots before the blocker list
MAX_BLOCKERS = (0x1000 - OFF_BLOCKERS) // 8 - 2  # always leaves zero slots before the end of the block

TBL_MARK = b'\x11' * 8  # replaced by the table address at run time
RET_MARK = b'\x22' * 8  # replaced by the address of "return no hit" at run time


def assemble():
    """Hand-assembled x64. At the site: rdi = blocker Unit* (or 0), r14 = shooter Unit*; rax, rcx, rdx, flags are free.
    Returns (bytes, labels)."""
    code = bytearray()
    labels = {}
    fixups = []  # (position of rel8, label)

    def emit(b):
        code.extend(b)

    def label(name):
        labels[name] = len(code)

    def jcc(opcode, target):
        emit(bytes([opcode, 0]))
        fixups.append((len(code) - 1, target))

    emit(b'\x48\xB8' + TBL_MARK)  # mov rax, TABLE
    emit(b'\x83\x38\x00')  # cmp dword [rax], 0
    jcc(0x74, 'out')  # je out
    emit(b'\x48\x85\xFF')  # test rdi, rdi
    jcc(0x74, 'out')  # je out
    emit(b'\x48\x8D\x48' + bytes([OFF_SHOOTERS]))  # lea rcx, [rax+0x10]
    label('s_loop')
    emit(b'\x48\x8B\x11')  # mov rdx, [rcx]
    emit(b'\x48\x85\xD2')  # test rdx, rdx
    jcc(0x74, 'out')  # je out
    emit(b'\x4C\x39\xF2')  # cmp rdx, r14
    jcc(0x74, 's_found')  # je s_found
    emit(b'\x48\x83\xC1\x08')  # add rcx, 8
    jcc(0xEB, 's_loop')  # jmp s_loop
    label('s_found')
    emit(b'\x83\x78' + bytes([OFF_ALL]) + b'\x00')  # cmp dword [rax+4], 0
    jcc(0x75, 'exempt')  # jne exempt
    emit(b'\x48\x8D\x88' + struct.pack('<i', OFF_BLOCKERS))  # lea rcx, [rax+0x400]
    label('b_loop')
    emit(b'\x48\x8B\x11')  # mov rdx, [rcx]
    emit(b'\x48\x85\xD2')  # test rdx, rdx
    jcc(0x74, 'out')  # je out
    emit(b'\x48\x39\xFA')  # cmp rdx, rdi
    jcc(0x74, 'exempt')  # je exempt
    emit(b'\x48\x83\xC1\x08')  # add rcx, 8
    jcc(0xEB, 'b_loop')  # jmp b_loop
    label('exempt')
    emit(b'\xFF\x80' + struct.pack('<i', OFF_COUNT))  # inc dword [rax+0x1040]
    emit(b'\x48\xB8' + RET_MARK)  # mov rax, RETURN_NO_HIT
    emit(b'\xFF\xE0')  # jmp rax
    label('out')  # falls through into the copied game instructions
    for pos, target in fixups:
        rel = labels[target] - (pos + 1)
        assert -128 <= rel <= 127
        code[pos] = rel & 0xFF
    return bytes(code), labels


CAVE, LABELS = assemble()
TBL_AT = CAVE.index(TBL_MARK)
RET_AT = CAVE.index(RET_MARK)
assert CAVE.count(TBL_MARK) == 1 and CAVE.count(RET_MARK) == 1
CAVE_A = CAVE[:TBL_AT]
CAVE_B = CAVE[TBL_AT + 8:RET_AT]
CAVE_C = CAVE[RET_AT + 8:]

# ---------------------------------------------------------------------------------------------------------------
# Patterns (memreader Plus find_pattern syntax). Wildcards are only: struct offsets, addresses of data and the targets
# of calls. Opcodes, registers, the stack slots of the arguments AND every jump distance are fixed, so a match means
# the control flow around the cave site is byte for byte the one that was analysed.
# '|' marks the address we want (removed before use).
# ---------------------------------------------------------------------------------------------------------------
P_SITE_SRC = '''
8B 55 6F                    ; mov edx,[rbp+0x6f]        mode
83 EA 01                    ; sub edx,1
0F 84 DF 00 00 00           ; je  (mode 1)
83 EA 01                    ; sub edx,1
0F 84 BD 00 00 00           ; je  (mode 2, real projectile)
83 EA 01                    ; sub edx,1
74 09                       ; je  (mode 3)
83 FA 01                    ; cmp edx,1
0F 85 DC 00 00 00           ; jne (not mode 4)
4C 8B 75 7F                 ; mov r14,[rbp+0x7f]        shooter Unit
4D 85 F6                    ; test r14,r14
74 30                       ; je
48 8B B8 ?? ?? ?? ??        ; mov rdi,[rax+0x2e8]       blocker Unit
48 85 FF                    ; test rdi,rdi
74 2D                       ; je
49 8D 4E ??                 ; lea rcx,[r14+0x20]
48 8B 01                    ; mov rax,[rcx]
FF 10                       ; call [rax]
48 8B 57 ??                 ; mov rdx,[rdi+0x20]
48 8D 4F ??                 ; lea rcx,[rdi+0x20]
8B D8                       ; mov ebx,eax
FF 12                       ; call [rdx]
3B C3                       ; cmp eax,ebx               same unit?
75 14                       ; jne
F3 0F 59 35 ?? ?? ?? ??     ; mulss xmm6,[rip+..]
8B 7D 5F                    ; mov edi,[rbp+0x5f]
4C 8B 75 67                 ; mov r14,[rbp+0x67]
E9 96 00 00 00              ; jmp
49 8B 95 ?? ?? ?? ??        ; mov rdx,[r13+0x80]        blocker alliance
48 85 D2                    ; test rdx,rdx
74 E8                       ; je
49 8B 46 ??                 ; mov rax,[r14+0x70]
48 8B 88 ?? ?? ?? ??        ; mov rcx,[rax+0x148]
8B 41 ??                    ; mov eax,[rcx+0x28]
39 42 ??                    ; cmp [rdx+0x28],eax        allied?
75 D5                       ; jne
|
48 8B 46 ??                 ; mov rax,[rsi+0x50]        <- cave goes here
48 8B 88 ?? ?? ?? ??        ; mov rcx,[rax+0x440]
48 8B 41 ??                 ; mov rax,[rcx+8]
48 8B 88 ?? ?? ?? ??        ; mov rcx,[rax+0x430]
48 8B 49 ??                 ; mov rcx,[rcx+0x20]
E8 ?? ?? ?? ??              ; call                      (rdx dies here)
83 7D 6F 04                 ; cmp dword [rbp+0x6f],4    (flags are set again here)
8B 7D 5F                    ; mov edi,[rbp+0x5f]
75 13                       ; jne
F3 0F 59 B0 ?? ?? ?? ??     ; mulss xmm6,[rax+ignore_allies_radius]
F3 44 0F 59 88 ?? ?? ?? ??  ; mulss xmm9,[rax+ignore_allies_height]
EB 9D                       ; jmp
F3 0F 59 B0 ?? ?? ?? ??     ; mulss xmm6,[rax+man_radius]
F3 44 0F 59 88 ?? ?? ?? ??  ; mulss xmm9,[rax+man_height]
EB 8A                       ; jmp
'''

P_RET_SRC = '''
41 0F 2F D8                 ; comiss xmm3,xmm8
73 07                       ; jae
B0 01                       ; mov al,1                  hit
E9 E5 00 00 00              ; jmp epilogue
|
32 C0                       ; xor al,al                 <- "return no hit"
E9 DE 00 00 00              ; jmp epilogue
F3 0F 10 BE ?? ?? ?? ??     ; movss xmm7,[rsi+..]
F3 0F 10 B6 ?? ?? ?? ??     ; movss xmm6,[rsi+..]
0F 28 C7                    ; movaps xmm0,xmm7
F3 44 0F 10 96 ?? ?? ?? ??  ; movss xmm10,[rsi+..]
'''

# unique_ui_id script function: "mov rcx,[rsi+8]" (Unit* inside the script interface) and "mov edx,[rcx+uid]"
P_UID_SRC = '''
48 8B F1                    ; mov rsi,rcx               this
48 8B FA                    ; mov rdi,rdx
48 8B CA                    ; mov rcx,rdx
E8 ?? ?? ?? ??              ; call
48 8B CF                    ; mov rcx,rdi
48 8B D8                    ; mov rbx,rax
E8 ?? ?? ?? ??              ; call
48 8B 4E 08                 ; mov rcx,[rsi+8]           Unit*
8B 91
|
?? ?? ?? ??                 ; mov edx,[rcx+0x3ea0]      unique_ui_id
48 8B CB                    ; mov rcx,rbx
E8 ?? ?? ?? ??              ; call
48 8B 5C 24 30              ; mov rbx,[rsp+0x30]
B8 01 00 00 00              ; mov eax,1
'''

EXPECT_AT_SITE = bytes.fromhex('488b46')  # mov rax,[rsi+..]
EXPECT_AT_RET = bytes.fromhex('32c0e9')  # xor al,al ; jmp


def parse(src):
    """-> (pattern string for memreader, offset of the '|' mark in bytes)"""
    toks = []
    mark = None
    for line in src.splitlines():
        line = line.split(';')[0].strip()
        if not line:
            continue
        if line == '|':
            mark = len(toks)
            continue
        toks += line.split()
    for t in toks:
        assert t == '??' or re.fullmatch('[0-9A-F]{2}', t), t
    assert toks[0] != '??' and len(toks) <= 256, len(toks)
    return ' '.join(toks), mark


P_SITE, SITE_OFF = parse(P_SITE_SRC)
P_RET, RET_OFF = parse(P_RET_SRC)
P_UID, UID_OFF = parse(P_UID_SRC)


def to_regex(pattern):
    return re.compile(b''.join(b'.' if t == '??' else re.escape(bytes([int(t, 16)])) for t in pattern.split()), re.S)


def check_against_exe():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 're'))
    from exe import Exe
    x = Exe()
    res = {}
    for name, pat, off in (('site', P_SITE, SITE_OFF), ('ret', P_RET, RET_OFF), ('uid', P_UID, UID_OFF)):
        rx = to_regex(pat)
        hits = []
        for n, va, vs, ro, rs, c in x.secs:
            if not c & 0x20000000:
                continue
            for m in rx.finditer(x.m[ro:ro + rs]):
                hits.append(va + m.start())
        print('%-5s %3d bytes, matches: %d %s -> target rva %s' % (
            name, len(pat.split()), len(hits), [hex(h) for h in hits[:4]], hex(hits[0] + off) if hits else None))
        assert len(hits) == 1, name
        res[name] = hits[0] + off
    assert x.read(res['site'], 3) == EXPECT_AT_SITE
    assert x.read(res['ret'], 3) == EXPECT_AT_RET
    f1, f2 = x.func(res['site']), x.func(res['ret'])
    print('site in function %x-%x, ret in function %x-%x' % (f1 + f2))
    assert f1 == f2
    # Only the analysed paths may reach the cave site: inside the function nothing may jump to the site, into the
    # 11 bytes memreader copies, or anywhere after the start of the "is it an ally" block up to there.
    import capstone
    begin, end = f1
    targets = {}
    decoded_to = begin
    for ins in capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64).disasm(x.read(begin, end - begin), begin):
        decoded_to = ins.address + ins.size
        if ins.mnemonic.startswith('j') and ins.op_str.startswith('0x'):
            targets.setdefault(int(ins.op_str, 16), []).append(ins.address)
    assert decoded_to == end, 'function does not decode to its end'
    toks = P_SITE.split()
    ally_block = res['site'] - SITE_OFF + next(i for i in range(len(toks)) if toks[i:i + 3] == ['49', '8B', '95'])
    stray = {hex(t): [hex(a) for a in v] for t, v in targets.items() if ally_block < t < res['site'] + 11}
    print('ally block at %x; jumps landing after its start and before site+11: %s' % (ally_block, stray or 'none'))
    assert not stray
    print('jumps to the ally block come from:', [hex(a) for a in targets.get(ally_block, [])])
    assert len(targets.get(ally_block, [])) == 2
    uid = struct.unpack('<I', x.read(res['uid'], 4))[0]
    print('unique_ui_id offset in Unit: 0x%x' % uid)
    print('\ncave (%d bytes):' % len(CAVE))
    import capstone
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    total = 0
    for ins in cs.disasm(CAVE, 0):
        print('  %02x  %-24s %s %s' % (ins.address, ins.bytes.hex(), ins.mnemonic, ins.op_str))
        total = ins.address + ins.size
    assert total == len(CAVE), 'cave does not decode to its end'
    print('labels', {k: hex(v) for k, v in LABELS.items()})
    return res


if __name__ == '__main__':
    check_against_exe()
