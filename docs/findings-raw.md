# 原始标定数据（本机实测，含已作废结论）

> 警告：本文是按时间顺序累积的工作笔记，**其中部分推论在后续轮次已被源码级证伪**。
> 定性结论以 [`dead-ends.md`](dead-ends.md) 为准，本文只作为「数值与日志口径」的存档：
> 偏移、落点公式、free 三次实测、GOT 地址表等可复核数据。

---

# FINDINGS — openjpeg 2.5.4 / Pillow 12.3.0 远程链（实测数据）

> 环境：aarch64 Ubuntu 24.04 proot，CPython 3.12（非 PIE，基址 0x400000），
> Pillow 12.3.0 + libopenjp2-0ec72a70.so.2.5.4
> 所有数字均为插桩/gdb 实测，非推测。

## 1. 可用原语（全部实测）

| # | 原语 | 事实 | 备注 |
|---|---|---|---|
| P1 | 越界写 | `read_sod()` 按 TLM 条目数分配 `tp_index`，按 TPsot 递增写第 3 个槽 | 步长 24B（M/N 解耦后可 30 拍、覆盖 ~700B） |
| P2 | 写入值语义 | 写入值 = **流内偏移**，即文件偏移 | 与输入值偏差 **+0x17e**（标定值：设 0xa20e82 → 实得 0xa21000） |
| P3 | 任意 free | `tcd.c:913` 无条件 `opj_image_data_free(tilec->data_win)`，`data_win` 在 `comps+0x50` | 不需要 groom，天然远程 |
| P4 | 跨请求存活 | 同一文件解码两次 → 第二次崩（`PYTHONMALLOC=malloc` 后消失 ⇒ 污染在 CPython 分配器侧） | 真实 HTTP 下=请求 1 污染、请求 2 命中 |
| P5 | 静态写 | `tilec->data` 是 **int32 连续数组**；numres=1 无 DWT ⇒ 解码值 = 编码值 | 可写任意 4 字节到 37 个静态落点之一 |

## 2. 值域（决定一切的结构性事实）

```
可表达的值 ∈ [~0x150, 文件大小]
  ⇒ 4.2MB 文件即可表达 system@plt = 0x420580 / execve@plt = 0x41f6e0 / execv@plt = 0x420ec0
  ⇒ 11MB 文件可表达 .data/.bss 0xa20000..0xb8b000
  ⇒ 32 位字段（x0,y0 这类）= (值, 0) 对 ⇒ 几何退化
  ⇒ 64 位字段（指针）= 任意可表达地址
```

## 3. 静态窗口（hunt8，扫描区间 0x400000..0xb8b000，8.7MB）

条件：`numres∈1..8` + `resolutions` 已映射 + `data` ∈ [0xa20000,0xb8b000] + `data_win==NULL`
⇒ **37 个命中**，其中两个落在 `_PyRuntime`：

```
data=0xb21ed0 → _PyRuntime+0x7a20   正好是静态标识符对象 "__new__" 的起点
data=0xb21870 → _PyRuntime+0x73c0
```

## 4. 静态标识符表（本轮新发现）

- 位置：0xb21000 起，连续对象，内容是 `__co / __ctypes_from_outparam / __delattr / __delete__ / __delitem__ / __dictoffset__ / __divmod__ / __enter__ / ...`
- 单对象布局：`refcnt(4+pad) | ob_type=0xa3c8b0 | length | hash | state | chars@+0x24`
- 对齐命中：`0xb21ed0 - 0xb21000 = 0xed0` ⇒ 第一像素即命中 **ob_type**

## 5. 已排除的路（别再重复）

| 假设 | 结果 |
|---|---|
| comps → .bss 零窗口可存活 | ✗ segfault（数据字段为 NULL） |
| 静态 .data 里找合法 chunk 头给 free 用 | ✗ 只有 1 个且 PREV_INUSE=0 |
| .data 里存 `type+0x58`（tp_repr 槽） | ✗ 0 命中 |
| `type+0x20..0x58` 区间 | ✗ 0 命中 |
| 同时"活过 free(comps)+写 .data" | ✗ 0 个（清理阶段 tcd.c:2002 必 free） |
| `t1.c:2081 memcpy(cblkdata, chunk.data, chunk.len)` | ✗ 自洽：缓冲按同一个 sum 分配，改 len 只是把缓冲一起变大 |
| 多 tile 换邻居 | ✗ 邻居仍是 `tiles[]` |
| 梳子写第一拍 | ✗ 撞邻居 chunk size → `munmap_chunk` / `free(): invalid next size (fast)` |
| `_int_free` 校验 | next->size 必须 >0x10 且 < `av->system_mem`（实测 0x2f9000） |

## 6.5 【突破】堆地址可表达 + GOT 目标（本轮）

```
非 PIE CPython ⇒ brk 堆基址固定（bss 0xb8b000 之上）
实测 tp_index: 0xe78f20(87次) / 0xe79130(58) / 0xe7a4c0(27)  ⇒ 跨进程稳定，可硬编码
0xe7a4c0 = 15.2MB ⇒ 15MB 文件即可写出该值 ⇒ 堆地址【可表达】（推翻此前"不可表达"结论）

GOT（readelf -rW 实测）：
  strlen  @0xa20f70   ← 目标：写成 system@plt
  memcpy  @0xa20368
  strcmp  @0xa20bd8
  memmove @0xa20ed8
system@plt =0x420580 / execve@plt =0x41f6e0 / execv@plt =0x420ec0（objdump 实测）

目标链：
  comps → payload 内假 tilecomp(112B) → data=0xa20f70 → 像素 int32 写 = 0x00420580,0
  ⇒ strlen@GOT = system@plt ⇒ strlen(cmd) → system(cmd)（x0=char* ✓）

待办：①标定假 tilecomp 的稳定地址 ②可逆 J2K 编码使解码像素=指定指针值 ③验证 GOT 被改写


- 已有：任意 free、跨请求存活、静态 4 字节写（37 落点）、可表达 `system@plt`
- 缺：**"第一参数指向我们数据的调用点"**；openjpeg 的 `error_handler(msg, client)` 的 x0 是格式化缓冲 ✗
- 下一步两条并行：
  1. 用 P5 改 `0xb21ed0` 处标识符的 `ob_type`（写两个像素=一个 64 位类型指针，指向 0xa3xxxx 的另一个静态类型）⇒ 观察类型混淆后果
  2. 从 37 落点里找落在 chars 上的窗口 ⇒ 改名 + hash=-1（CPython 懒重算 hash，故远程不需要知道 siphash 种子）

## 7. 【里程碑】任意 free 成功执行（本轮实测）

```
free() 参数 = 我写的字节，且已【成功执行】（不再 misaligned / invalid pointer）

实测 1：comps=0xe790e0 → tp_index[22] @0xe79130 = 0xe75420
          ⇒ free(0xe75420) → 块进 unsorted bin（malloc(): invalid size (unsorted) 证明 free 已完成）
实测 2：槽值改成 0xe78f20（tp_index 自己，header 0x241 完好）
          ⇒ free(0xe78f20) 无报错，崩溃发生在其后（说明 free 成功）

地址算术（全部实测反解，误差 0）：
  tp_index[i] = tell + 0x72
  comps       = S_23 + 0x170
  自由度：PAD（决定 tell）、PRELAST=part(N-1) 长度（决定 S_23）
  comps+0x50 = tp_index[k] → 读到的值 = 我们指定 tell 的那个槽
```

glibc 三道门槛（全部已量清，不再是搜索）：
```
① (p & 0xf) == 0          16 字节对齐
② *(p-8) = 合法 chunk size（>=0x20, 16 对齐, 非 mmap 位）
③ p 必须落在已映射的可写页
```

当前剩余问题（唯一）：free 成功后进程崩 —— 因为清理阶段（tcd.c:2002）会再 free 一次被我们改写的 comps。
下一步：让 comps 同时是一个「header 合法 + 块内 +0x50 为 0（free(NULL) 无害）」的块 ⇒ 用 calloc 清零块 0xe75420
（data_win=*(0xe75470)=0 ⇒ free(NULL)；清理 free(0xe75420) ⇒ chunksize=0x441 合法）
