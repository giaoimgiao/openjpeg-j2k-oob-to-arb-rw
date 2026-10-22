import os
import struct
import subprocess
import sys

# tifmut.py <tif> [iter] —— tag 级结构变异（只改 IFD 条目值，不改结构）
# 目标 tag：决定「分配」与「写入跨度」的那些
TAGS = {
    256: 'Width', 257: 'Length', 258: 'BitsPerSample', 259: 'Compression',
    262: 'Photometric', 273: 'StripOffsets', 277: 'SamplesPerPixel',
    278: 'RowsPerStrip', 279: 'StripByteCounts', 284: 'PlanarConfig',
    317: 'Predictor', 322: 'TileWidth', 323: 'TileLength',
    324: 'TileOffsets', 325: 'TileByteCounts', 338: 'ExtraSamples',
    339: 'SampleFormat',
}
EX = [0, 1, 2, 0xFFFF, 0x7FFF, 0xFFFFFFFF, 0x10000]

src = sys.argv[1] if len(sys.argv) > 1 else 't1.tif'
base = bytearray(open(src, 'rb').read())

if base[:2] == b'II':
    bo = '<'
elif base[:2] == b'MM':
    bo = '>'
else:
    sys.exit('not tiff')

ifd = struct.unpack_from(bo + 'I', base, 4)[0]
n = struct.unpack_from(bo + 'H', base, ifd)[0]
ents = []
for i in range(n):
    off = ifd + 2 + i * 12
    tag, typ, cnt = struct.unpack_from(bo + 'HHI', base, off)
    if tag in TAGS:
        ents.append((tag, typ, cnt, off))
print('IFD entries:', n, 'targetable:', [(TAGS[t], hex(o)) for t, _, _, o in ents][:12])

CODE = "import sys;from PIL import Image;im=Image.open(sys.argv[1]);im.load()"

hits = 0
runs = 0
for tag, typ, cnt, off in ents:
    for v in EX:
        d = bytearray(base)
        if typ == 3 and cnt == 1:          # SHORT inline
            struct.pack_into(bo + 'H', d, off + 8, v & 0xFFFF)
        elif typ == 4 and cnt == 1:        # LONG inline
            struct.pack_into(bo + 'I', d, off + 8, v & 0xFFFFFFFF)
        else:
            struct.pack_into(bo + 'I', d, off + 8, v & 0xFFFFFFFF)  # 改值/偏移
        fn = '/tmp/tm.tif'
        open(fn, 'wb').write(bytes(d))
        env = dict(os.environ)
        env['LD_PRELOAD'] = '/tmp/guard2.so'
        env['GUARD_THRESH'] = '64'
        try:
            r = subprocess.run([sys.executable, '-c', CODE, fn], env=env,
                               timeout=10, capture_output=True)
            rc = r.returncode
            err = r.stderr.decode('utf-8', 'replace').strip().splitlines()[-1:] 
            err = err[0][:100] if err else ''
        except subprocess.TimeoutExpired:
            rc = -9
            err = 'timeout'
        runs += 1
        if rc < 0:
            hits += 1
            keep = '/tmp/tm_%s_%x.tif' % (TAGS[tag], v & 0xFFFFFFFF)
            open(keep, 'wb').write(bytes(d))
            print('CRASH %-14s = %#x  rc=%d  %s  -> %s' %
                  (TAGS[tag], v, rc, err, keep), flush=True)

print('runs=%d crashes=%d' % (runs, hits))