"""Find direct calls/jumps to an rva, pointers to it in data, and RIP-relative references to an rva."""
import struct, sys
from exe import Exe


def code_refs(x, target, kinds=(0xE8, 0xE9)):
    out = []
    for n, va, vs, ro, rs, c in x.secs:
        if not c & 0x20000000:
            continue
        data = x.m[ro:ro + rs]
        for k in kinds:
            p = data.find(bytes([k]))
            while p != -1:
                if p + 5 <= len(data):
                    d = struct.unpack_from('<i', data, p + 1)[0]
                    if va + p + 5 + d == target:
                        out.append((va + p, k))
                p = data.find(bytes([k]), p + 1)
    return out


def ptr_refs(x, target):
    needle = struct.pack('<Q', x.base + target)
    out = []
    p = x.m.find(needle)
    while p != -1:
        out.append(x.rva(p))
        p = x.m.find(needle, p + 1)
    return out


def rip_refs(x, target, lo=None, hi=None):
    """instructions with a rip-relative disp32 that resolves to target (any opcode): brute force over disp position."""
    out = []
    for n, va, vs, ro, rs, c in x.secs:
        if not c & 0x20000000:
            continue
        data = x.m[ro:ro + rs]
        # candidates: for each position p of disp32, next-instruction address is p+4 (+imm size 0/1/4)
        import numpy as np
        arr = np.frombuffer(data, dtype=np.uint8)
        n4 = len(arr) - 4
        d = (arr[0:n4].astype(np.int64) | (arr[1:n4 + 1].astype(np.int64) << 8) | (arr[2:n4 + 2].astype(np.int64) << 16) | (arr[3:n4 + 3].astype(np.int64) << 24))
        d = np.where(d >= 2 ** 31, d - 2 ** 32, d)
        pos = np.arange(n4, dtype=np.int64) + va
        for extra in (0, 1, 4):
            hit = np.nonzero(pos + 4 + extra + d == target)[0]
            for h in hit:
                out.append((int(va + h), extra))
    return out


if __name__ == '__main__':
    x = Exe()
    t = int(sys.argv[1], 16)
    for a, k in code_refs(x, t):
        f = x.func(a)
        print('%s from %x  func %s' % ('call' if k == 0xE8 else 'jmp ', a, '%x-%x' % f if f else '?'))
    for a in ptr_refs(x, t):
        print('pointer at %x [%s]' % (a, x.sec(a)))
