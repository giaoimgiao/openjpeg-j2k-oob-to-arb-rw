# repro/ 早期实验结果（保留，避免后人重走）

这批文件是 `tp_index` 越界写阶段的“破墙版”尝试，**均已实测失败**，保留作为记录：

| 文件 | 内容 | 结论 |
|---|---|---|
| `builder2.py` | 用 `SOT.Psot` 声明值抬高写入值：`end_pos = pos + (Psot-12) + 2`，想让几百字节文件写出 ~12MB 级值 | **受限**：Psot 放大后 openjpeg 报 `broken data stream`，`read_sod` 之前有流长度校验 |
| `verify2.py` | 用 ctypes 直接从 Python 堆读回目标地址，验证写入是否落地 | 工具可用，但依赖本机非 PIE 布局 |
| `stage1b.j2k` | 上述构造的最小样本（837B） | 解码报 `broken data stream` |
| `stage1.j2k` / `stage2.j2k` | 早期大文件版本（12MB 级） | 见 `docs/dead-ends.md` §4 |

结论已固定在 `docs/dead-ends.md`：值域受 `Psot` 4 字节限制（<4GB ⇒ 高 32 位恒 0），
不能表达 64 位堆地址；写 `comps` 等字段又会被 `opj_tcd_init_tile` 重置。
