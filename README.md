# J2K / openjpeg / Pillow：受限越界写 → 任意内存读写 的升级研究

> **EN**: Escalating a *known* out-of-bounds write in openjpeg (vendored in Pillow)
> into arbitrary memory read/write via data-oriented object grafting.

## 研究范式（修订）：从「单点精密构造」转向「声明-使用差集」普查

前 20 多轮的做法是“精密技巧”：24 字节步长对齐、`delta%24`、`nb_tps`、
塑形、逐槽无害性。每一条都要为当前这台机器、这个 glibc、这个宿主单独校准一次 ——
**调好也只能用一次**，这正是它不具备通用性的原因。

改成普查后，研究的单位从“一个构造”变成“一个类别”：

```
文件声明的数量 N_decl   → 决定分配
文件实际给出的数量 N_use → 决定写入下标 / 拷贝长度
当 N_use > N_decl ⇒ 越界；若越界值来自文件字节，则【不需要地址、不受 ASLR 限制】
```

`read_sod` 的 `tp_index` 只是这一类里的一个实例（它的特殊之处是越界值 = 文件偏移，
所以只能写小整数）。普查的目标是找**越界值 = 文件字节**的实例，那类天生通用。

普查工具与判据：

- `tools/census.py`：抽出「分配数量」与「循环上界」不同源的配对（含文件:行）。
  第一版判据（标识符不同）噪声大，需叠加“两者均为独立解析的文件字段”。
- `tools/guard_alloc.c`：`LD_PRELOAD` 分配器，块尾贴 `PROT_NONE` 页，
  覆盖 `malloc/calloc/realloc` 与 `posix_memalign/aligned_alloc/memalign`。
  **判据只有一条：崩溃点是否落在 `read_sod` 之外**（T1/DWT/apply_pclr/packet 解析）。
  它不看版本、不看地址、不需要大文件。

交付物也不止 RCE：一个跨版本稳定、无需 ASLR、上传即崩的解析器缺陷（CVE 层面）
本身即有效成果；RCE 作为持续研究，不作为阻塞项。

---

## 0. 这是什么（先说准确）

**从ComfyUI 为入口，确认它依赖 Pillow，而 Pillow 又捆绑了有漏洞的 OpenJPEG**

- **OpenJPEG漏洞本体是已知的、公开跟踪的**：openjpeg 的 J2K 越界写
  （`read_sod()` 中 `tp_index[current_tpsno]` 越界；对应 OSV-2025-219 / openjpeg PR#9520 一类）。
  **本仓库不主张任何 0-day。**
- **本仓库新增的是「利用技术」**：公开资料里这一处基本止于崩溃型 PoC，
  而这里给出的是**把受限越界写升级为任意内存读写、并推到本地 RCE 的完整方法论**
  （数据导向 / 对象嫁接），以及过程中的全部判据与踩坑。
- **适用范围**：这是一条**本地进程内**链路（需要执行点 + 固定地址），**不是远程利用**；
  远程化与 ASLR 绕过**未解决**。
- **在真实服务上的实际后果**：解码进程**崩溃或卡死**。是否构成可用 DoS，
  取决于部署（上传配额、解码是否隔离进程、是否自动重启等），不宜夸大。

仓库中的脚本是**本地复现脚本**，目的是让这套机制可被验证与讨论。

---

## 1. 结论速览

| 能力 | 状态 | 位置 |
|---|---|---|
| J2K 文件 → 可达越界写 | ✅ | `WRITEUP.md` §2 |
| 文件 → 解码进程崩溃 / 卡死 | ✅ | `poc/poc_dos.jp2` |
| 受限越界写 → 类型混淆 → 任意读写 | ✅ 本地实证 | `repro/` |
| 任意读写 → 本地 RCE（`uid=0`） | ✅ 本地实证 | `repro/repro.sh` |
| 受限越界写 → 任意地址 free | ✅ 本地实证 | `docs/dead-ends.md` §1 |
| `comps` 指向 payload 假结构 → 像素写 GOT | ❌ 源码级证伪 | `docs/dead-ends.md` §2.1 / §2.2 |
| 上传 → 远程 RCE | ❌ 未解决 | `WRITEUP.md` §7 |
| ASLR 绕过 | ❌ 未解决 | `WRITEUP.md` §7 |

---

## 2. 漏洞与目标

- **目标**：Pillow 12.3.0 wheel 内 **vendored** 的 `openjpeg 2.5.4`
  （`.../pillow.libs/libopenjp2-*.so`）。上游修复不会自动进入 Pillow 的构建产物 ——
  **下游 vendored 副本的滞后**正是本类问题值得单独指出的原因。
- **根因**：`j2k.c` 的 `read_sod()` 按 **TLM 声明的 tile-part 数** 分配 `tp_index` 数组，
  却按 **SOT 的 `TPsot`** 递增写入 ⇒ 越界写两个 8 字节值（内容为文件偏移量）。

细节、推导与反汇编见 [`WRITEUP.md`](WRITEUP.md)。

---

## 3. 仓库结构

```
.
├── WRITEUP.md              完整技术报告（原语、方法论、踩坑、限制）
├── README.md               本文件
├── docs/
│   ├── timeline.md         研究时间线
│   ├── status.md           漏洞状态、影响描述与缓解
│   ├── dead-ends.md        ★死路清单与源码级证伪（动手前必读）
│   └── findings-raw.md     原始标定数据（含已作废结论，仅存档）
├── poc/
│   ├── poc_dos.jp2         解码进程崩溃 PoC
│   └── check_target.py     环境检测器（版本 + 可达性）
└── repro/                  本地复现脚本
    ├── repro.sh            一键（本地）
    ├── repro_local.py      主复现逻辑
    ├── builder.py          三段越界写构造器（J2K 生成）
    └── base.j2k            403 B 最小 4-tile 基础图
```

---

## 4. 快速开始

### 4.1 检测目标是否受影响（只读）

```bash
python3 poc/check_target.py
python3 poc/check_target.py --python /opt/conda/bin/python
```

判定：子进程解码 `poc_dos.jp2` 后**异常退出（负 rc）** ⇒ 存在该越界写；
`DECODE_OK` ⇒ 不受影响 / 已修。

### 4.2 崩溃复现

`poc/poc_dos.jp2` 交给任何用 PIL 解码 JP2/J2K 的入口即可（例如 ComfyUI 的 `Load Image`）。

### 4.3 本地完整链复现（需要在本机执行 Python）

```bash
bash repro/repro.sh
# 期望：tp_repr 槽 = <system> ... uid=0(root) ...
```

> `repro/` 依赖**本机固定地址**（Python 基址 `0x400000`、无 ASLR）与具体 glibc 版本；
> 换环境需重新校准偏移与 chunk 档位（方法见 `WRITEUP.md` §4）。

---

## 5. 限制

| 项 | 说明 |
|---|---|
| 远程性 | ❌ 需要目标机上的执行点；"上传即 RCE" 未打通 |
| ASLR | ❌ 全程固定绝对地址 |
| 文件体积 | RCE 链需 ~11–13 MB（值即文件偏移→ 也就是说:目标服务器需要允许上传10M以上的图片，才可RCE|
| 通用性 | 依赖 glibc 分配行为与进程堆历史，换环境需重调 |
| 实际危害 | 解码进程崩溃 / 卡死；是否可用取决于部署侧的配额与进程隔离 |
| 已证伪路线 | 像素写 GOT、`comps`→fake、tcache 投毒、UAF 别名 —— 见 [`docs/dead-ends.md`](docs/dead-ends.md) §3，勿重复投入 |

---

## 6. 研究要点（方法论）

1. **受限原语刻画**：自由槽 `≡8 (mod 24)`、耦合死槽 `= 前一自由槽+2`、
   以及**单调约束**（地址越高的槽，值必然越大 ⇒ GOT 不可达）。
2. **Data-Oriented 升级**：把邻居对象**嫁接成 `memoryview`**，用解释器正常逻辑
   （`mv[i]` / `mv[i]=x`）得到任意读写 —— **不需要 free / UAF / GOT / ROP**。
3. **工程边界**：`N` 必须为奇数（chunk size 对齐）；受害者必须 >512 B
   （否则走 pymalloc，与 glibc 的 `tp_index` 永不相邻）；只写到 stride `m=2` 就停。
4. **自然邻居侦察结论**：**不布置堆**时，`tp_index` 的邻居是宿主进程的**任意缓冲**
   （实测为一串路径字符串）⇒ "让程序自己使用被污染对象"这条路在通用场景不成立，
   这正是远程化未解决的原因。

---

## 7. 免责

仅用于**授权的安全研究与教学**。未经授权对第三方系统进行测试或攻击属违法行为。
