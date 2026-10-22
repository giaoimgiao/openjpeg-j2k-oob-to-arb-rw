import os
import random
import subprocess
import sys

# iccfuzz.py <icc> <N> [seed]
src = sys.argv[1] if len(sys.argv) > 1 else '/tmp/Pillow-1230/Tests/icc/sRGB_v4_ICC_preference.icc'
N = int(sys.argv[2]) if len(sys.argv) > 2 else 120
random.seed(int(sys.argv[3]) if len(sys.argv) > 3 else 1)

base = bytearray(open(src, 'rb').read())
print('icc size', len(base))

CODE = (
    "import sys, io\n"
    "from PIL import Image, ImageCms\n"
    "p = ImageCms.ImageCmsProfile(io.BytesIO(open(sys.argv[1],'rb').read()))\n"
    "s = ImageCms.createProfile('sRGB')\n"
    "t = ImageCms.buildTransform(p, s, 'RGB', 'RGB')\n"
    "im = Image.new('RGB', (8, 8), (200, 30, 40))\n"
    "ImageCms.applyTransform(im, t)\n"
)

hits = 0
for it in range(N):
    d = bytearray(base)
    for _ in range(random.randint(1, 4)):
        p = random.randrange(len(d))
        d[p] = random.randrange(256)
    fn = '/tmp/fzicc.icc'
    open(fn, 'wb').write(bytes(d))
    env = dict(os.environ)
    env['LD_PRELOAD'] = '/tmp/guard2.so'
    env['GUARD_THRESH'] = '64'
    try:
        r = subprocess.run([sys.executable, '-c', CODE, fn], env=env,
                           timeout=15, capture_output=True)
        rc = r.returncode
        err = r.stderr.decode('utf-8', 'replace').strip().splitlines()[-1:]
        err = err[0][:110] if err else ''
    except subprocess.TimeoutExpired:
        rc, err = -9, 'timeout'
    if rc < 0:
        hits += 1
        keep = '/tmp/fzicc_%04d.icc' % it
        open(keep, 'wb').write(bytes(d))
        print('CRASH it=%d rc=%d %s | %s' % (it, rc, keep, err), flush=True)

print('done %d crashes=%d' % (N, hits))