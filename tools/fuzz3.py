import os
import random
import subprocess
import sys

# fuzz3.py <样本> <N> [seed] [--any]
#   在 guard_alloc 下用 Pillow 解码变异样本；
#   崩溃判据：进程被信号杀死（rc < 0）——即 C 层越界/段错误，而不是 Python 异常(rc=1)

src = sys.argv[1] if len(sys.argv) > 1 else 't1.tif'
N = int(sys.argv[2]) if len(sys.argv) > 2 else 200
random.seed(int(sys.argv[3]) if len(sys.argv) > 3 else 1)

base = bytearray(open(src, 'rb').read())
hits = []

CODE = ("import sys;from PIL import Image;im=Image.open(sys.argv[1]);im.load();print('OK')")

for it in range(N):
    d = bytearray(base)
    for _ in range(random.randint(1, 3)):
        p = random.randrange(len(d))
        d[p] = random.randrange(256)
    fn = '/tmp/fz3.bin'
    open(fn, 'wb').write(bytes(d))
    env = dict(os.environ)
    env['LD_PRELOAD'] = '/tmp/guard2.so'
    env['GUARD_THRESH'] = '64'
    try:
        r = subprocess.run([sys.executable, '-c', CODE, fn], env=env,
                           timeout=10, capture_output=True)
        rc = r.returncode
        err = r.stderr.decode('utf-8', 'replace')[-200:]
    except subprocess.TimeoutExpired:
        rc = -9
        err = 'timeout'
    if rc < 0:
        name = '/tmp/fz3_%04d%s' % (it, os.path.splitext(src)[1])
        open(name, 'wb').write(bytes(d))
        hits.append((it, rc, name))
        print('CRASH it=%d rc=%d %s | %s' % (it, rc, name, err.replace('\n', ' ')[:120]), flush=True)

print('done %d, crashes=%d' % (N, len(hits)))