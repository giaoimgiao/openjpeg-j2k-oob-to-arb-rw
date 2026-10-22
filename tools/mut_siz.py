import struct
import sys

src = sys.argv[1] if len(sys.argv) > 1 else 'w8.j2k'
out = sys.argv[2] if len(sys.argv) > 2 else 'm.j2k'
field = sys.argv[3]
val = int(sys.argv[4], 0)

d = bytearray(open(src, 'rb').read())
i = d.find(b'\xff\x51')
assert i > 0, 'no SIZ'
F = {
    'Xsiz': (i + 6, '>I'), 'Ysiz': (i + 10, '>I'),
    'XOsiz': (i + 14, '>I'), 'YOsiz': (i + 18, '>I'),
    'XTsiz': (i + 22, '>I'), 'YTsiz': (i + 26, '>I'),
    'XTOsiz': (i + 30, '>I'), 'YTOsiz': (i + 34, '>I'),
    'Csiz': (i + 38, '>H'),
    'Ssiz': (i + 40, '>B'), 'XRsiz': (i + 41, '>B'), 'YRsiz': (i + 42, '>B'),
}
o, fmt = F[field]
struct.pack_into(fmt, d, o, val)
open(out, 'wb').write(bytes(d))
print('%s=%#x -> %s' % (field, val, out))