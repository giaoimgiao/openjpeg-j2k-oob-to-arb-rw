import struct
import sys

# mk_csiz.py <src.j2k> <out.j2k> <Csiz>
# 只重写 SIZ：把组件数改成 N，并为每个组件复制一份
#   (Ssiz, XRsiz, YRsiz)，取原第一个组件的值
# 其余标记（TLM/COD/QCD/COM/SOT...）原样保留，靠 L 字段自动重算位置

SRC, OUT = sys.argv[1], sys.argv[2]
N = int(sys.argv[3])

d = bytearray(open(SRC, 'rb').read())
si = d.find(b'\xff\x51')
assert si > 0
L = struct.unpack('>H', d[si + 2:si + 4])[0]
Csiz_old = struct.unpack('>H', d[si + 38:si + 40])[0]
comp0 = d[si + 40:si + 43]
assert len(comp0) == 3, comp0

body = bytearray(d[si + 4:si + 38])          # Rsiz .. YTOsiz（34B）
body += struct.pack('>H', N)                 # Csiz
body += bytes(comp0) * N                     # 每个组件 3B
newL = 2 + len(body)                         # L 不含自身 2 字节

new = bytearray(b'\xff\x51') + struct.pack('>H', newL) + body
out = bytearray(d[:si]) + new + bytearray(d[si + 2 + L:])

open(OUT, 'wb').write(bytes(out))
print('Csiz %d -> %d   L_siz %d -> %d   file %d -> %d' %
      (Csiz_old, N, L, newL, len(d), len(out)))