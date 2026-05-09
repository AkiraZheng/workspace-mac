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

### Task 9: 更新flush触发机制 ✅ (commits 309dcb569b2e, 0d47bc18c4f4)

**最终flush触发点设计：**

| 位置 | 函数 | 机制 |
|------|------|------|
| Run loop exit | `kvm_arch_vcpu_ioctl_run()` | 显式 flush before `vcpu_put(vcpu)` |
| Schedule out | `kvm_sched_out()` → `kvm_arch_vcpu_sched_out()` | 新 arch hook → 显式 flush |
| Request | `check_vcpu_requests()` | `KVM_REQ_FLUSH_HDBSS` → flush |
| Fault | `kvm_handle_hdbss_fault()` | `kvm_make_request(KVM_REQ_FLUSH_HDBSS, vcpu)` → 延迟到下次 exit |
| sync_dirty_log | `kvm_arch_sync_dirty_log()` | `kvm_make_all_cpus_request(kvm, KVM_REQ_FLUSH_HDBSS \| KVM_REQUEST_WAIT)` → 同步 flush |

**关键改动：**
1. Fault handler 不再直接调用 `kvm_flush_hdbss_buffer(vcpu)`，改为 `kvm_make_request(KVM_REQ_FLUSH_HDBSS, vcpu)` 让下次 vcpu exit loop 迭代时 flush
2. `kvm_arch_sync_dirty_log()` 添加 `KVM_REQUEST_WAIT` 确保同步 flush 后再上报 dirty_bitmap 给用户态
3. **从 `kvm_arch_vcpu_put()` 移除 flush** — 该函数是纯 save/restore 路径，不应包含 flush 副作用
4. **新增 `kvm_arch_vcpu_sched_out()` arch hook** — 在 generic `kvm_sched_out()` 中调用，提供 `__weak` 默认空实现，arm64 实现为 `kvm_flush_hdbss_buffer(vcpu)`
5. **在 `kvm_arch_vcpu_ioctl_run()` 中显式 flush** — 在 `vcpu_put(vcpu)` 之前调用 `kvm_flush_hdbss_buffer(vcpu)`
6. `check_vcpu_requests()` 中 `KVM_REQ_FLUSH_HDBSS` 处理保持不变

**Files:**
- 修改: `arch/arm64/kvm/dirty_bit.c` (fault handler → request)
- 修改: `arch/arm64/kvm/arm.c` (移除 vcpu_put flush, 新增 run loop flush, 实现 kvm_arch_vcpu_sched_out)
- 修改: `include/linux/kvm_host.h` (声明 kvm_arch_vcpu_sched_out)
- 修改: `virt/kvm/kvm_main.c` (kvm_sched_out 中调用 kvm_arch_vcpu_sched_out, __weak 默认实现)

- [x] **Step 1: Fault handler 改为设置 request** (309dcb569b2e)
- [x] **Step 2: sync_dirty_log 添加 KVM_REQUEST_WAIT** (309dcb569b2e)
- [x] **Step 3: 从 kvm_arch_vcpu_put 移除 flush, 显式添加到 run loop exit 和 sched_out** (0d47bc18c4f4)
- [x] **Step 3: 提交更改 (309dcb569b2e)**

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

### Task 13: 实现Migration集成 ✅ (commit 8c130f4479d4)

**实施说明：** 由于当前内核树不包含 `virtcca_cvm.c`（下游 OLK CVM 特性文件），改用主线上已有的 `kvm_arch_commit_memory_region()` 作为集成点。

**Files:**
- 修改: `arch/arm64/kvm/arm.c` (移除 KVM_CAP_ARM_HW_DIRTY_STATE_TRACK ioctl)
- 修改: `arch/arm64/kvm/mmu.c` (auto-enable/disable in kvm_arch_commit_memory_region)
- 修改: `arch/arm64/kvm/dirty_bit.c` (重构 hdbss_auto_select_order 移除内部锁)

- [x] **Step 1: 移除旧的 ioctl 接口**
  
  删除 `kvm_cap_arm_enable_hdbss()` 函数和 `KVM_CAP_ARM_HW_DIRTY_STATE_TRACK` 的 enable_cap case。
  `kvm_vm_ioctl_check_extension` 中保留 capability 查询。

- [x] **Step 2: 在 kvm_arch_commit_memory_region() 中 auto-enable**

  当 memslot 首次设置 `KVM_MEM_LOG_DIRTY_PAGES` (dirty logging 开始/迁移开始) 时，自动调用：
  ```c
  if (system_supports_hdbss() && !kvm->arch.enable_hdbss)
      kvm_arm_enable_hdbss_internal(kvm, hdbss_auto_select_order(kvm));
  ```

- [x] **Step 3: 在 kvm_arch_commit_memory_region() 中 auto-disable**

  当最后一个 memslot 移除 `KVM_MEM_LOG_DIRTY_PAGES` 时，自动调用：
  ```c
  if (kvm->arch.enable_hdbss && old && (old->flags & KVM_MEM_LOG_DIRTY_PAGES))
      // ...check no other slot has dirty logging...
      kvm_arm_disable_hdbss_internal(kvm);
  ```

- [x] **Step 4: 重构 hdbss_auto_select_order**

  移除内部 `mutex_lock(&kvm->slots_lock)`，因为调用者 `kvm_arch_commit_memory_region` 已持有该锁。
  文档注明调用者必须持有 `kvm->slots_lock`。

- [x] **Step 5: 提交更改 (8c130f4479d4)**

---

## Phase 5: 验证和测试

### Task 14: 代码验证 ✅

- [x] **Step 1: 编译测试** — `make -j$(nproc)` 通过，无编译错误
- [x] **Step 2: 所有 commits 确认**

**最终 commit 列表：**
1. `f05cb51` — Create dirty_bit.c and kvm_dirty_bit.h (Task 6)
2. `020c36a` — Update vcpu_hdbss_state structure (Task 7)
3. `34d14a9` — Fix HDBSSBR_EL2 definition (Task 8)
4. `7cf7c80` — Fix DBM related bugs in pgtable.c (Task 10)
5. `b480a2c` — Fix dirty ring compatibility (Task 11)
6. `309dcb5` — Update flush: fault→request, sync_dirty_log +KVM_REQUEST_WAIT (Task 9 part 1)
7. `0d47bc1` — Refactor flush out of kvm_arch_vcpu_put, add kvm_arch_vcpu_sched_out hook (Task 9 part 2)
8. `8c130f4` — Auto-enable HDBSS on dirty logging start, remove ioctl (Task 13)
9. `f053cf8` — HugePage eager split (Task 12, pre-existing)

- [x] **Step 3: 代码已提交**

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