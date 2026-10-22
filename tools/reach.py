import re
import sys
import glob

# reach.py：decoder 可达性分析
#   入口：opj_read_header / opj_read_tile_header / opj_decode_tile_data
#   建每函数体（行首 } 结束），扫描体内出现的其它函数名，BFS
#   输出可达函数集合；再对 census 候选判宿主函数是否可达

ENTRIES = ['opj_j2k_read_header_procedure','opj_j2k_decode_tiles','opj_j2k_copy_default_tcp_and_create_tcd']
FILES = sorted(glob.glob('*.c'))

def defname(line):
    m = re.match(r'^(?:static\s+)?(?:OPJ_BOOL|OPJ_UINT32|OPJ_INT32|void|OPJ_SIZE_T|'
                 r'OPJ_FLOAT32|OPJ_FLOAT64|char|int|size_t|opj_[a-z_]+_t\s*\*?)\s+\**'
                 r'([A-Za-z_]\w*)\s*\(', line)
    return m.group(1) if m else None

funcs = {}     # name -> (file, start, end)
for fn in FILES:
    L = open(fn, errors='replace').read().splitlines()
    i = 0
    while i < len(L):
        name = defname(L[i]) or defname(L[i-1] + " " + L[i]) or defname(L[i-2] + " " + L[i-1] + " " + L[i])
        if name and '(' in L[i]:
            j = i
            while j < len(L) and not L[j].rstrip().endswith('{'):
                j += 1
                if j - i > 6:
                    break
            if j < len(L) and L[j].rstrip().endswith('{'):
                k = j + 1
                while k < len(L) and L[k].rstrip() != '}':
                    k += 1
                funcs.setdefault(name, (fn, i, k))
                i = k + 1
                continue
        i += 1

print('functions parsed:', len(funcs))

bodies = {}
for name, (fn, s, e) in funcs.items():
    L = open(fn, errors='replace').read().splitlines()
    bodies[name] = ' '.join(L[s:e + 1])

reach = set()
q = [e for e in ENTRIES if e in funcs]
reach.update(q)
while q:
    cur = q.pop()
    body = bodies.get(cur, '')
    for name in funcs:
        if name in reach or name == cur:
            continue
        if re.search(r'\b%s\s*\(' % re.escape(name), body):
            reach.add(name)
            q.append(name)

print('decoder-reachable functions:', len(reach))

# 编码器专用入口，用于反向验证
ENC = ['opj_j2k_setup_encoder', 'opj_j2k_encode', 'opj_j2k_write_mct_data_group']
print('encoder entries reachable?',
      [(e, e in reach) for e in ENC])

# 判定几个关键函数
for f in ['opj_mct_decode_custom', 'opj_j2k_merge_ppm', 'opj_j2k_merge_ppt',
          'opj_tcd_code_block_dec_allocate', 'opj_j2k_read_sod']:
    print('  %-38s reachable=%s' % (f, f in reach))
