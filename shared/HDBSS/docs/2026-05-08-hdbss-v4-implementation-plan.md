# HDBSS V4 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 在干净环境下合入 HDBSS v3 代码，并按顺序实现 v4 改进项

**架构：** 分步骤执行：先修复简单问题，再 revert/merge HDBSS 代码，然后逐步实现复杂功能

**技术栈：** Linux Kernel KVM/arm64, HDBSS/HACDBS

**文档目录：** `/mnt/shared/HDBSS/docs/`

---

## 第一阶段：简单修复（独立于 HDBSS 代码改动）

### Task 1.1: HDBSSBR_EL2 define 修复

**文件：**
- 修改: `arch/arm64/tools/sysreg`

**说明：** 把 `GENMASK(55, 12 + sz)` 替换为 `HDBSSBR_EL2_BADDR_MASK`

- [ ] **Step 1: 查看当前 HDBSSBR_EL2 定义**

```bash
grep -n "HDBSSBR_EL2" /root/openeuler/kernel/arch/arm64/tools/sysreg | head -20
```

- [ ] **Step 2: 确认 BADDR_MASK 的定义**

```bash
grep -n "BADDR_MASK\|BADDR" /root/openeuler/kernel/arch/arm64/tools/sysreg | head -10
```

- [ ] **Step 3: 修改 define**

将 `GENMASK(55, 12 + sz)` 替换为 `HDBSSBR_EL2_BADDR_MASK`

- [ ] **Step 4: 验证修改**

```bash
git diff arch/arm64/tools/sysreg
```

- [ ] **Step 5: 提交**

```bash
git add arch/arm64/tools/sysreg
git commit -m "arm64/sysreg: fix HDBSSBR_EL2 BADDR mask definition"
```

---

### Task 1.2: size → order 命名修改

**文件：**
- 修改: `arch/arm64/kvm/` 中相关文件

**说明：** enable 函数中把 size 参数改成 order，避免歧义

- [ ] **Step 1: 查找 size 参数位置**

```bash
grep -rn "hdbss.*size\|size.*hdbss" /root/openeuler/kernel/arch/arm64/kvm/ --include="*.c" --include="*.h" | head -20
```

- [ ] **Step 2: 确认需要修改的函数**

典型修改：函数参数 `size_t size` → `unsigned int order`

- [ ] **Step 3: 修改参数命名**

- [ ] **Step 4: 验证修改**

```bash
git diff arch/arm64/kvm/
```

- [ ] **Step 5: 提交**

```bash
git add arch/arm64/kvm/
git commit -m "KVM: arm64: rename size to order in HDBSS enable function"
```

---

### Task 1.3: flush 触发位置调整

**文件：**
- 修改: `arch/arm64/kvm/mmu.c` 或 `arch/arm64/kvm/handle_exit.c`

**说明：** 调整 HDBSS flush 触发位置，保证函数干净性

- [ ] **Step 1: 查看当前 flush 触发位置**

```bash
grep -n "hdbss.*flush\|flush.*hdbss\|hdbss_flush" /root/openeuler/kernel/arch/arm64/kvm/*.c | head -20
```

- [ ] **Step 2: 分析当前代码路径**

- [ ] **Step 3: 调整 flush 位置**

- [ ] **Step 4: 验证修改**

```bash
git diff arch/arm64/kvm/
```

- [ ] **Step 5: 提交**

```bash
git add arch/arm64/kvm/
git commit -m "KVM: arm64: adjust HDBSS flush trigger position"
```

---

## 第二阶段：Revert v1 HDBSS + 合入干净 v3

### Task 2.1: 创建 revert 分支

- [ ] **Step 1: 确认当前分支状态**

```bash
git status
git log --oneline -5
```

- [ ] **Step 2: 创建新分支**

```bash
git checkout -b hdbss-v4-clean
```

- [ ] **Step 3: 记录原始提交历史**

```bash
git log --oneline 16ab2a2fee8b..HEAD | grep -i "hdbss\|hdb"
```

需要 revert 的提交：
```
b1d8169dd540 - fix bug in hdbss
00c93102b328 - fix memory leak in HDBSS
a5e3c939fbb1 - do not support hdbss in nvhe
fe4fa7481191 - v3 Support the FEAT_HDBSS (merge commit)
8d2e1e3b26a9 - arm64/config: add config
6d60015590c3 - arm64/kvm: support to handle HDBSSF event
bd6106e348d7 - arm64/kvm: using ioctl to enable/disable
16ab2a2fee8b - arm64/sysreg: add HDBSS register info
```

- [ ] **Step 4: 提交**

```bash
git commit -m "Start HDBSS v4 development on clean branch"
```

---

### Task 2.2: Revert 所有 HDBSS 相关提交

- [ ] **Step 1: Revert 非 merge 提交（倒序）**

```bash
git revert --no-commit b1d8169dd540
git revert --no-commit 00c93102b328
git revert --no-commit a5e3c939fbb1
git revert --no-commit 8d2e1e3b26a9
git revert --no-commit 6d60015590c3
git revert --no-commit bd6106e348d7
git revert --no-commit 16ab2a2fee8b
```

- [ ] **Step 2: 处理 merge 提交 fe4fa7481191**

```bash
git revert --no-commit -m 1 fe4fa7481191
```

- [ ] **Step 3: 验证 revert 结果**

```bash
git diff --stat
# 确认相关文件被修改
```

- [ ] **Step 4: 提交 revert**

```bash
git commit -m "Revert all HDBSS v1/v3 commits to start clean"
```

---

### Task 2.3: 编译验证 revert 结果

- [ ] **Step 1: 编译 kernel**

```bash
cd /root/openeuler/kernel
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc) 2>&1 | tail -50
```

- [ ] **Step 2: 检查编译错误**

如果有 HDBSS 相关错误，检查是否还有遗漏的 revert

- [ ] **Step 3: 如有冲突，解决后继续编译**

---

### Task 2.4: 准备 v3 Patch 文件

**文件来源：** `/mnt/shared/HDBSS/HDBSS_v3_comments/PATCH-v3-1-5-arm64-sysreg-Add-HDBSS-related-register-information.mbox`

- [ ] **Step 1: 提取 5 个主要 patch**

```bash
cd /mnt/shared/HDBSS
# 使用 git am 提取，如果失败则手动提取
git am --keep-cr < HDBSS_v3_comments/PATCH-v3-1-5-arm64-sysreg-Add-HDBSS-related-register-information.mbox 2>&1
```

如果失败，手动提取 patch 到 `/mnt/shared/HDBSS/docs/v3_patches/`：
- 0001_arm64_sysreg_Add_HDBSS_related_register_information.patch
- 0002_KVM_arm64_Add_support_to_set_the_DBM_attr_during_memory_abort.patch
- 0003_KVM_arm64_Add_support_for_FEAT_HDBSS.patch
- 0004_KVM_arm64_Enable_HDBSS_support_and_handle_HDBSSF_events.patch
- 0005_KVM_arm64_Document_HDBSS_ioctl.patch

- [ ] **Step 2: 验证提取的 patch 数量**

```bash
ls -la /mnt/shared/HDBSS/docs/v3_patches/
```

---

### Task 2.5: Apply v3 Patches

- [ ] **Step 1: 按顺序 apply patch 1-5**

```bash
cd /root/openeuler/kernel
git am /mnt/shared/HDBSS/docs/v3_patches/0001_*.patch
git am /mnt/shared/HDBSS/docs/v3_patches/0002_*.patch
git am /mnt/shared/HDBSS/docs/v3_patches/0003_*.patch
git am /mnt/shared/HDBSS/docs/v3_patches/0004_*.patch
git am /mnt/shared/HDBSS/docs/v3_patches/0005_*.patch
```

- [ ] **Step 2: 处理冲突（如有）**

```bash
# 如有冲突，解决后
git add .
git am --continue
```

- [ ] **Step 3: 验证合入结果**

```bash
git log --oneline -10
git diff HEAD~5 --stat
```

---

## 第三阶段：代码归档到 dirty_bit.c

### Task 3.1: 创建 dirty_bit.c 文件

**新文件：** `arch/arm64/kvm/dirty_bit.c`
**头文件：** `arch/arm64/include/asm/kvm_dirty_bit.h`

- [ ] **Step 1: 创建头文件**

```c
// arch/arm64/include/asm/kvm_dirty_bit.h
#ifndef _ASM_ARM64_KVM_DIRTY_BIT_H
#define _ASM_ARM64_KVM_DIRTY_BIT_H

#include <linux/kvm_host.h>

#ifdef CONFIG_ARM64_HDBSS
// HDBSS related definitions and functions
#endif

#endif
```

- [ ] **Step 2: 创建源文件**

将 `mmu.c`, `pgtable.c`, `handle_exit.c` 中的 HDBSS 相关代码迁移到 `dirty_bit.c`

- [ ] **Step 3: 更新 Makefile**

修改 `arch/arm64/kvm/Makefile` 添加 `dirty_bit.c`

- [ ] **Step 4: 验证编译**

```bash
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc) 2>&1 | head -50
```

- [ ] **Step 5: 提交**

```bash
git add arch/arm64/kvm/dirty_bit.c arch/arm64/include/asm/kvm_dirty_bit.h
git commit -m "KVM: arm64: create dirty_bit.c for HDBSS code"
```

---

## 第四阶段：DBM 添加/清除 + Bug 修复

### Task 4.1: 修复 kvm_pgtable_stage2_pte_prot() 不提取 DBM

**文件：** `arch/arm64/kvm/hyp/pgtable.c`

- [ ] **Step 1: 定位函数**

```bash
grep -n "kvm_pgtable_stage2_pte_prot" /root/openeuler/kernel/arch/arm64/kvm/hyp/pgtable.c
```

- [ ] **Step 2: 添加 DBM 提取**

在函数中添加：
```c
if (pte & KVM_PTE_LEAF_ATTR_HI_S2_DBM)
    prot |= KVM_PGTABLE_PROT_DBM;
```

- [ ] **Step 3: 验证修改**

- [ ] **Step 4: 提交**

```bash
git commit -m "KVM: arm64: fix kvm_pgtable_stage2_pte_prot to extract DBM"
```

---

### Task 4.2: 修复 stage2_pte_needs_update() DBM 被忽略

**文件：** `arch/arm64/kvm/hyp/pgtable.c`

- [ ] **Step 1: 定位函数**

```bash
grep -n "stage2_pte_needs_update" /root/openeuler/kernel/arch/arm64/kvm/hyp/pgtable.c
```

- [ ] **Step 2: 修改函数**

添加 DBM 到比较逻辑：
```c
if ((old ^ new) & KVM_PTE_LEAF_ATTR_HI_S2_DBM)
    return true;
```

- [ ] **Step 3: 验证修改**

- [ ] **Step 4: 提交**

```bash
git commit -m "KVM: arm64: fix stage2_pte_needs_update to handle DBM changes"
```

---

### Task 4.3: 实现权限变更时清除 DBM

**文件：** `arch/arm64/kvm/hyp/pgtable.c` 或 `arch/arm64/kvm/mmu.c`

- [ ] **Step 1: 定位权限变更函数**

确认 W→RO 路径（目前没有非迁移场景的 W→RO）

- [ ] **Step 2: 添加清除 DBM 逻辑**

在 `kvm_pgtable_stage2_relax_perms()` 或相关函数中：
```c
if (old_prot & KVM_PGTABLE_PROT_W && !(new_prot & KVM_PGTABLE_PROT_W)) {
    // W → RO，清除 DBM
    if (ptep->dbm)
        clear DBM;
}
```

- [ ] **Step 3: 验证修改**

- [ ] **Step 4: 提交**

---

## 第五阶段：自动启用/禁用 HDBSS（去掉 ioctl）

### Task 5.1: 在 migration 初始化时自动 enable

**文件：** `arch/arm64/kvm/mmu.c` 或 `arch/arm64/kvm/arm.c`

- [ ] **Step 1: 查找 QEMU 触发 migration 的 ioctl**

```bash
grep -n "KVM_SET_USER_MEMORY_REGION\|KVM_RUN\|migration" /root/openeuler/kernel/arch/arm64/kvm/*.c | head -30
```

- [ ] **Step 2: 添加 HDBSS enable 逻辑**

在 memory region 设置时检测是否需要启用 HDBSS

- [ ] **Step 3: 验证修改**

- [ ] **Step 4: 提交**

---

### Task 5.2: 移除 HDBSS ioctl

- [ ] **Step 1: 找到 ioctl 定义**

```bash
grep -rn "KVM_ARM_HDBSS\|HDBSS ioctl" /root/openeuler/kernel/ --include="*.h" --include="*.c" | head -20
```

- [ ] **Step 2: 移除 ioctl 处理**

- [ ] **Step 3: 验证编译**

- [ ] **Step 4: 提交**

---

## 第六阶段：合入 HACDBS（可选）

### Task 6.1: 合入 HACDBS Patch

**文件来源：** `/mnt/shared/HDBSS/HACDBS_patch/`

- [ ] **Step 1: 提取 HACDBS patch**

```bash
git am < /mnt/shared/HDBSS/HACDBS_patch/20260430_leo_bras_kvm_dirty_bit_cleaning_accelerator_hacdbs.mbx
```

- [ ] **Step 2: 处理冲突**

- [ ] **Step 3: 验证编译**

- [ ] **Step 4: 提交**

---

## 任务依赖关系

```
Task 1.1 ─┐
Task 1.2 ─┼──► Task 2.1 ─► Task 2.2 ─► Task 2.3 (编译验证)
Task 1.3 ─┘                 │
                            ▼
                      Task 2.4 ─► Task 2.5
                              (v3 patches)  │
                                           ▼
                                     Task 3.1 (dirty_bit.c)
                                           │
                                           ▼
                        Task 4.1 ─► Task 4.2 ─► Task 4.3
                                           │
                                           ▼
                                    Task 5.1 ─► Task 5.2
                                           │
                                           ▼
                                     Task 6.1 (optional)
```

---

## 编译验证命令汇总

```bash
# 完整编译
cd /root/openeuler/kernel
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc) 2>&1 | tail -100

# 只编译 KVM 模块
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -C virt/kvm -j$(nproc) 2>&1 | tail -50

# 检查 HDBSS 相关编译结果
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc) 2>&1 | grep -i "hdbss\|error\|warning" | head -30
```
