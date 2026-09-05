---
name: arm-kvm-style
description: ARM KVM (arch/arm64/kvm) 代码与 commit 风格指南。在编写、修改 arch/arm64/kvm/ 或 virt/kvm/ 下的代码和 commit message 时使用。涵盖 commit message 格式、代码命名、注释风格、内存序、寄存器操作等约定。
---

# ARM KVM 代码与 Commit 风格指南

本 skill 从 linux 主线 `arch/arm64/kvm/` 的 commit 历史、代码，以及 Linux 内核通用提交规范（submitting-patches）中蒸馏而来，适用于在该子系统中编写代码和 commit message。

---

## 零、Linux 内核通用提交规范

以下规则来自 [Submitting patches](https://www.kernel.org/doc/html/latest/process/submitting-patches.html)，适用于所有内核子系统，ARM KVM 也遵循。

### 0.1 一个 patch 只做一件事

- 每个 patch 包含一个 **逻辑变更**，能独立理解和验证
- Bug fix 和性能优化分开；API 变更和使用该 API 的新代码分开
- 一个逻辑变更跨多个文件时，仍合为一个 patch
- 系列中每个 patch 必须 **可独立编译和运行**（`git bisect` 友好）
- 如果 patch B 依赖 patch A，在描述中注明 "this patch depends on patch A"
- 一次提交不超过 ~15 个 patch，等待 review 后再发下一批

### 0.2 Commit Message Body 写作原则

- **描述问题**：无论 patch 大小，必须说明要解决什么问题。说服 reviewer 这值得修
- **描述用户可见的影响**：崩溃、死锁、性能回退、延迟毛刺、dmesg 输出等。很多 stable 维护者只从 upstream cherry-pick，要提供足够信息帮助他们路由
- **量化优化和权衡**：声称性能/内存/栈/二进制大小改善时，附数字。也说明非显而易见的代价（CPU vs 内存 vs 可读性的权衡）
- **技术细节**：问题确立后，用 plain English 描述具体做了什么，让 reviewer 验证代码行为符合意图
- **祈使语气**：写 "make xyzzy do frotz" 而非 "[This patch] makes xyzzy do frotz" 或 "[I] changed xyzzy to do frotz"
- **自包含**：每次提交或重新提交时，包含完整的 patch 描述和理由。不要只说 "this is version N"，不要指望维护者去翻之前的版本
- **每行 75 字符换行**（tag 行例外，tag 不换行以便脚本解析）

### 0.3 引用其他 commit

- 不要只写 SHA-1，必须同时附 one-line summary：
  ```
  Commit e21d2170f36602ae2708 ("video: remove unnecessary platform_set_drvdata()")
  removed the unnecessary platform_set_drvdata(), but left the variable "dev" unused.
  ```
- SHA-1 至少用 **12 位**（内核仓库对象极多，短 hash 碰撞是真实风险）

### 0.4 Link / Closes / Fixes tag

- `Link:` 指向 lore.kernel.org 邮件存档（去掉 Message-ID 的尖括号）：
  ```
  Link: https://lore.kernel.org/30th.anniversary.repost@klaava.Helsinki.FI
  ```
- `Closes:` 指向 bug tracker 或邮件列表中的 bug 报告
- `Fixes:` 格式：至少 12 位 hash + 引号包裹的 one-line summary，**不折行**：
  ```
  Fixes: 54a4f0239f2e ("KVM: MMU: make kvm_mmu_zap_page() return the number of pages it actually freed")
  ```
- 推荐 git config：
  ```ini
  [core]
          abbrev = 12
  [pretty]
          fixes = Fixes: %h (\"%s\")
  ```

### 0.5 Tag 使用规则

| Tag | 含义 | 需要本人许可？ |
|-----|------|---------------|
| `Signed-off-by:` | 开发者证书来源（DCO），表示你写了或有权传递此 patch | 是（自己签自己的） |
| `Reviewed-by:` | 进行了技术审查，认为可接受 | 是 |
| `Tested-by:` | 在某个环境测试通过 | 是 |
| `Acked-by:` | 认可此 patch（通常是子系统维护者或利益相关方），比 Reviewed-by 非正式 | 是 |
| `Reported-by:` | 报告了 bug | 否（公开报告即可） |
| `Suggested-by:` | 提出了 patch 的想法 | 否（公开建议即可） |
| `Cc:` | 记录被通知的人（未提供评论） | 否 |
| `Co-developed-by:` | 共同作者，每个 Co-developed-by 后必须紧跟该人的 Signed-off-by | 是 |
| `Assisted-by:` | 使用了 AI 编码辅助工具时必须标注 | 否 |
| `Closes:` | 关闭 bug 报告 | 否 |

- `Reported-by:` 后应紧跟 `Closes:` 指向报告链接
- 添加 `Tested-by` / `Reviewed-by` / `Acked-by` 等 tag 需要本人明确许可
- 如果 patch 大幅修改导致之前的 Reviewed-by 不再适用，应移除该 tag 并在 changelog 中说明

### 0.6 Patch 格式

```
Subject: [PATCH 001/123] subsystem: summary phrase

From: Patch Author <author@example.com>     # 仅当提交者不是作者时需要

<解释正文，75 字符换行>

Signed-off-by: Author <author@mail>
---
V2 -> V3: Removed redundant helper function
V1 -> V2: Cleaned up coding style and addressed review comments

v2: https://lore.kernel.org/bar
v1: https://lore.kernel.org/foo

 path/to/file | 5 +++--
 1 file changed, 3 insertions(+), 2 deletions(-)

<diff>
```

- Subject 格式：`[PATCH vN M/N] subsystem: condensed summary`
- Summary 不超过 70-75 字符，是 patch 的全局唯一标识符
- `---` 标记之后的内容不会进入 git changelog，用于放 diffstat、版本变更记录
- 版本变更记录放在 `---` 之后，方便 `git am` 自动剥离

### 0.7 Commit Message 中的 Backtrace

- Backtrace 有助于记录问题调用链，但要 **精简**
- 不要贴完整 dmesg（时间戳、模块列表、寄存器 dump 是噪音）
- 只保留关键错误信息 + 调用链：
  ```
  unchecked MSR access error: WRMSR to 0xd51
  Call Trace:
   mba_wrmsr
   update_domains
   rdtgroup_mkdir
  ```

### 0.8 代码风格检查

- 提交前用 `scripts/checkpatch.pl` 检查
- checkpatch 三级：ERROR（很可能错）、WARNING（需仔细审查）、CHECK（需思考）
- checkpatch 是指导而非教条——如果违反规则但代码看起来更好，可以保留，但要能辩护
- 移动代码到新文件时，**不要同时修改移动的代码**，保持 move 和 change 分离

### 0.9 Base tree 信息

- 使用 `git format-patch --base=auto` 自动生成 `base-commit:` trailer
- 放在 cover letter 或系列第一个 patch 的 `---` 之后
- base commit 必须在公开的维护者/mainline 树中可找到

### 0.10 邮件提交

- **纯文本**：不用 MIME、不用附件、不压缩
- 用 `git send-email` 内联发送
- 回复使用 **trimmed interleaved replies**（不要 top-posting）

---

## 一、ARM KVM 子系统 Commit 规范

以下规则是 ARM KVM 子系统在通用规范之上的特定约定。

### 1.1 Subject Line（主题行）

格式：`KVM: arm64: <子系统>: <祈使句描述>`

- **前缀固定为 `KVM: arm64:`**，后接可选的子子系统前缀
- 子子系统前缀示例：`vgic:`、`vgic-v3:`、`vgic-its:`、`GICv2:`、`ptdump:`、`selftest:`、`selftests:`
- 无子子系统时直接写动作：`KVM: arm64: Fix timer offsets for non-protected VMs`
- **祈使语气**，首字母大写，末尾无句号
- 常用动词：`Add`、`Fix`、`Remove`、`Make`、`Handle`、`Don't`、`Drop`、`Preserve`、`Prevent`、`Reject`、`Validate`、`Engage`、`Relax`、`Split`、`Expose`、`Consider`、`Plumb`、`Convert`、`Rename`、`Factor out`、`Move`
- 长度控制在 50~72 字符
- 描述 **做了什么**，不是为什么做

示例：
```
KVM: arm64: vgic: Prevent speculative SPI array underflow
KVM: arm64: Fix hvhe and broken CNTVOFF_EL2
KVM: arm64: Add NVHCR_EL2 context switching
KVM: arm64: Don't WARN on pKVM stage-2 map failures
KVM: arm64: Make timer_get_offset() work in all contexts
KVM: arm64: vgic-its: Don't dereference a NULL collection on ITT save
```

### 1.2 Body（正文）

结构：**问题描述 → 根因分析 → 解决方案**

- 首段描述 **当前行为和它的问题**，引用具体的函数名、数据结构、代码路径
- 中段解释 **为什么会出问题**，引用 ARM 架构规范（寄存器名、特性名）
- 末段说明 **本 patch 如何解决**，用祈使句
- 使用 ARM 架构术语：EL1/EL2、VTCR_EL2、HCR_EL2、stage-1/stage-2、VNCR、TLBI、BBM（break-before-make）、CMO（cache maintenance operation）等
- 每段 72 字符左右换行

示例正文结构：
```
<函数名>() 在 <场景> 下会 <问题行为>。当 <条件> 时，
<具体机制> 导致 <后果>。

<根因解释，引用架构特性或寄存器>。

<解决方案>。<具体做法>。这样 <好处>。
```

### 1.3 ARM KVM Tag 顺序

ARM KVM 子系统的 tag 排列惯例（在通用规范 0.5 基础上）：

```
Fixes: <12位hash> ("<原始subject>")
Cc: stable@vger.kernel.org
Link: https://lore.kernel.org/... 或 https://patch.msgid.link/...
Reported-by: ...
Suggested-by: ...
Signed-off-by: <作者>
Reviewed-by: ...
Tested-by: ...
Acked-by: ...
Link: https://patch.msgid.link/...   # patch 的 message-id 链接
Signed-off-by: <维护者>
```

ARM KVM 维护者（最后的 Signed-off-by）：
- Oliver Upton `<oupton@kernel.org>`
- Will Deacon `<will@kernel.org>`
- Marc Zyngier `<maz@kernel.org>`（review）

多个 `Fixes:` 可并列。`Link:` 可出现两次：一次指向讨论，一次指向 patch message-id。

### 1.4 Merge Commit 风格

- 以功能领域分组，用 bullet list 描述每组变更
- 每组标注主要贡献者
- 示例：
```
KVM/arm64 changes for 7.3

 - Add support for 'slot' based PMU events, paired with new UAPI that
   compels the user to select a specific PMU implementation (Congkai Tan)

 - Lazy save/restore of vCPU state for pKVM, along with various fixes
   and cleanups (Fuad Tabba)
```

---

## 二、代码风格

### 2.1 文件头

```c
// SPDX-License-Identifier: GPL-2.0-only
/*
 * <一句话描述文件职责>
 *
 * Copyright (C) <年份> <公司>
 * Author: <姓名> <<email>>
 */
```

- 允许在文件头注释中加入一句简短的幽默（如 `No bombay mix was harmed in the writing of this file.`），但不强制

### 2.2 命名约定

| 类别 | 前缀/模式 | 示例 |
|------|-----------|------|
| stage-2 页表函数 | `stage2_*` | `stage2_set_prot_attr()`, `stage2_try_break_pte()` |
| hyp stage-1 函数 | `hyp_*` | `hyp_map_walker()`, `hyp_set_prot_attr()` |
| 通用页表函数 | `kvm_pgtable_*` | `kvm_pgtable_walk()`, `kvm_pgtable_stage2_map()` |
| VGIC 函数 | `vgic_*` / `__vgic_*` | `vgic_v3_save_pending_tables()` |
| Walker 回调 | `<子系统>_*_walker` | `stage2_map_walker()`, `stage2_unmap_walker()` |
| 叶子节点尝试 | `*_try_leaf` | `stage2_map_walker_try_leaf()`, `hyp_map_walker_try_leaf()` |
| 布尔判断函数 | 描述性名称 | `kvm_pte_table()`, `stage2_pte_cacheable()`, `kvm_block_mapping_supported()` |
| 数据结构 | `<子系统>_data` | `struct stage2_map_data`, `struct hyp_map_data` |
| 宏 | 全大写 | `KVM_S2_MEMATTR()`, `KVM_PTE_LEAF_ATTR_LO_S2_S2AP_R` |

### 2.3 函数风格

- **static** 用于文件内部函数，非 static 仅用于需要跨文件导出的接口
- 返回负错误码：`-EINVAL`、`-ENOMEM`、`-ERANGE`、`-EAGAIN`、`-E2BIG`
- `-EAGAIN` 专用于 PTE 竞态（walker 检测到 PTE 已被其他路径修改）
- 错误检查后立即 return，不嵌套深层 if-else
- 变量声明在函数顶部或代码块顶部（C99 风格，可在声明处初始化）

### 2.4 结构体初始化

使用 designated initializer，tab 对齐：

```c
struct kvm_pgtable_walker walker = {
    .cb      = stage2_map_walker,
    .flags   = KVM_PGTABLE_WALK_TABLE_PRE | KVM_PGTABLE_WALK_LEAF,
    .arg     = &map_data,
};
```

### 2.5 寄存器操作

- 使用 `FIELD_PREP()` 构造寄存器字段，`FIELD_GET()` 提取字段
- 使用架构定义的宏/常量，不硬编码 magic number
- 位域操作示例：
```c
attr |= FIELD_PREP(KVM_PTE_LEAF_ATTR_LO_S1_ATTRIDX, mtype);
ap = FIELD_GET(KVM_PTE_LEAF_ATTR_LO_S1_AP, pte);
```

### 2.6 内存序与并发

- 使用 `READ_ONCE()` / `WRITE_ONCE()` 标记无锁共享的 PTE 访问
- 使用 `smp_store_release()` 发布新的 PTE（保证之前的写入对读者可见）
- 使用 `cmpxchg()` 实现 lock-free PTE 更新（stage2_try_set_pte）
- TLB 无效化后使用 `dsb(ishst)` + `isb()` 确保完成
- 页表 walk 结束后视情况使用 `dsb(ishst)` 屏障

### 2.7 错误处理与断言

- `WARN_ON()` / `WARN_ON_ONCE()` 用于不应发生但可恢复的条件
- `WARN_ON()` 返回值用于调试，不用于控制流
- 对不可能路径使用 `unreachable()`
- 对 guest 可控的条件不使用 `WARN`（guest 不应能触发 kernel warning）

---

## 三、注释风格

### 3.1 行内注释

- 使用 `/* ... */` 风格，不使用 `//`
- 注释解释 **WHY**，不解释 WHAT
- 引用 ARM 架构概念时使用缩写并首次展开（如 BBM = break-before-make）
- 示例：
```c
/*
 * Skip updating the PTE if we are trying to recreate the exact
 * same mapping or only change the access permissions.
 */
```

### 3.2 函数级注释

- 导出函数使用 kernel-doc 格式（`/**`）
- 内部 static 函数通常不加 kernel-doc，用普通 `/* */` 或无注释
- 示例：
```c
/**
 * stage2_try_break_pte() - Invalidates a pte according to the
 *                          'break-before-make' requirements of the
 *                          architecture.
 *
 * @ctx: context of the visited pte.
 * @mmu: stage-2 mmu
 *
 * Returns: true if the pte was successfully broken.
 */
```

### 3.3 幽默注释

ARM KVM 代码中偶尔出现幽默/俏皮的注释，这是该子系统的文化特征：

```c
/* No bombay mix was harmed in the writing of this file. */
/* Here be dragons. */
/*
 * "But where's the TLBI?!", you scream.
 * "Over in the core code", I sigh.
 */
```

- 仅在确实合适时使用，不刻意添加
- 不影响技术准确性

### 3.4 架构引用

- 引用 ARM 寄存器时写全称：`VTCR_EL2`、`HCR_EL2`、`ICH_VTR_EL2`
- 引用 ARM 特性时写：`FEAT_NV2p1`、`FEAT_TLBIRANGE`、`FEAT_NV3`
- 引用架构概念时使用标准缩写：BBM、CMO、FWB、VNCR、TLBI
- 引用架构文档时说 "As per the ARM GICv3 spec" 或 "The architecture requires..."

---

## 四、代码组织

### 4.1 文件划分

- `hyp/pgtable.c`：stage-1 和 stage-2 页表操作的核心实现
- `hyp/nvhe/`：非 VHE 模式下的 hypervisor 代码
- `hyp/vhe/`：VHE 模式下的代码
- `hyp/vgic-v3-sr.c`：VGIC v3 save/restore
- `vgic/`：VGIC 通用逻辑
- `hyp/nvhe/sys_regs.c`：系统寄存器处理

### 4.2 Walker 模式

页表操作统一使用 walker 回调模式：

```c
struct kvm_pgtable_walker walker = {
    .cb    = my_walker,
    .flags = KVM_PGTABLE_WALK_LEAF | KVM_PGTABLE_WALK_TABLE_POST,
    .arg   = &my_data,
};
ret = kvm_pgtable_walk(pgt, addr, size, &walker);
```

Walker 回调签名：
```c
static int my_walker(const struct kvm_pgtable_visit_ctx *ctx,
                     enum kvm_pgtable_walk_flags visit)
```

### 4.3 Break-Before-Make 模式

Stage-2 页表更新遵循 BBM：
1. `stage2_try_break_pte()` — 锁定并无效化旧 PTE，执行 TLBI
2. 执行 CMO（如需要）
3. `stage2_make_pte()` — 用 `smp_store_release()` 安装新 PTE

---

## 五、检查清单

### 提交前检查（通用规范）

- [ ] 一个 patch 只做一件事，可独立编译运行（`git bisect` 友好）
- [ ] Body 描述了问题、用户可见影响、技术方案
- [ ] Body 使用祈使语气（"make xyzzy do frotz"），非 "[This patch]..."
- [ ] 每行 75 字符换行（tag 行除外）
- [ ] 引用其他 commit 时包含至少 12 位 hash + one-line summary
- [ ] Bug fix 包含 `Fixes:` tag（12 位 hash + 引号包裹 subject，不折行）
- [ ] `Reported-by:` 后跟 `Closes:` 链接
- [ ] `Link:` 指向 lore.kernel.org 或 patch.msgid.link
- [ ] 使用了 AI 辅助工具时包含 `Assisted-by:` tag
- [ ] 需要 stable 回移时包含 `Cc: stable@vger.kernel.org`
- [ ] 运行 `scripts/checkpatch.pl` 无 ERROR
- [ ] 邮件纯文本发送，不用 MIME/附件
- [ ] 版本变更记录放在 `---` 之后

### 提交前检查（ARM KVM 子系统）

- [ ] Subject 以 `KVM: arm64:` 开头，可选子子系统前缀（`vgic:`、`ptdump:` 等）
- [ ] Subject 祈使语气，首字母大写，无句号，50~72 字符
- [ ] Body 解释了 WHY（架构行为、竞态条件），不只是 WHAT
- [ ] Tag 顺序正确（Fixes → Cc stable → Link → Reported-by → Signed-off-by → Reviewed-by → 维护者 Signed-off-by）
- [ ] 维护者 sign-off 在最后（Oliver Upton / Will Deacon）

### 写代码前检查

- [ ] 函数命名遵循子系统前缀约定（`stage2_*` / `hyp_*` / `kvm_pgtable_*` / `vgic_*`）
- [ ] 使用 `FIELD_PREP/FIELD_GET` 操作寄存器字段
- [ ] PTE 写入使用 `WRITE_ONCE` 或 `smp_store_release`
- [ ] TLB 无效化后 `dsb(ishst)` + `isb()`
- [ ] 错误返回负 error code（`-EINVAL`、`-ENOMEM`、`-EAGAIN` 等）
- [ ] `-EAGAIN` 仅用于 PTE 竞态
- [ ] 注释解释 WHY 而非 WHAT
- [ ] 不硬编码架构常量，使用架构定义的宏
- [ ] Guest 可控条件不使用 `WARN_ON`
- [ ] 使用 `static` 限制文件内部函数作用域
