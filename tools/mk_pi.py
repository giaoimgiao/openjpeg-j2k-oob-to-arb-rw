import struct

d = bytearray(open('w8.j2k','rb').read())

# --- SIZ: 256x256, 单 tile ---
si = d.find(b'\xff\x51')
struct.pack_into('>I', d, si+6, 256)   # Xsiz
struct.pack_into('>I', d, si+10, 256)  # Ysiz
struct.pack_into('>I', d, si+22, 256)  # XTsiz
struct.pack_into('>I', d, si+26, 256)  # YTsiz

# --- COD: Scod=1, layers=0xFFFF, numres=1, +1 precinct byte ---
ci = d.find(b'\xff\x52')
L = struct.unpack('>H', d[ci+2:ci+4])[0]
param = bytearray(d[ci+4:ci+2+L])
print('orig Scod', param[0], 'layers', struct.unpack('>H', param[2:4])[0], 'numres', param[5])
param[0] = 1
struct.pack_into('>H', param, 2, 0xFFFF)
param[5] = 0
newL = 2 + len(param) + 1
new = b'\xff\x52' + struct.pack('>H', newL) + bytes(param) + b'\x00'
out = bytearray(d[:ci]) + bytearray(new) + bytearray(d[ci+2+L:])
open('pi1.j2k','wb').write(bytes(out))
print('OK', len(out), 'newL', newL)
