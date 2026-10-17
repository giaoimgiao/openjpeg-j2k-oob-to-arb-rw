# 从一张 J2K 图片到 root：Pillow 内嵌 openjpeg 越界写的完整利用链

> **状态**：本地 PoC（在作者环境复现成功，见 `exp/`）。
> **披露状态**：目标为 Pillow 12.3.0 内 **vendored** 的 openjpeg 2.5.4（补丁未跟进）。
> **在完成协调披露前，请勿公开投递细节。** 本文为技术记录草稿。

---

## 0. TL;DR

- **入口**：一个 J2K(JPEG2000) 文件。
- **根因**：openjpeg `j2k.c` 的 `read_sod()` 按 **TLM 声明的 tile-part 数** 分配
  `tp_index` 数组，却按 **SOT 的 `TPsot`** 递增写入 ⇒ 越界写（OOB write）。
- **原语**：每个越界 part 连续写两个 8 字节值（`v1`=SOD 文件偏移，`v2`=下一 part 偏移−10），
  构成一个"地址单调递增的规律双写"。
- **利用（Data-Oriented，不用 free/UAF/GOT/ROP）**：
  1. 用 **3 段**越界写把紧邻 `tp_index` 的、**我们自己伪造的大 `bytes`** 改造成 `memoryview`
     （`ob_type→PyMemoryView_Type`，`view.buf→任意地址`）；
     之后 `victim[i]` / `victim[i]=x` 就是**任意内存读写**。
  2. 两次解码：① `buf`=目标 `str` 地址 → 把命令写进它的首字节；② `buf`=`PyUnicode_Type.tp_repr` → 写入 `system`。
  3. `repr(str)` ⇒ `system("id")` ⇒ 命令执行（本环境 `uid=0(root)`）。

---

## 1. 背景：为什么要打"依赖的依赖"

> **本文定位（原语篇）**：本文记录的是**原语**这一层 —— 如何用一张 J2K 图片把这个漏洞
> 变成"**任意内存读写 + 信息泄露（ASLR 归零）**"。
> 从同一原语走到"**一条命令执行**"的**最短路线**（一次解码、不需要 memoryview 元数据），
> 见姊妹仓库 [`comfyui-openjpeg-rce`](https://github.com/giaoimgiao/comfyui-openjpeg-rce)；
> 两条链的差异与组合方式见 [`RELATION.md`](https://github.com/giaoimgiao/openjpeg-j2k-oob-to-arb-rw/blob/main/RELATION.md)。
> 下文出现的 **ComfyUI** 指的是"受影响目标"的举例（ComfyUI → Pillow → 内嵌 openjpeg），
> 不代表本文只适用于 ComfyUI。

```
ComfyUI  ──依赖──▶  Pillow 12.3.0  ──vendored──▶  openjpeg 2.5.4
   (最新已修)             (最新已修)                 (补丁未跟进 ← 打这里)
```
ComfyUI / Pillow 主版本的最新漏洞都已修复，但 **Pillow 把 openjpeg 源码 vendored 进
自己的 wheel**（`pillow.libs/libopenjp2-*.so`），上游 openjpeg 的修复并不自动进入
Pillow 的构建。于是这一类"**框架依赖级**"漏洞具备**通杀性**：
只要目标用这份 Pillow 版本，同一份文件即可命中。

---

## 2. 漏洞根因（源码级）

`openjpeg/src/lib/openjp2/j2k.c`：

```c
/* read_sot()：数组大小 = TLM 声明的条目数 */
if (! p_j2k->...m_tlm.m_is_invalid) {
    /* do nothing */
} else { /* 只有 TLM 无效时才扩容 */ }

/* read_sod()：写索引来自 SOT 的 TPsot */
OPJ_UINT32 l_current_tile_part =
    cstr_index->tile_index[tile].current_tpsno;      /* 由 TPsot 递增 */

l_cstr_index->tile_index[tile].tp_index[l_current_tile_part].end_header = l_current_pos;
l_cstr_index->tile_index[tile].tp_index[l_current_tile_part].end_pos    =
        l_current_pos + sot_length + 2;
```

**TLM 有效时数组永不增长**，而 `TPsot` 可以一直增：
当 `TPsot >= TLM条目数` 时，下标越界 ⇒ 在 `tp_index` 数组之后连续写两个 8 字节。
（对应 OSV-2025-219 / PR#9520 一类 J2K 越界写。）

---

## 3. 原语的精确刻画

设数组基址为 `tp`，第 `k` 个越界 part（`k = TPsot = N, N+1, ...`，`N` 为 TLM 条目数）写入：

```
写点：tp + 24N + 8·...      相对"数组后第一个对象"(victim) 的偏移：
  k = N   →  victim+0x00 (v1) , victim+0x08 (v2)
  k = N+1 →  victim+0x18 (v1) , victim+0x20 (v2)
  k = N+2 →  victim+0x30 (v1) , victim+0x38 (v2)
```

- **自由槽**（值可控）= 偏移 ≡ 8 (mod 24)：`+0x08 +0x20 +0x38 +0x50 ...`
- **耦合死槽**（值 = 前一个自由槽 + 2）= 偏移 ≡ 0 (mod 24)：`+0x00 +0x18 +0x30 +0x48 +0x60 ...`
- **单调约束**：`v2(k) = (part k+1 的 SOD 偏移) − 10`，part 在文件里顺序排列
  ⇒ **地址越高的槽，值必然越大** ⇒ `+0x08 < +0x18 < +0x20 < +0x30 < +0x38 < ...`

### 3.1 单调约束的直接结论
`ob_type(+0x08) < buf(+0x38)`。由于 `PyMemoryView_Type = 0xa350c8` 高于所有
GOT 槽（`0xa1ffe8–0xa21020`）⇒ **GOT 覆盖不可达**，必须换靶子。

---

## 4. 利用思路：Data-Oriented（把对象"嫁接"成 memoryview）

> 关键转变：不要去找"哪个对象会被释放"（那只能靠扫），而是问
> **"我要让哪个合法操作替我去读写内存"**。

`memoryview` 的 `Py_buffer` 结构（CPython 3.12）：

```
+0x38 view.buf    ← 数据指针（自由槽 ✓）
+0x40 view.obj    +0x48 view.len
+0x50 view.itemsize   +0x58 readonly(int)/ndim(int)
+0x60 view.format     +0x68 view.shape    +0x70 view.strides
```

只要把 `view.buf` 指向任意地址，`mv[i]` / `mv[i]=x` 就是任意读写，**解释器正常逻辑**。

### 4.1 三个工程约束（全部踩过）
1. **只写到 stride `m=2`（`+0x30/+0x38`）就停**。
   若继续写 `m=3`，则耦合规则强制 `view.format(+0x60) = itemsize(+0x50) + 2`，
   无法同时满足 `itemsize=1` 且 `format` 合法 ⇒ `mv[0]` 崩。
2. **`N` 必须为奇数**。victim 基址 `= 24N+8` 必须等于 `tp_index` 的 chunk size
   `align(24N+8,16)`；否则错位 8 字节，会把写打进邻居的 **chunk size 字段** ⇒
   `double free / corrupted size`。本例取 **`N=23`**（chunk `0x230`）。
3. **victim 必须 >512 字节**（走 glibc 堆）。
   Python 小对象（≤512B）走 **pymalloc**，与 `tp_index`（glibc malloc）**永远不相邻**。

### 4.2 受害者：一个大 `bytes`，内容里预置 view 结构
victim = `bytes(608)`，其内容从 `obj+0x20` 起，因此把 view 字段直接写进内容：
`format` 指向 `'B'`、`shape`/`strides` 借用临时 memoryview 的地址。
经 3 段越界写后，它就"变成"了一个可用的 memoryview。

### 4.3 堆风水（布置，而非扫描）
```
drain 旧空闲块(hold) → 连续分配 400 组 [D(bytes519,chunk0x230)] [victim(chunk0x290)]
→ 只释放"对齐"的 D（id(v)-id(D)==0x230）→ 解码
⇒ tp_index(N=23, chunk0x230) 落进洞，其邻居正好是 victim
```

---

## 5. 从任意读写到 RCE

由于 `buf ≥ 0xa350c8`（单调约束），可达靶子为 **类型对象的 `tp_*` 槽**：

```
buffer = PyUnicode_Type.tp_repr (0xa3c908)
mv[0..7] = &system                ⇒  repr() 变成 system()
```
再把一个大 `str` 的首 8 字节写成命令，`repr(str)` ⇒ `system(str_ptr)` ⇒ 执行。

**细节**：`repr(x)` 会 `LOAD_GLOBAL` 一次 ⇒ 对象 `ob_refcnt`（即内存首字节）**+1**，
所以首字节写 `'h'`，执行时正好是 `'i'`（命令 `id`）。

---

## 6. 复现

```bash
bash repro/repro.sh
# system = 0x...
# 目标 str id=0xc28120
#   命中 = 1
# mv1 buf=0xc28120 len=0x10
#   命中 = 1
# tp_repr 槽 = 0x... (期望 0x...) 
# === RCE_TRIGGER_BEGIN ===
# uid=0(root) gid=0(root) ...
```

目录：
- `repro/repro_local.py` —— 主复现逻辑（风水 + 两次嫁接 + 触发）
- `repro/builder.py` —— 三段越界写构造器（J2K 生成）
- `repro/base.j2k` —— 403 字节最小 4-tile 基础图
- `repro/repro.sh` —— 一键（本地）
- `poc/poc_dos.jp2` —— 上传即可触发的崩溃 PoC
- `poc/check_target.py` —— 环境检测器

---

## 7. 影响面与限制（诚实版）

| 项 | 说明 |
|---|---|
| **前提 A：文件可到 ~11–13MB** | 值即文件偏移，而目标地址 ≈ `0xa2–0xd0`（10.6–13MB）⇒ 文件必须 > 该值。**≤10MiB 上传限制的部署天然不受影响**。 |
| **前提 B：地址稳定** | 本次利用使用固定绝对地址（本环境 Python 基址 `0x400000` 固定、无 ASLR）。带 ASLR 的部署需要先做信息泄露。 |
| **前提 C：堆风水可重复** | 依赖 glibc 分配行为；不同版本/负载下需要重调 chunk 档位与 `N`。 |
| **崩溃风险** | 未命中的解码会破坏堆（DoS）。 |

---

## 8. 修复建议

1. Pillow 升级其 vendored openjpeg 到含修复的版本（或改为系统 openjpeg）。
2. openjpeg 侧：`read_sod()` 写入前对 `current_tpsno >= nb_tps` 做边界检查。
3. 部署侧：对图生图等高价值接口限制上传体积、隔离解码进程、禁止以高权限运行解码 worker。

---

## 9. 披露与免责声明（务必先读）

- 本文描述的链路针对一个**尚未在 Pillow 中修复**的内嵌依赖漏洞。
- **公开完整利用细节之前，应先完成协调披露**（Pillow 安全邮箱 / openjpeg 维护者），
  给厂商留出修复窗口。
- 本文为**本地** PoC；未授权对第三方系统使用属违法行为。
- "首个"类表述应以公开可检索的先例核实为准，本文不作此声明。

---

## 10. 相关仓库（姊妹项目）

- **本仓库**：负责**通用原语** —— 类型混淆成 memoryview ⇒ **任意读写 + 信息泄露（ASLR 归零）**。
- **姊妹仓库** [`comfyui-openjpeg-rce`](https://github.com/giaoimgiao/comfyui-openjpeg-rce)：
  同一个漏洞、同一个写入原语的**另一条执行链** —— 图片把元组的元素指针改写为攻击者缓冲区，
  缓冲区里放**假 `PyTypeObject`**（`tp_repr = system@plt`）⇒ `repr(元素)` 即执行；
  **不需要 memoryview 元数据、只需一次解码**（本仓库路线需要两次解码）。
- **两者差异对照与组合方式**见 [`RELATION.md`](https://github.com/giaoimgiao/openjpeg-j2k-oob-to-arb-rw/blob/main/RELATION.md)。
