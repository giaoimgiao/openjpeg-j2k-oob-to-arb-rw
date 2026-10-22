import os
import struct
import random
import subprocess
import sys

# fuzz2.py <模板> <N> [seed] —— 只变异 COD / QCD 的参数区
TPL = sys.argv[1] if len(sys.argv) > 1 else 'w8.j2k'
N = int(sys.argv[2]) if len(sys.argv) > 2 else 120
random.seed(int(sys.argv[3]) if len(sys.argv) > 3 else 1)

base = bytearray(open(TPL, 'rb').read())


def seg_range(buf, marker):
    i = buf.find(bytes([0xFF, marker]))
    if i < 0:
        return None
    L = struct.unpack('>H', buf[i + 2:i + 4])[0]
    return (i + 4, i + 2 + L)          # 参数区（不含 marker/L）


rcod = seg_range(base, 0x52)
rqcd = seg_range(base, 0x5C)
print('COD', rcod, 'QCD', rqcd)
ranges = [r for r in (rcod, rqcd) if r]

hits = []
for it in range(N):
    d = bytearray(base)
    for _ in range(random.randint(1, 2)):
        lo, hi = random.choice(ranges)
        p = random.randrange(lo, max(lo + 1, hi))
        d[p] = random.randrange(256)
    open('/tmp/fz2.j2k', 'wb').write(bytes(d))
    env = dict(os.environ)
    env['LD_LIBRARY_PATH'] = '/tmp/clean'
    env['LD_PRELOAD'] = '/tmp/guard2.so'
    env['GUARD_THRESH'] = '8'
    try:
        r = subprocess.run(['opj_decompress', '-i', '/tmp/fz2.j2k', '-o', '/tmp/fz2.pnm'],
                           env=env, timeout=6, capture_output=True)
        rc = r.returncode
    except subprocess.TimeoutExpired:
        rc = -9
    if rc not in (0, 1):
        name = '/tmp/fz2_%03d.j2k' % it
        open(name, 'wb').write(bytes(d))
        hits.append((it, rc, name))
        print('HIT it=%d rc=%d %s' % (it, rc, name), flush=True)

print('done %d iters, hits=%d' % (N, len(hits)))
for h in hits[:10]:
    print(h)