"""Reads the file table of a Total War .pack file (PFH5): read_pack(path) -> data, {name: (offset, size, compressed)}, flags, magic."""
import struct,sys
def read_pack(path):
    f=open(path,'rb'); d=f.read(); 
    magic=d[:4]; bm,pc,pis,fc,fis,ts=struct.unpack('<6I',d[4:28])
    off=28+ (0)
    off+=pis
    entries=[]; p=off
    has_ts=bm&0x40
    for i in range(fc):
        size,=struct.unpack('<I',d[p:p+4]); p+=4
        if has_ts: p+=4
        comp=d[p]; p+=1
        e=d.index(b'\0',p); name=d[p:e].decode('utf8'); p=e+1
        entries.append((name,size,comp))
    start=off+fis
    out={}; q=start
    for n,s,c in entries:
        out[n]=(q,s,c); q+=s
    return d,out,bm,magic
if __name__=='__main__':
    d,o,bm,m=read_pack(sys.argv[1]); print(m,hex(bm),len(o))
    for n in o:
        if len(sys.argv)<3 or sys.argv[2] in n: print(n,o[n][1],o[n][2])
