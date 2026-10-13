"""Find a C string in the exe and everything that points at it (lea rip-relative or 8-byte pointer)."""
import struct, sys
from exe import Exe


def find_strings(x, s, exact=True):
    needle = (b'\0' + s.encode() + b'\0') if exact else s.encode()
    out = []
    p = x.m.find(needle)
    while p != -1:
        out.append(x.rva(p + (1 if exact else 0)))
        p = x.m.find(needle, p + 1)
    return [r for r in out if r]


def lea_refs(x, targets):
    targets = set(targets)
    out = []
    for n, va, vs, ro, rs, c in x.secs:
        if not c & 0x20000000:
            continue
        data = x.m[ro:ro + rs]
        for pre in (b'\x48\x8d', b'\x4c\x8d'):
            p = data.find(pre)
            while p != -1:
                if p + 7 <= len(data) and data[p + 2] & 0xC7 == 0x05:
                    t = va + p + 7 + struct.unpack_from('<i', data, p + 3)[0]
                    if t in targets:
                        out.append((va + p, t))
                p = data.find(pre, p + 1)
    return out


def ptr_refs(x, target):
    needle = struct.pack('<Q', x.base + target)
    out = []
    p = x.m.find(needle)
    while p != -1:
        out.append(x.rva(p))
        p = x.m.find(needle, p + 1)
    return out


if __name__ == '__main__':
    x = Exe()
    for s in sys.argv[1:]:
        rs = find_strings(x, s)
        print(s, [hex(r) for r in rs])
        for a, t in lea_refs(x, rs):
            f = x.func(a)
            print('  lea at %x -> %x func %s' % (a, t, '%x-%x' % f if f else '?'))
        for r in rs:
            for a in ptr_refs(x, r):
                print('  pointer at %x [%s] -> %x ; next qwords: %s' % (a, x.sec(a), r, ' '.join('%x' % (v - x.base) for v in struct.unpack('<4Q', x.read(a + 8, 32)))))
