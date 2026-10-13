"""Read-only helpers for looking at Warhammer3.exe (never writes to it)."""
import bisect, mmap, os, struct, sys
import capstone
import pefile

# where the game is installed: set the environment variable WARHAMMER3_EXE if it is somewhere else
EXE = os.environ.get('WARHAMMER3_EXE', r'E:\Steam\steamapps\common\Total War WARHAMMER III\Warhammer3.exe')


class Exe:
    def __init__(self, path=EXE):
        self.pe = pefile.PE(path, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.f = open(path, 'rb')
        self.m = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        self.secs = [(s.Name.rstrip(b'\0').decode('latin1'), s.VirtualAddress, s.Misc_VirtualSize,
                      s.PointerToRawData, s.SizeOfRawData, s.Characteristics) for s in self.pe.sections]
        d = self.pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
        raw = self.read(d.VirtualAddress, d.Size)
        n = len(raw) // 12
        self.funcs = [struct.unpack_from('<III', raw, i * 12) for i in range(n)]
        self.funcs = [f for f in self.funcs if f[0]]
        self.funcs.sort()
        self.starts = [f[0] for f in self.funcs]
        self.cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        self.cs.detail = False

    def off(self, rva):
        for n, va, vs, ro, rs, c in self.secs:
            if va <= rva < va + max(vs, rs):
                if rva - va >= rs:
                    return None
                return ro + rva - va
        return None

    def rva(self, off):
        for n, va, vs, ro, rs, c in self.secs:
            if ro <= off < ro + rs:
                return va + off - ro
        return None

    def sec(self, rva):
        for n, va, vs, ro, rs, c in self.secs:
            if va <= rva < va + max(vs, rs):
                return n
        return None

    def read(self, rva, n):
        o = self.off(rva)
        if o is None:
            return b''
        return self.m[o:o + n]

    def func(self, rva):
        """(begin, end) of the .pdata entry holding rva (a function may have several chunks)."""
        i = bisect.bisect_right(self.starts, rva) - 1
        if i < 0:
            return None
        b, e, u = self.funcs[i]
        if b <= rva < e:
            return b, e
        return None

    def cstr(self, rva, limit=120):
        b = self.read(rva, limit)
        if not b:
            return None
        e = b.find(b'\0')
        if e <= 3:
            return None
        s = b[:e]
        if all(32 <= c < 127 for c in s):
            return s.decode()
        return None

    def dis(self, begin, end, out=sys.stdout, marks=()):
        code = self.read(begin, end - begin)
        for ins in self.cs.disasm(code, begin):
            note = ''
            op = ins.op_str
            if 'rip' in op:
                import re
                mm = re.search(r'rip ([+-]) (0x[0-9a-f]+)', op)
                if mm:
                    t = ins.address + ins.size + (int(mm.group(2), 16) if mm.group(1) == '+' else -int(mm.group(2), 16))
                    s = self.cstr(t)
                    note = '  ; -> %x' % t + (' "%s"' % s if s else '') + ' [%s]' % self.sec(t)
            mark = '>>' if ins.address in marks else '  '
            out.write('%s %8x  %-22s %-7s %s%s\n' % (mark, ins.address, ins.bytes.hex(), ins.mnemonic, op, note))


if __name__ == '__main__':
    x = Exe()
    a = int(sys.argv[1], 16)
    if len(sys.argv) > 2:
        b = int(sys.argv[2], 16)
    else:
        a, b = x.func(a)
    print('range %x-%x' % (a, b))
    x.dis(a, b)
