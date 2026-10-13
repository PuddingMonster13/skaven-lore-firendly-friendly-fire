"""Extract named files from a pack: python -I extract_some.py <pack> <outdir> <substring> [<substring> ...]"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pack import read_pack

d, o, bm, m = read_pack(sys.argv[1])
out = os.path.abspath(sys.argv[2])
subs = [s.lower() for s in sys.argv[3:]]
for n, (q, s, c) in o.items():
    ln = n.lower().replace(chr(92), '/')
    if not any(x in ln for x in subs):
        continue
    b = d[q:q + s]
    if c:
        import zstandard
        b = zstandard.ZstdDecompressor().decompress(b[4:], max_output_size=struct.unpack('<I', b[:4])[0])
    p = os.path.abspath(os.path.join(out, ln))
    assert p.startswith(out + os.sep), n
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'wb').write(b)
    print(len(b), ln)
