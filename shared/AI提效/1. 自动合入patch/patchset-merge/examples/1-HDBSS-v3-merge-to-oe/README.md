本次测试条件：蓝区+opencode+deepsek v4 pro

用户测试指令：将/mnt/shared/originPatch/HDBSS_v3合入到/root/code/openeuler/kernel仓库下，没有源仓库

交互内容：子agent分析完后询问执行策略（选择特性完全revert后再merge的策略）

# HDBSS v3 Patchset 自动合入测试

## 测试概要

| 项 | 值 |
|----|-----|
| 测试日期 | 2026-05-22 |
| 补丁来源 | `/mnt/shared/originPatch/HDBSS_v3/` (mbox 格式，来自 lore.kernel.org) |
| 目标仓库 | `/root/code/openeuler/kernel` (openEuler OLK-6.6 arm64) |
| 目标分支 | `patch-hdbss-v3` |
| 原始 Patchset | [PATCH v3 0/5] Support the FEAT_HDBSS introduced in Armv9.5 |
| 合并策略 | C: 回退本地实现 → 合入全部 |
| 编译目标 | `make ARCH=arm64 Image` |
| 编译结果 | ✅ 全部通过 |

## 合入过程

### 第 1 步：分析阶段 (Phase 0-1)

并行分析发现目标内核 OLK-6.6 已存在 HDBSS 本地实现（通过 `CONFIG_ARM64_HDBSS` 保护），共 10 个 commit（分布于 2 个 merge commit）。分析结论：现有实现与 v3 patchset 在数据结构、函数位置、刷新机制等方面存在结构性冲突。

### 第 2 步：回退现有实现 (PRE_REVERT)

通过 `git revert -m 1` 逆序撤销 2 个 merge commit：

| 顺序 | Revert Commit | 撤销内容 |
|------|-------------|---------|
| 1st | b1d8169dd540 (!17748) | HDBSS bugfix (NVHE 排除 + 内存泄漏修复) |
| 2nd | fe4fa7481191 (!15754) | HDBSS feature 主题分支 (6 个 commit) |

回退过程中产生 6 个文件冲突，已逐个手动解决。

### 第 3 步：串行合入 (Phase 2)

每个 patch 执行 `APPLY → BUILD → COMMIT` 链条，5 个 patch 全部成功：

| Seq | Commit | 文件 | 行数 | 冲突 | 编译 |
|-----|--------|------|------|------|------|
| 0001 | sysreg HDBSS 寄存器定义 | 2 | +31 | 上下文 GCSPR_EL2 不存在，手动插入 | ✅ |
| 0002 | DBM 属性支持 | 2 | +10 | API 差异：BIT(4) 替代 BIT(6)，HI 宏位置不同 | ✅ |
| 0003 | FEAT_HDBSS cpufeature | 5 | +22 | KVM_CAP 编号适配，全部文件上下文不匹配 | ✅ |
| 0004 | HDBSS 核心实现 | 8 | +207 | API 差异：vtcr 字段、guard() 宏、vcpu_load/put 替代 vhe switch | ✅ |
| 0005 | ioctl 文档 | 1 | +16 | 上下文行号差异 | ✅ |

### 第 4 步：关键适配

补丁 0004 是核心实现，因目标内核 API 差异需 7 处适配：

| # | 原始代码 | 目标内核适配 | 原因 |
|---|---------|------------|------|
| 1 | `guard(write_lock_irqsave)` | `unsigned long flags; write_lock_irqsave/unlock` | 目标内核无 rwlock guard 定义 |
| 2 | `kvm_vcpu_load_vhe/put_vhe` | `kvm_arch_vcpu_load/put` | 目标内核无 VHE 专用加载函数 |
| 3 | `kvm->arch.mmu.vtcr` | `kvm->arch.vtcr` | struct kvm_arch 中 vtcr 位置不同 |
| 4 | `VTCR_EL2_HDBSS` | 新增宏 `(1ULL << 39)` | 目标内核缺少此定义 |
| 5 | `esr_brk_comment()` 之后 | `esr_is_data_abort()` 之前 | esr.h 缺少该函数 |
| 6 | `vncr_tlb` 字段后 | `reset_state` 字段后 | 目标内核无 NV(Nested Virtualization) |
| 7 | `kvm_vcpu_get_esr(vcpu)` | 同上（一致） | 使用 ESR 访问器而非直接访问 |

## 文件清单

| 文件 | 说明 |
|------|------|
| `0001-0002-*.patch` | Revert 阶段的 2 个 git format-patch |
| `0003-0007-*.patch` | Merge 阶段的 5 个 git format-patch |
| `summary.md` | 详细合并汇总报告 |
| `analysis_cache.json` | Phase 1 并行分析缓存 |
| `merge_tasks.json` | Phase 1.5 合并任务调度 |
| `patchset.metadata.json` | patchset 元数据 |
| `original_patches/` | 原始 .mbox 补丁文件 |

## 测试结论

- **成功**：5 个 patch 全部成功合入，编译验证通过
- **策略**：采用「场景 C（回退本地实现 → 合入全部）」策略，先 revert 2 个 merge commit 撤销现有 HDBSS 实现，再逐 patch 应用 v3 patchset
- **复杂度**：补丁 0004 涉及 8 个文件、需 7 处 API 适配，是本次合入的核心难点
- **风险提示**：HDBSS 功能需在 Armv9.5+ 硬件上进行功能验证（脏页迁移场景）
