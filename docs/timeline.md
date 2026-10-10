# 研究时间线

> 按工作阶段记录（相对顺序，非绝对日期）。目标：Pillow 12.3.0 vendored `openjpeg 2.5.4`。

## 阶段 0：起点（不是为了打 openjpeg）

- 最初目标是一个使用 ComfyUI 的生图服务，摸底其接口。
- 顺链路溯源：**ComfyUI →（依赖）Pillow →（vendored，依赖的依赖）openjpeg**。
- 结论：ComfyUI 与 Pillow 主版本的最新漏洞均已修复，唯独 Pillow wheel 内
  **vendored 的 openjpeg 未带补丁** ⇒ 选择它。

## 阶段 1：投递面摸底（10 MiB 墙）

- 上传走 **presigned URL 直传对象存储**；校验的是**声明的 fileSize**，
  且签名覆盖 `content-length` ⇒ "声明小传大" 被拒。
- 实测：`image/*` 上限 **10 MiB**；`video/mp4` 可到 ~30 MiB，但任务层
  **一律按登记大小/类型校验** ⇒ 大文件进入不了图生图任务。
- 结论：**≤10 MiB 限制的部署，天然挡住本链的 RCE 形态**（值即文件偏移，需 >10.6 MiB）。

## 阶段 2：本地复现越界写

- 用插桩版 `libopenjp2` 复现 OOB 写，确认写点公式：
  第 `k` 个越界 part 写 `tp+24k+8`（v1=该 part 的 SOD 文件偏移）与
  `tp+24k+16`（v2=下一 part 偏移−10）。
- 构造器演进：`mk5 → mk9 → mk10/mk10b → mk10c`（参数化双写）+ `calib`（迭代校准到字节）。

## 阶段 3：类型混淆

- 读回内存验证：`ob_type` 可被精确改成指定类型对象（一字节不差）。
- 反汇编 `tp_dealloc`：确认 `str`/`code` 的析构会 `Py_XDECREF` 指定字段。

## 阶段 4：错误结论与撤回

- 曾把"内存有变化"误判为"free 成功"（**假阳性**），随后以干净判据
  （对象前 16 字节是否被 tcache 改写 / 对象是否行为异常）**正式撤回**。
- 得出**结构性结论**：写值单调递增 ⇒ 地址越高的槽值越大 ⇒ **GOT 不可达**。

## 阶段 5：换面——从"找会死的受害者"到"让合法操作替我干活"

- 检讨：此前一直纠结 `dealloc`/UAF，属于**把问题定义错**。
- 转而研究**消费端**（谁来读这些字段、读来干什么），并实测各类对象的字段布局。

## 阶段 6：Data-Oriented 升级（核心）

- 发现 `memoryview.view.buf` 落在**自由槽 `+0x38`**：
  只要把邻居对象嫁接成 `memoryview`，`mv[i]` / `mv[i]=x` 即**任意读写**。
- 逐一排除：`bytearray.ob_start(+0x28)`、`list.ob_item(+0x18)`、`function.func_code(+0x30)`
  等均落在**耦合死槽**。

## 阶段 7：工程边界（踩坑）

- **`N` 必须为奇数**：victim 基址 `24N+8` 必须等于 `tp_index` 的 chunk size
  （`align(24N+8,16)`），否则错位 8 字节会踩邻居的 chunk size 字段 ⇒ `double free`。
- **只写到 stride `m=2` 就停**：否则耦合规则破坏 `view.format(+0x60)`。
- **受害者必须 >512 B**：小对象走 pymalloc，与 glibc 的 `tp_index` 永不相邻。
- **三段越界写构造器 `mk13`**：一次性写 `victim+0x08 / +0x20 / +0x38`。

## 阶段 8：本地 RCE

- 用**两次解码**：① `buf`=目标 `str` 地址 → 写命令；② `buf`=`PyUnicode_Type.tp_repr` → 写 `system`。
- 触发 `repr(str)` ⇒ `system("id")` ⇒ 本机 `uid=0(root)`。
- 细节：`repr` 会 `LOAD_GLOBAL` 一次 ⇒ `ob_refcnt` 首字节 +1（首字节写 `'h'` 以得到 `'i'`）。

## 阶段 9：打包与远程化侦察（未完成）

- 打成本地复现目录（`repro/`）与检测器（`poc/`）。
- 侦察"自然邻居"：**不布置堆**时，`tp_index` 的邻居是宿主进程的**任意缓冲**
  （实测为一串路径字符串），**不是可用对象** ⇒ 远程化路线受阻。
- 未解决：**上传 → 远程 RCE**、**ASLR 绕过**。

## 关键技术资产

| 名称 | 作用 |
|---|---|
| `builder.py` / `mk13` | 三段越界写构造器（参数化 A/B/C + 校准） |
| `repro_local.py` | 本地完整链复现（风水 + 嫁接 + 触发） |
| `poc_dos.jp2` | 上传即可触发的崩溃 PoC |
| `check_target.py` | 环境检测（版本 + 可达性） |