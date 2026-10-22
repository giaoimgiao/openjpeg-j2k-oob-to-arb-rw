import struct

d = bytearray(open('w8.j2k','rb').read())
si = d.find(b'\xff\x51')
struct.pack_into('>I', d, si+6, 256)
struct.pack_into('>I', d, si+10, 256)
struct.pack_into('>I', d, si+22, 256)
struct.pack_into('>I', d, si+26, 256)

ci = d.find(b'\xff\x52')
L = struct.unpack('>H', d[ci+2:ci+4])[0]
param = bytearray(d[ci+4:ci+2+L])
param[0] = 1                      # Scod: 带 precinct
struct.pack_into('>H', param, 2, 3073)
param[5] = 5                      # numres-1 = 5 => 6 分辨率
NR = 6
newL = 2 + len(param) + NR
new = b'\xff\x52' + struct.pack('>H', newL) + bytes(param) + bytes([0] * NR)
out = bytearray(d[:ci]) + bytearray(new) + bytearray(d[ci+2+L:])
open('pi2.j2k','wb').write(bytes(out))
print('OK', len(out), 'newL', newL, 'layers 3073 numres 6')
