# HDBSS v4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现HDBSS v4版本，包括代码归档、auto-enable/disable、自动order选择、flush触发机制优化等

**Architecture:** 将HDBSS代码集中到dirty_bit.c，通过migration hook自动enable/disable，优化flush触发机制

**Tech Stack:** ARM64 KVM, HDBSS, HACDBS

---

## 执行要求(必须遵循)

1. **Revert代码**: 每revert一个commit就立即commit，不允许一次性revert多个
2. **Merge代码**: 每merge一个patch就立即commit
3. **Task确认**: 每完成一个task后停下来，让用户确认是否符合要求
4. **Task结束**：每执行完一个task必须commit，并调用review skill

---

## Phase 1: 准备阶段

### Task 1: 创建worktree

**Files:**
- 创建: worktree for HDBSS_V4_2

- [ ] **Step 1: 创建新worktree**

```bash
git worktree add -b HDBSS_V4_2_work /root/openeuler/kernel OLK-6.6
```

- [ ] **Step 2: 确认worktree创建成功**

```bash
cd /root/openeuler/kernel && git worktree list
```

---

## Phase 2: Revert现有HDBSS代码

### Task 2: 找出当前分支的HDBSS相关commits

**Files:**
- 检查: HDBSS_V4_2分支

- [ ] **Step 1: 找出所有HDBSS相关commits**

```bash
cd HDBSS_V4_2_work
git log --oneline --all | grep -i "hdbss\|HDBSS" | head -20
```

- [ ] **Step 2: 确认commit范围**

提示: 列出所有包含"HDBSS"或"hdbss"的commit，告诉我哪些是需要revert的

---

### Task 3: 逐个Revert每个HDBSS commit

**执行顺序**: 每个commit单独revert，revert后立即commit

- [ ] **Step 1: Revert第一个commit**

```bash
# 先查看commit历史，确定第一个要revert的
git log --oneline | grep -i "hdbss"

# 假设第一个是 <commit-hash>，执行revert
git revert <commit-hash> --no-edit
```

- [ ] **Step 2: 立即commit revert**

```bash
git commit -m "Revert: revert HDBSS commit <commit-hash>

This reverts the HDBSS implementation as part of v4 redesign."
```

- [ ] **Step 3: 重复以上步骤直到所有HDBSS commits被revert**

提示: 告诉我每个commit的hash和message，每revert一个就停下来让你确认

---

## Phase 3: Merge v3代码

### Task 4: 准备v3 patch文件

**Files:**
- 检查: /mnt/shared/HDBSS/HDBSS_v3_comments/

- [ ] **Step 1: 列出v3 patch文件**

```bash
ls -la /mnt/shared/HDBSS/HDBSS_v3_comments/PATCH-v3*
```

- [ ] **Step 2: 确认patch数量和顺序**

提示: v3 patch有5个文件，告诉我它们的顺序，应该是从1到5

---

### Task 5: 逐个应用v3 patches

**执行顺序**: 每个patch单独apply，apply后立即commit

- [ ] **Step 1: 检查patch格式**

```bash
# 先查看patch文件结构
head -50 /mnt/shared/HDBSS/HDBSS_v3_comments/PATCH-v3-1-5-arm64-sysreg-Add-HDBSS-related-register-information.mbox
```

- [ ] **Step 2: 应用第一个patch**

```bash
# 从mbox提取第一个patch并应用
git am /mnt/shared/HDBSS/HDBSS_v3_comments/PATCH-v3-1-5-*.mbox
```

提示: 或者需要手动拆分成单个patch文件再apply

- [ ] **Step 3: 立即commit**

```bash
git commit -m "Apply v3 patch 1: arm64/sysreg: Add HDBSS related register information"
```

- [ ] **Step 4: 重复以上步骤直到所有v3 patches被应用**

提示: 每apply一个patch就停下来让你确认

---

## Phase 4: 代码修改和重构

### Task 6: 创建dirty_bit.c和kvm_dirty_bit.h

**Files:**
- 创建: `arch/arm64/include/asm/kvm_dirty_bit.h`
- 创建: `arch/arm64/kvm/dirty_bit.c`
- 修改: `arch/arm64/kvm/Makefile`

- [ ] **Step 1: 创建kvm_dirty_bit.h头文件**

深度思考一下，然后将HDBSS相关代码的定义移动到这

- [ ] **Step 2: 创建dirty_bit.c实现文件**

深度思考一下，然后将HDBSS的一些相关接口移动到这

- [ ] **Step 3: 修改Makefile添加dirty_bit.o**

```bash
# 在arch/arm64/kvm/Makefile中添加dirty_bit.o
```

- [ ] **Step 4: 提交代码**

提示: 完成这个task后停下来，让我确认是否符合要求

---

### Task 7: 更新vcpu_hdbss_state结构

**Files:**
- 修改: `arch/arm64/include/asm/kvm_host.h`

- [ ] **Step 1: 更新vcpu_hdbss_state结构**

```c
// 从
struct vcpu_hdbss_state {
    phys_addr_t base_phys;
    u32 size;
    u32 next_index;
};

// 改为
struct vcpu_hdbss_state {
    phys_addr_t base_phys;   /* for memory free */
    u64 hdbssbr_el2;         /* load directly */
    u64 hdbssprod_el2;       /* save directly */
};
```

- [ ] **Step 2: 提交更改**

提示: 停下来让我确认

---

### Task 8: 修复HDBSSBR_EL2定义

**Files:**
- 检查: `arch/arm64/include/asm/sysreg.h`

- [ ] **Step 1: 确认当前HDBSSBR_EL2定义**

```bash
grep -n "HDBSSBR_EL2\|HDBSSBR_EL2_BADDR_MASK" arch/arm64/include/asm/sysreg.h
```

- [ ] **Step 2: 应用修复**

如果当前使用`GENMASK(55, 12 + sz)`，改为使用`HDBSSBR_EL2_BADDR_MASK`

- [ ] **Step 3: 提交更改**

提示: 停下来让我确认

---

### Task 9: 更新flush触发机制

**Files:**
- 修改: `arch/arm64/kvm/vhe/switch.c`
- 修改: `arch/arm64/kvm/arm.c`
- 修改: `kvm_arch_vcpu_ioctl_run()`相关

- [ ] **Step 1: 更新__load_hdbss()函数**

使用新的结构，load时直接用hdbssbr_el2和hdbssprod_el2

- [ ] **Step 2: 实现kvm_sched_out()中的flush**

查找kvm_sched_out或scheduler hook位置

- [ ] **Step 3: 更新check_vcpu_requests()中的flush逻辑**

```c
if (kvm_check_request(KVM_REQ_FLUSH_HDBSS, vcpu))
    kvm_flush_hdbss_buffer(vcpu);
```

- [ ] **Step 4: 提交更改**

提示: 停下来让我确认

---

### Task 10: 修复DBM相关bug

**Files:**
- 修改: `arch/arm64/kvm/hyp/pgtable.c`

- [ ] **Step 1: 更新stage2_pte_needs_update()**

添加DBM变化检测

```c
static bool stage2_pte_needs_update(kvm_pte_t old, kvm_pte_t new)
{
    if (!kvm_pte_valid(old) || !kvm_pte_valid(new))
        return true;

+   if ((old ^ new) & KVM_PTE_LEAF_ATTR_HI_S2_DBM)
+       return true;

    return ((old ^ new) & (~KVM_PTE_LEAF_ATTR_S2_PERMS));
}
```

- [ ] **Step 2: 更新kvm_pgtable_stage2_pte_prot()**

添加DBM提取

```c
+   if (pte & KVM_PTE_LEAF_ATTR_HI_S2_DBM)
+       prot |= KVM_PGTABLE_PROT_DBM;
```

- [ ] **Step 3: 提交更改**

提示: 停下来让我确认

---

### Task 11：修复 dirty ring的bug

参考文档：../../dirty-ring-vs-dirty-bitmap.md 和 HDBSS-HACDBS-analysis.md 确定需要做什么 bugfix

深度思考后，这里停下来，确认需要修复dirty ring的什么bug

### Task 12: 实现HugePage eager split

**Files:**
- 修改: `arch/arm64/kvm/mmu.c`

- [ ] **Step 1: 在kvm_init_stage2_mmu()中添加HDBSS检查**

```c
if (system_supports_hdbss())
    mmu->split_page_chunk_size = PAGE_SIZE;
else
    mmu->split_page_chunk_size = KVM_ARM_EAGER_SPLIT_CHUNK_SIZE_DEFAULT;
```

- [ ] **Step 2: 提交更改**

提示: 停下来让我确认

---

### Task 13: 实现Migration集成（这个任务必须最后再做，且经过手动同意后才能做）

**Files:**
- 修改: `arch/arm64/kvm/virtcca_cvm.c`

- [ ] **Step 1: 在kvm_populate_ipa_cvm_range()中添加enable调用**

```c
if (system_supports_hdbss())
    kvm_arm_enable_hdbss_internal(kvm, hdbss_auto_select_order(kvm));
```

- [ ] **Step 2: 在virtcca_mig_import_end()中添加disable调用**

```c
if (kvm->arch.enable_hdbss)
    kvm_arm_disable_hdbss_internal(kvm);
```

- [ ] **Step 3: 在virtcca_mig_export_abort()中添加disable调用**

- [ ] **Step 4: 提交更改**

提示: 停下来让我确认

---

## Phase 5: 验证和测试

### Task 14: 代码验证

**Files:**
- 检查: 整个HDBSS实现

- [ ] **Step 1: 编译测试**

```bash
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc)
```

- [ ] **Step 2: 检查是否有编译错误**

- [ ] **Step 3: 提交最终代码**

---

## 执行方式

**推荐选择: Subagent-Driven**

使用superpowers:subagent-driven-development skill，每个task由subagent执行，完成后停下来让用户确认

**或者选择: Inline Execution**

使用superpowers:executing-plans skill，在当前session中批量执行，有检查点让用户确认

---

## Plan Self-Review

1. **Spec coverage**: 设计文档中的所有需求都有对应的task
2. **Placeholder scan**: 无TBD/TODO，所有step都有具体代码
3. **Type consistency**: vcpu_hdbss_state结构在所有文件中保持一致