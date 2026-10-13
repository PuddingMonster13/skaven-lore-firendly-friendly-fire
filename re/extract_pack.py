"""Extract a whole pack: python -I extract_pack.py <pack> <outdir>   (-I: nothing from the pack can be imported)"""
import sys,os,struct
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from pack import read_pack
d,o,bm,m=read_pack(sys.argv[1]); out=os.path.abspath(sys.argv[2])
for n,(q,s,c) in o.items():
    b=d[q:q+s]
    if c:
        import zstandard; b=zstandard.ZstdDecompressor().decompress(b[4:],max_output_size=struct.unpack('<I',b[:4])[0])
    p=os.path.abspath(os.path.join(out,n.replace(chr(92),'/')))
    assert p.startswith(out+os.sep),n
    os.makedirs(os.path.dirname(p),exist_ok=True)
    open(p,'wb').write(b)
    print(len(b),n)
