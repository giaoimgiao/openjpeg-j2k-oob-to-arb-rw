import os
import random
import subprocess
import sys

# fuzz.py <模板> <N> [seed]
TPL = sys.argv[1] if len(sys.argv) > 1 else 'w8.j2k'
N = int(sys.argv[2]) if len(sys.argv) > 2 else 60
random.seed(int(sys.argv[3]) if len(sys.argv) > 3 else 1)

base = bytearray(open(TPL, 'rb').read())
HDR = 0x200          # 只打主头区（SIZ/TLM/COD/QCD/COM）
hits = []

for it in range(N):
    d = bytearray(base)
    for _ in range(random.randint(1, 4)):
        p = random.randrange(0, min(HDR, len(d)))
        d[p] = random.randrange(256)
    open('/tmp/fz.j2k', 'wb').write(bytes(d))
    env = dict(os.environ)
    env['LD_LIBRARY_PATH'] = '/tmp/clean'
    env['LD_PRELOAD'] = '/tmp/guard2.so'
    env['GUARD_THRESH'] = '8'
    try:
        r = subprocess.run(['opj_decompress', '-i', '/tmp/fz.j2k', '-o', '/tmp/fz.pnm'],
                           env=env, timeout=6, capture_output=True)
        rc = r.returncode
    except subprocess.TimeoutExpired:
        rc = -9
    if rc not in (0, 1):
        name = '/tmp/fz_%03d.j2k' % it
        open(name, 'wb').write(bytes(d))
        hits.append((it, rc, name))
        print('HIT it=%d rc=%d %s' % (it, rc, name), flush=True)

print('done %d iters, hits=%d' % (N, len(hits)))