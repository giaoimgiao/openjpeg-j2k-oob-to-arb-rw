import re
import sys

# ts.py <log> [LO HI]
# 时序判别器：某个地址在 read_sod（越界写）发生时是否【已存在且仍有效】
# 输出：地址 / 分配行号 / 是否早于首个 read_sod / 期间是否被 free / 之后是否被 memset 风险

LOG = sys.argv[1] if len(sys.argv) > 1 else 'ap.log'
txt = open(LOG, errors='replace').read().splitlines()

ap = re.compile(r'ALLOC (malloc|calloc)] (?:n=(\d+) )?s(?:ize)?=(\d+) -> (0x[0-9a-f]+)')
fp = re.compile(r'FREE] (0x[0-9a-f]+) chunksize=(0x[0-9a-f]+)')
rs = re.compile(r'DBG read_sod')

first_rs = None
# 基准 = 最后一次 "decode #" 标记之后的第一个 read_sod（多段日志时取最后一段）
last_dec = 0
for i, ln in enumerate(txt, 1):
    if 'decode #' in ln:
        last_dec = i
for i, ln in enumerate(txt, 1):
    if i <= last_dec:
        continue
    if rs.search(ln):
        first_rs = i
        break
if first_rs is None:
    for i, ln in enumerate(txt, 1):
        if rs.search(ln):
            first_rs = i
            break

if first_rs is None:
    print('no DBG read_sod')
    sys.exit(1)

LO = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0
HI = int(sys.argv[3], 0) if len(sys.argv) > 3 else 1 << 64

alloc = {}   # addr -> (line, size)
free = {}    # addr -> first free line
for i, ln in enumerate(txt, 1):
    m = ap.search(ln)
    if m:
        n = int(m.group(2)) if m.group(2) else 1
        alloc[int(m.group(4), 16)] = (i, n * int(m.group(3)))
        continue
    m = fp.search(ln)
    if m:
        a = int(m.group(1), 16)
        free.setdefault(a, i)

print('first read_sod at line', first_rs)
print('%-12s %-7s %-8s %-9s %s' % ('addr', 'line', 'size', 'before?', 'note'))
rows = 0
for a, (line, size) in sorted(alloc.items()):
    if not (LO <= a <= HI):
        continue
    before = line < first_rs
    note = ''
    if not before:
        note = 'TOO LATE: 写入时还不存在'
    elif a in free and free[a] < first_rs:
        note = 'FREED BEFORE'
    elif size >= 80:
        note = 'exists at write time（需再查之后是否 memset）'
    print('%-12s %-7d %-8d %-9s %s' % (hex(a), line, size, 'YES' if before else 'no', note))
    rows += 1
    if rows > 40:
        print('...')
        break
print('total in window:', rows)