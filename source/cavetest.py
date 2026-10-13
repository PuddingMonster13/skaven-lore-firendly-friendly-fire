"""Runs the real cave bytes natively inside this Python process against a fake table and checks every decision.
Nothing here touches the game.  python cavetest.py  -> must end with ALL PASS."""
import ctypes
import struct

import cave

k32 = ctypes.windll.kernel32
k32.VirtualAlloc.restype = ctypes.c_void_p
k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]

table = (ctypes.c_ubyte * cave.TABLE_SIZE)()
tbl_addr = ctypes.addressof(table)

PRE = bytes.fromhex('57' '4156' '4989ce' '4889d7')  # push rdi; push r14; mov r14,rcx; mov rdi,rdx
FALL = bytes.fromhex('b801000000' '415e' '5f' 'c3')  # mov eax,1; pop r14; pop rdi; ret   (= game continues: blocked check goes on)
RET0 = bytes.fromhex('31c0' '415e' '5f' 'c3')  # xor eax,eax; pop r14; pop rdi; ret    (= "no hit")

mem = k32.VirtualAlloc(None, 0x1000, 0x3000, 0x40)
assert mem
ret0_addr = mem + len(PRE) + len(cave.CAVE) + len(FALL)
code = PRE + cave.CAVE_A + struct.pack('<Q', tbl_addr) + cave.CAVE_B + struct.pack('<Q', ret0_addr) + cave.CAVE_C + FALL + RET0
ctypes.memmove(mem, code, len(code))
run = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint64)(mem)


def fill(enable, all_flag, shooters, blockers):
    ctypes.memset(tbl_addr, 0, cave.TABLE_SIZE)
    struct.pack_into('<II', table, 0, enable, all_flag)
    for i, p in enumerate(shooters):
        struct.pack_into('<Q', table, cave.OFF_SHOOTERS + 8 * i, p)
    for i, p in enumerate(blockers):
        struct.pack_into('<Q', table, cave.OFF_BLOCKERS + 8 * i, p)


def count():
    return struct.unpack_from('<I', table, cave.OFF_COUNT)[0]


S1, S2, B1, B2, X = 0x7FF612340010, 0x7FF612350010, 0x7FF612360010, 0x7FF612370010, 0x7FF612380010
BLOCKED, THROUGH = 1, 0
checks = 0


def expect(name, got, want):
    global checks
    checks += 1
    assert got == want, '%s: got %r want %r' % (name, got, want)


fill(0, 0, [S1], [B1])
expect('disabled', run(S1, B1), BLOCKED)
expect('disabled count', count(), 0)
fill(0, 1, [S1], [B1])
expect('disabled with all', run(S1, B1), BLOCKED)
fill(1, 0, [], [])
expect('empty lists', run(S1, B1), BLOCKED)
fill(1, 0, [S1, S2], [B1, B2])
expect('listed pair 1', run(S1, B1), THROUGH)
expect('listed pair 2', run(S2, B2), THROUGH)
expect('listed pair 3', run(S1, B2), THROUGH)
expect('count after 3', count(), 3)
expect('other blocker', run(S1, X), BLOCKED)
expect('other shooter', run(X, B1), BLOCKED)
expect('blocker unit unknown (0)', run(S1, 0), BLOCKED)
expect('shooter is only a blocker', run(B1, B2), BLOCKED)
expect('blocker is only a shooter', run(S1, S2), BLOCKED)
expect('count unchanged', count(), 3)
fill(1, 1, [S1], [])
expect('all: any blocker', run(S1, X), THROUGH)
expect('all: blocker unit unknown (0)', run(S1, 0), BLOCKED)
expect('all: other shooter', run(X, B1), BLOCKED)
fill(1, 0, [S1], [])
expect('shooter listed, no blockers', run(S1, B1), BLOCKED)
# full lists: last entries are found, and the scan stops at the guaranteed zero slot
many_s = [0x10000000 + 16 * i for i in range(cave.MAX_SHOOTERS)]
many_b = [0x20000000 + 16 * i for i in range(cave.MAX_BLOCKERS)]
fill(1, 0, many_s, many_b)
expect('full lists last/last', run(many_s[-1], many_b[-1]), THROUGH)
expect('full lists miss blocker', run(many_s[-1], X), BLOCKED)
expect('full lists miss shooter', run(X, many_b[0]), BLOCKED)
# a blocker pointer that only appears in the shooter list must not count as a blocker (shooter scan must not run on)
fill(1, 0, many_s, [])
expect('shooter list does not leak into blocker list', run(many_s[0], many_s[1]), BLOCKED)
# callee-saved registers survive (run() would crash or misbehave otherwise); run many times
fill(1, 0, [S1], [B1])
for _ in range(100000):
    assert run(S1, B1) == THROUGH
expect('count after loop', count(), 100000)
print('cave is %d bytes, %d checks' % (len(cave.CAVE), checks))
print('ALL PASS')
