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
