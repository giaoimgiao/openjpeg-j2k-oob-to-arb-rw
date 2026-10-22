import re
import sys
import glob

# census.py：抽出「分配数量」与「循环上界」不同源的配对
#   判据：同一函数窗口内，opj_calloc/opj_malloc 的数量表达式 X，
#         与随后 for(...; i < Y; ...) 的 Y 不是同一个标识符；
#         且循环体里出现了该缓冲的名字。

FILES = sys.argv[1:] or ['j2k.c', 'tcd.c', 'pi.c', 't2.c', 'jp2.c', 't1.c']

ALLOC = re.compile(
    r'([A-Za-z_][\w\.\->\[\]]*)\s*=\s*\([^)]*\)\s*opj_(?:calloc|malloc)\(\s*([^,)]+)')
LOOP = re.compile(r'for\s*\(\s*[^;]*;\s*([^;]+);')

def ids(expr):
    return set(re.findall(r'[A-Za-z_]\w*', expr))

rows = []
for fn in FILES:
    try:
        L = open(fn, errors='replace').read().splitlines()
    except OSError:
        continue
    for i, ln in enumerate(L):
        m = ALLOC.search(ln)
        if not m:
            continue
        buf, cnt = m.group(1), m.group(2).strip()
        buf_ids = ids(buf)
        # 往前找 3 行，数量可能在上一行
        ctx = ' '.join(L[max(0, i - 2):i + 1])
        m2 = ALLOC.search(ctx)
        if m2:
            buf, cnt = m2.group(1), m2.group(2).strip()
            buf_ids = ids(buf)
        base = buf.split('->')[-1].split('[')[0]
        for j in range(i + 1, min(i + 70, len(L))):
            lm = LOOP.search(L[j])
            if not lm:
                continue
            bound = lm.group(1).strip()
            if bound in cnt or cnt in bound:
                continue
            body = ' '.join(L[j:j + 12])
            if base not in body and buf not in body:
                continue
            # 只报“数量看起来来自文件”的：名字含 num/nb/count/size/parts/layers 等
            if not re.search(r'num|nb_|cnt|count|size|parts|layers|entries|res|bands|comps',
                             cnt, re.I):
                continue
            rows.append((fn, i + 1, buf, cnt,
                         L[j].strip()[:52]))

print('%-8s %-6s %-26s %-14s %s' % ('file', 'line', 'buffer', 'alloc-count', 'loop-bound'))
seen = set()
out = 0
for fn, line, buf, cnt, lb in rows:
    key = (fn, line)
    if key in seen:
        continue
    seen.add(key)
    print('%-8s %-6d %-26s %-14s %s' % (fn, line, buf[:26], cnt[:14], lb))
    out += 1
    if out >= 40:
        break
print('candidates:', len(seen))