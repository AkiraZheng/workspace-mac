# HDBSS v5 设计文档

本文档描述 ARM64 KVM HDBSS（Hardware Dirty Bit State Structure）v5 的设计，涵盖所有关键适配点、方案对比和最终决策。

---

## 目录

1. [ARM Spec 概述](#1-arm-spec-概述)
2. [DBM 标签配置方式](#2-dbm-标签配置方式)
3. [Lazy Split 与 Eager Split 适配](#3-lazy-split-与-eager-split-适配)
4. [HDBSS Buffer 生命周期](#4-hdbss-buffer-生命周期)
5. [Flush 路径设计](#5-flush-路径设计)
6. [HDBSS Enable/Disable 与 VTCR 同步](#6-hdbss-enabledisable-与-vtcr-同步)
7. [Dirty Ring 适配](#7-dirty-ring-适配)
8. [嵌套虚拟化保护](#8-嵌套虚拟化保护)
9. [HDBSSPROD_EL2 保存/恢复](#9-hdbssprod_el2-保存恢复)
10. [HDBSS Fault 处理](#10-hdbss-fault-处理)
11. [UAF 安全分析](#11-uaf-安全分析)
12. [已知限制与遗留问题](#12-已知限制与遗留问题)

---

## 1. ARM Spec 概述

### 1.1 三态模型

ARM Spec（DDI 0487 M.b, D8.5.2）定义了 Stage-2 页表描述符的三种 dirty state：

| 状态 | DBM | S2AP[1] (W) | 写访问行为 |
|------|-----|-------------|-----------|
| Non-writable | 0 | 0 | 写 → Permission fault |
| Writable-clean | 1 | 0 | HD=0: 写 → Permission fault (软件管理); HD=1: 写 → 硬件 C→D + HDBSS 记录 |
| Writable-dirty | 1 | 1 | 可写，无 fault |

Spec 原文（D8.5.2, D8-7773）：

> a Block descriptor or Page descriptor can be described as having one of the following states:
> - Non-writable.
> - Writable-clean.
> - Writable-dirty.

### 1.2 HDBSS 使能条件

Spec D8.5.2.3 (D8-7777)：

> HDBSS is enabled only if VTCR_EL2.{HDBSS,HA,HD} are {1,1,1}.

代码实现（`dirty_bit.c:156`）：
```c
kvm->arch.mmu.vtcr |= VTCR_EL2_HD | VTCR_EL2_HDBSS | VTCR_EL2_HA;
```

### 1.3 HDBSS Entry 格式

Spec Table D8-93 (D8-7778)：

| Bit 位置 | 字段 | 说明 |
|----------|------|------|
| [0] | Valid | 0=无效, 1=有效 |
| [3:1] | TTWL | 翻译表 walk level（3-bit 补码有符号整数） |
| [11] | NSIPA | Secure 状态下 IPA 的安全属性 |
| [55:12] | IPA | 被 C→D 更新的 Stage-2 描述符翻译的 IPA |
| [63:56] | RES0 | - |

每个 entry 8 字节。Buffer 大小由 `HDBSSBR_EL2.SZ` 编码（`ilog2(size_bytes) - 12`）。

### 1.4 HDBSS Buffer Full 行为

Spec D8.5.2.3 (D8-7779)：

> If the HDBSS is full and enabled, then the PE does not update any stage 2 descriptors from writable-clean to writable-dirty.
>
> Any access that requires a stage 2 dirty state hardware update generates a stage 2 Permission fault... ESR_EL2.ISS2.HDBSSF is reported as 1.

即 buffer 满时：硬件不做 C→D 转换，guest 写触发 Permission fault（带 HDBSSF 标志），软件负责 flush buffer。

---

## 2. DBM 标签配置方式

### 2.1 设计决策：无条件 DBM

v5 移除了 `KVM_PGTABLE_S2_DBM` page-table flag（Phase 6.1），DBM 位在所有可写非设备页上**无条件设置**。

### 2.2 方案对比

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| v4: 有条件 DBM | `KVM_PGTABLE_S2_DBM` flag 控制，仅 HDBSS 支持时设 DBM | 非 HDBSS VM 不受影响 | 需要 flag 管理；wrprotect 需要额外清 DBM；未来 FEAT_S2PIE 必须改 |
| v5: 无条件 DBM | 所有可写页都设 DBM，不管 HDBSS 是否启用 | 简单；page table library 外部"just works"；与未来 FEAT_S2PIE 兼容 | 非 HDBSS 时 DBM 位无硬件效果（HD=0 时 DBM 被忽略），无害 |

Spec D8.5.2.1 (D8-7774) 支持 v5 方案：
> For stage 2 translations, if the Effective value of VTCR_EL2.HD is 1, then dirty state hardware management is enabled.

HD=0 时 DBM 无硬件效果，软件管理 dirty state（Permission fault）。因此无条件设 DBM 在 HD=0 时无害。

### 2.3 AP 位与 DBM 的联动规则

设计原则：**所有修改 S2AP 的软件路径必须紧跟 DBM 的修改**。

#### W→RO 方向（清 W，需要检查是否清 DBM）

| # | 代码路径 | 文件:行 | S2AP 修改 | DBM 修改 | 一致性 |
|---|---------|--------|----------|---------|--------|
| 1 | `kvm_pgtable_stage2_wrprotect()` | `pgtable.c:1313-1318` | 清 S2AP_W | block 清 DBM, page 保留 | ✅ walker 中区分 |
| 2 | `kvm_arch_mmu_enable_log_dirty_pt_masked()` | `mmu.c:1326-1352` → 调 #1 | 同 #1 | 同 #1 | ✅ |
| 3 | `kvm_pgtable_stage2_unmap()` | `pgtable.c:1213` | 整 PTE 清零 | DBM 自然消失 | ✅ |

#### RO→W 方向（设 W，DBM 跟着设）

| # | 代码路径 | 文件:行 | S2AP 修改 | DBM 修改 | 一致性 |
|---|---------|--------|----------|---------|--------|
| 4 | `stage2_set_prot_attr(W)` | `pgtable.c:734-749` | 设 S2AP_W | 设 DBM | ✅ 同一 if 块 |
| 5 | `kvm_pgtable_stage2_relax_perms(W)` | `pgtable.c:1395-1398` | 设 S2AP_W | 设 DBM | ✅ 同一 if 块 |
| 6 | `kvm_pgtable_stage2_map(W)`（lazy split） | `pgtable.c:1109` → #4 | 设 S2AP_W | 设 DBM | ✅ |
| 7 | `stage2_split_walker()` | `pgtable.c:1519-1570` → #4 | 继承 prot | 跟着 prot（有 W 就设，无 W 就不设） | ✅ |

#### 硬件行为

| # | 代码路径 | S2AP 修改 | DBM 修改 | 一致性 |
|---|---------|----------|---------|--------|
| 8 | 硬件 C→D | 硬件设 S2AP_W=1 | DBM 保持 1 | ✅ 硬件行为 |

#### 不修改 S2AP_W 的路径（DBM 无影响）

| # | 代码路径 | 操作 | DBM 影响 |
|---|---------|------|---------|
| 9 | `kvm_pgtable_stage2_mkyoung()` | 只设 AF 位 | 无影响 |
| 10 | `kvm_pgtable_stage2_test_clear_young()` | 只清 AF 位 | 无影响 |
| 11 | `kvm_pgtable_stage2_flush()` | 只做 cache flush，不改 PTE | 无影响 |
| 12 | `relax_perms(R)` 或 `relax_perms(X)` | 不含 W 时只设 S2AP_R 或 XN | 无影响 |

#### "只改 W 不碰 DBM"的场景分析

问题：RO→W 方向中，如果旧 PTE 已带 DBM=1，设 W 时只 OR 了 W 位而没有同时 OR DBM，会怎样？

**路径 4/6/7（`stage2_set_prot_attr`）**：不存在此问题。`*ptep = attr` 是**整体覆盖**，不是 OR 操作。新值完全由 `prot` 决定，有 W 就有 DBM，没 W 就没 DBM。旧 PTE 的 DBM 状态被完全覆盖。

```c
// stage2_set_prot_attr() — 整体覆盖
if (prot & KVM_PGTABLE_PROT_W) {
    attr |= KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W;
    attr |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;   // 无条件跟 W 一起设
}
// ...
*ptep = attr;   // ← 整体覆盖，不是 OR
```

**路径 5（`relax_perms`）**：不存在此问题。底层是 OR 操作，但 v5 中 `set |= DBM` 是**无条件**执行的（移除了 v4 的 `if (pgt->flags & KVM_PGTABLE_S2_DBM)` 条件守卫）：

```c
// kvm_pgtable_stage2_relax_perms() — OR 操作
if (prot & KVM_PGTABLE_PROT_W) {
    set |= KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W;
    set |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;   // 无条件，不管旧 DBM 状态
}
// → stage2_attr_walker():
//   pte |= data->attr_set;   // OR 操作，DBM 必被设为 1
```

| 旧 PTE 状态 | 操作 | 新 PTE 状态 | 正确? |
|------------|------|------------|-------|
| RO (DBM=0, W=0) | `pte \|= W \| DBM` | WD (DBM=1, W=1) | ✅ |
| WC (DBM=1, W=0) | `pte \|= W \| DBM`（DBM 已是 1，OR 无变化） | WD (DBM=1, W=1) | ✅ |

**结论：不存在"只改 W 不碰 DBM"的路径。** v5 中所有设 W 的路径都无条件同时设 DBM。v4 中 `relax_perms()` 有 `if (pgt->flags & KVM_PGTABLE_S2_DBM)` 条件守卫，在 flag 没设时确实可能只改 W 不设 DBM——v5 移除了该条件。

### 2.4 wrprotect 的 block/page 区分

`stage2_attr_walker()` (pgtable.c:1259-1260) 中：

```c
if (ctx->level < KVM_PGTABLE_LAST_LEVEL)
    pte &= ~KVM_PTE_LEAF_ATTR_HI_S2_DBM;
```

- **Block entry**（level < LAST）：清 S2AP_W + 清 DBM → **RO**（Non-writable）
  - 迫使首次写 fault → 触发 split
- **Level-3 page**（level == LAST）：清 S2AP_W + 保留 DBM → **WC**（Writable-clean）
  - HDBSS 在下次写时重新 arm（硬件 C→D + 记录）

设计理由：HDBSS 只记录 page 级 IPA（entry 的 IPA 对齐到 Page/Block descriptor 大小）。Block entry 保留 DBM 会让硬件做 C→D 但记录的 IPA 是 block 级的，不能直接用于 dirty bitmap 的 page 级标记。

---

## 3. Lazy Split 与 Eager Split 适配

### 3.1 背景知识：KVM Dirty Logging 的 Split 机制

KVM 的 dirty logging 在 page 粒度工作，但 guest 内存可能以大页（huge page / block mapping）映射。需要在 dirty logging 开启时将 block mapping 拆成 page mapping。

#### 3.1.1 核心数据结构

```c
// kvm_host.h:183-184
#define KVM_ARM_EAGER_SPLIT_CHUNK_SIZE_DEFAULT 0
// 0 = lazy split（默认），非零 = eager split

// kvm_s2_mmu 中的 chunk size
// mmu.c:1032
mmu->split_page_chunk_size = KVM_ARM_EAGER_SPLIT_CHUNK_SIZE_DEFAULT;
```

#### 3.1.2 三种触发路径

**路径 1：dirty logging 开启时（无 INITIALLY_SET）**

`kvm_arch_commit_memory_region()` (mmu.c:2577-2611)：

```c
void kvm_arch_commit_memory_region(struct kvm *kvm, ...)
{
    bool log_dirty_pages = new && new->flags & KVM_MEM_LOG_DIRTY_PAGES;

    // HDBSS enable/disable（我们的代码）
    kvm_arm_hdbss_on_dirty_logging_change(kvm, ...);

    if (log_dirty_pages) {
        if (change == KVM_MR_DELETE)
            return;

        // INITIALLY_SET 模式：提前返回，靠 CLEAR ioctl 逐批处理
        if (kvm_dirty_log_manual_protect_and_init_set(kvm))
            return;

        // 非 INITIALLY_SET 模式：一次性 wrprotect + split
        kvm_mmu_wp_memory_region(kvm, new->id);     // ← wrprotect
        kvm_mmu_split_memory_region(kvm, new->id);  // ← split
    } else {
        kvm_mmu_free_memory_cache(&kvm->arch.mmu.split_page_cache);
    }
}
```

**路径 2：CLEAR ioctl（INITIALLY_SET 模式）**

`kvm_arch_mmu_enable_log_dirty_pt_masked()` (mmu.c:1326-1352)：

```c
void kvm_arch_mmu_enable_log_dirty_pt_masked(struct kvm *kvm,
        struct kvm_memory_slot *slot, gfn_t gfn_offset, unsigned long mask)
{
    // 1. wrprotect 选中的页
    kvm_stage2_wp_range(&kvm->arch.mmu, start, end);

    // 2. 如果是 INITIALLY_SET 模式，eager split
    if (kvm_dirty_log_manual_protect_and_init_set(kvm))
        kvm_mmu_split_huge_pages(kvm, start, end);

    kvm_nested_s2_wp(kvm);
}
```

**路径 3：写 fault 时（lazy split）**

guest 写 RO 的 block entry → Permission fault → `user_mem_abort()` (mmu.c) → 检测到 block mapping → `kvm_mmu_split_huge_pages()` 拆成 page mapping → `kvm_pgtable_stage2_relax_perms()` 恢复写权限。

#### 3.1.3 wrprotect 和 split 的调用链

```
kvm_mmu_wp_memory_region()           (mmu.c:1268)
  → kvm_stage2_wp_range()            (mmu.c:1250)
    → stage2_apply_range_resched()   (mmu.c)
      → kvm_pgtable_stage2_wrprotect() (pgtable.c:1313)
        → stage2_update_leaf_attrs()
          → stage2_attr_walker()     ← 清 S2AP_W + block 清 DBM

kvm_mmu_split_memory_region()         (mmu.c:1296)
  → kvm_mmu_split_huge_pages()       (mmu.c:121)
    → kvm_pgtable_stage2_split()     (pgtable.c)
      → stage2_split_walker()        ← 从原 block PTE 提取 prot, 创建子页表
        → kvm_pgtable_stage2_create_unlinked() (pgtable.c:1445)
          → stage2_set_prot_attr()   ← 继承 prot（此时无 W → RO）
```

#### 3.1.4 INITIALLY_SET 模式

`kvm_dirty_log_manual_protect_and_init_set(kvm)` (kvm_main.c)：

- 当 VM 支持 `KVM_CAP_MANUAL_DIRTY_LOG_PROTECT2` 且使用 `KVM_DIRTY_LOG_INITIALLY_SET` 时，dirty bitmap 初始全 1
- QEMU 通过 CLEAR ioctl 逐批清除脏页（每批触发 wrprotect + split）
- 优点：减少首次 dirty logging 开启时的开销（不全量 wrprotect）

### 3.2 v5 的适配方案

v5 **不强制 eager split**（移除了 v4 的 `256 * 1024 * PAGE_SIZE` 默认值）。两种模式都支持。

下面逐路径分析 DBM 的清/加时机。

#### 3.2.1 路径 1：非 INITIALLY_SET 的 dirty logging 开启（eager split）

完整调用链和 DBM 状态变化：

```
kvm_arch_commit_memory_region()                  (mmu.c:2577)
  → kvm_arm_hdbss_on_dirty_logging_change()      (dirty_bit.c:195)
    → kvm_arm_enable_hdbss_global()               (dirty_bit.c:150)
      → kvm->arch.mmu.vtcr |= HD|HDBSS|HA        ← 软件 VTCR 设 HDBSS 位
      → kvm_vcpu_kick(vcpu)                       ← kick vCPU

  → kvm_mmu_wp_memory_region()                    (mmu.c:1268)  ← 步骤 1: wrprotect
    → kvm_stage2_wp_range()                       (mmu.c:1250)
      → stage2_apply_range_resched()
        → kvm_pgtable_stage2_wrprotect()          (pgtable.c:1313)
          → stage2_update_leaf_attrs()
            → stage2_attr_walker()                (pgtable.c:1237)
              pte &= ~S2AP_W                       ← 清写权限
              if (level < LAST_LEVEL)
                  pte &= ~DBM                      ← block 清 DBM
              else
                  保留 DBM                          ← page 保留 DBM
```

wrprotect 后的状态：
- Block entry: **RO** (DBM=0, S2AP_W=0)
- Level-3 page (已是 page): **WC** (DBM=1, S2AP_W=0)

```
  → kvm_mmu_split_memory_region()                 (mmu.c:1296)  ← 步骤 2: eager split
    → kvm_mmu_split_huge_pages()                  (mmu.c:121)
      → kvm_pgtable_stage2_split()
        → stage2_split_walker()                   (pgtable.c:1519)
          → prot = kvm_pgtable_stage2_pte_prot(pte)   (pgtable.c:1565)
            ↑ 从 RO block PTE 提取 prot
            ↑ pte 有 S2AP_R 但无 S2AP_W → prot = R（不含 W）
          → kvm_pgtable_stage2_create_unlinked(phys, level, prot=R, ...)
            (pgtable.c:1445)
            → stage2_set_prot_attr(prot=R)        (pgtable.c:702)
              ↑ prot 不含 W → 不设 S2AP_W，不设 DBM
            → 子页: RO (DBM=0, S2AP_W=0)          ← 继承 block 的 RO 状态
```

**关键发现**：split 出来的子页是 **RO**（DBM=0, W=0），不是 WC。因为 `kvm_pgtable_stage2_pte_prot()` 只提取 S2AP_W 判断是否含 W prot，block 此时是 RO（W 被清了），所以 prot 不含 W，`stage2_set_prot_attr()` 不会设 DBM。

子页的 DBM 不是在 split 时加的，而是在**首次写 fault 时由 `relax_perms` 加的**：

```
guest 写 RO 子页 → Permission fault → user_mem_abort()   (mmu.c:2105)
  → perm_fault = true
  → kvm_s2_fault_compute_prot():
    → write_fault = true
    → prot |= KVM_PGTABLE_PROT_W                       (mmu.c:1652-1653)
  → kvm_s2_fault_map()                                 (mmu.c:2017)
    → mapping_size == perm_fault_granule (= PAGE_SIZE)
    → kvm_pgtable_stage2_relax_perms(pgt, ipa, prot=W|R)  (mmu.c:2077)
      (pgtable.c:1382)
      → set |= S2AP_W + set |= DBM                     ← 加写权限 + 加 DBM
      → 子页: WD (DBM=1, S2AP_W=1)
    → mark_page_dirty_in_slot()                        (mmu.c:2088-2089)
      ← 软件标脏（首次写，HDBSS 还没 arm）
  → guest 重试写入 → WD 状态，无 fault
```

**下一轮 dirty tracking（wrprotect 再次执行）**：

```
kvm_mmu_wp_memory_region()
  → stage2_attr_walker():
    → 子页: 清 S2AP_W, 保留 DBM → WC (DBM=1, S2AP_W=0)
    ↑ 注意：此时是 level-3 page，不是 block，所以 DBM 被保留

guest 写 WC 子页 → HDBSS 硬件 C→D + 记录到 buffer → 无 fault
```

完整生命周期（eager split + 首次写后）：

```
初始映射:     block WD (DBM=1, W=1)     ← stage2_set_prot_attr 设 W+DBM
wrprotect:    block RO (DBM=0, W=0)     ← stage2_attr_walker 清 W+DBM (block)
split:        子页 RO (DBM=0, W=0)       ← 继承 block 的 RO，DBM 未设
首次写 fault: 子页 WD (DBM=1, W=1)       ← relax_perms 设 W+DBM + 软件标脏
下一轮 wp:    子页 WC (DBM=1, W=0)       ← stage2_attr_walker 清 W, 保留 DBM (page)
后续写:       硬件 C→D + HDBSS 记录      ← 无 fault, HDBSS 工作
下一轮 wp:    子页 WC (DBM=1, W=0)       ← 循环
```

#### 3.2.2 路径 2：INITIALLY_SET 模式的 CLEAR ioctl

```
kvm_arch_mmu_enable_log_dirty_pt_masked()          (mmu.c:1326)
  → kvm_stage2_wp_range()                          (mmu.c:1336)  ← 步骤 1: wrprotect
    → stage2_attr_walker()
      → block: RO (DBM=0, W=0)
      → page:  WC (DBM=1, W=0)

  → kvm_mmu_split_huge_pages()                     (mmu.c:1347)  ← 步骤 2: split
    → stage2_split_walker()
      → prot = kvm_pgtable_stage2_pte_prot(RO block PTE)
        → prot = R (不含 W)
      → stage2_set_prot_attr(R) → 子页 RO (DBM=0, W=0)
```

与路径 1 相同：split 后子页是 RO，DBM 在首次写 fault 时由 `relax_perms` 加上。

#### 3.2.3 路径 3：Lazy Split（写 fault 触发）

```
wrprotect:    block RO (DBM=0, W=0)               ← stage2_attr_walker 清 W+DBM
              page  WC (DBM=1, W=0)               ← 已是 page 的保留 DBM

guest 写 RO block → Permission fault → user_mem_abort()   (mmu.c:2105)
  → perm_fault = true
  → memslot_is_logging() = true, write_fault = true
    → topup_mmu_memcache()                        ← 准备 split 内存
  → kvm_s2_fault_compute_prot():
    → prot |= KVM_PGTABLE_PROT_W
  → kvm_s2_fault_map()                            (mmu.c:2017)
    → perm_fault_granule = kvm_vcpu_trap_get_perm_fault_granule(vcpu)
      ↑ block mapping 的 permission fault，granule = block size
    → mapping_size = PAGE_SIZE (不是 block size，因为 dirty logging on)
    → mapping_size != perm_fault_granule
    → kvm_pgtable_stage2_map(pgt, ipa, PAGE_SIZE, phys, prot=W|R, memcache)
      (mmu.c:2080)
      → stage2_map_walker() → stage2_map_walker_try_leaf()
        → stage2_set_prot_attr(prot=W|R)
          → set S2AP_W + set DBM                  ← 子页 WD (DBM=1, W=1)
        → 替换 block entry 为 page table + page entry
      → 子页: WD (DBM=1, W=1)
    → mark_page_dirty_in_slot()                   ← 软件标脏

guest 重试写入 → WD 状态，无 fault
```

lazy split 与 eager split 的区别：
- eager split：先拆 block 成 RO 子页，首次写时 `relax_perms` 加 W+DBM
- lazy split：在 fault handler 中直接 `stage2_map` 创建 WD 子页（含 W+DBM），一步到位

两种方式最终结果一致：子页变成 WD (DBM=1, W=1)，下一轮 wrprotect 后变 WC (DBM=1, W=0)。

#### 3.2.4 总结：DBM 的加/清时机

| 步骤 | 操作 | DBM 变化 | 代码位置 |
|------|------|---------|---------|
| 初始映射 | `stage2_set_prot_attr(W)` | 设 DBM | `pgtable.c:749` |
| wrprotect (block) | `stage2_attr_walker` 清 W | 清 DBM | `pgtable.c:1260` |
| wrprotect (page) | `stage2_attr_walker` 清 W | 保留 DBM | `pgtable.c:1259` (不进 if) |
| eager split | `stage2_set_prot_attr(R)` | 不设 DBM（继承 RO） | `pgtable.c:734` (不进 if) |
| 首次写 fault (eager) | `relax_perms(W)` | 设 DBM | `pgtable.c:1397` |
| lazy split fault | `stage2_map(W)` → `set_prot_attr(W)` | 设 DBM | `pgtable.c:749` |
| 下一轮 wp (page) | `stage2_attr_walker` 清 W | 保留 DBM → WC | `pgtable.c:1259` (不进 if) |
| HDBSS 硬件 C→D | 硬件设 S2AP_W=1 | DBM 保持 1 | ARM Spec |

### 3.3 为什么 v5 不强制 eager split

v4 在 `kvm_init_stage2_mmu()` 中设置 `split_page_chunk_size = 256 * 1024 * PAGE_SIZE`，在 16KB/64KB 页上产生架构无效的 block size（4GB/16GB）。v5 移除该默认值，改为 `KVM_ARM_EAGER_SPLIT_CHUNK_SIZE_DEFAULT`（0 = lazy），用户可通过 ioctl opt-in eager split。HDBSS 的三态模型在 lazy 和 eager 两种模式下都正确（3.2.4 节）。

---

## 4. HDBSS Buffer 生命周期

### 4.1 PML-Style 设计

参考 x86 PML 的 buffer 管理模式：

| 事件 | vCPU create | dirty logging on | dirty logging off | vCPU destroy |
|------|-----------|-------------------|-------------------|-------------|
| Buffer | **alloc** | 不操作 | 不操作 | **free** |

v4 在 dirty logging enable 时 alloc、disable 时 free——存在 UAF 风险（Sashiko S18）。v5 改为 PML-style：vCPU create 时 alloc，vCPU destroy 时 free，enable/disable 只操作 VTCR 位。

### 4.2 alloc 实现

`kvm_arm_vcpu_alloc_hdbss()` (dirty_bit.c:16-44)：

```c
int kvm_arm_vcpu_alloc_hdbss(struct kvm_vcpu *vcpu)
{
    // 已分配或硬件不支持 → 跳过
    if (vcpu->arch.hdbss.hdbss_pg || !system_supports_hdbss())
        return 0;

    // 读 VM 级配置（用户 ioctl 或 dirty ring 自动计算）
    size = vcpu->kvm->arch.hdbss_buffer_size ?: KVM_ARM_HDBSS_DEFAULT_SIZE;

    // 分离计算 buddy order 和 HDBSSBR_EL2.SZ 编码
    buddy_order = get_order(size);      // 给 alloc_pages 用
    sz_encoded = ilog2(size) - 12;      // 给 HDBSSBR_EL2 用

    hdbss_pg = alloc_pages(GFP_KERNEL_ACCOUNT, buddy_order);

    vcpu->arch.hdbss = (struct vcpu_hdbss_state) {
        .hdbss_pg = hdbss_pg,
        .hdbssbr_el2 = HDBSSBR_EL2(page_to_phys(hdbss_pg), sz_encoded),
        .hdbssprod_el2 = 0,
        .buddy_order = buddy_order,    // 存下来，free 时用
    };
}
```

调用点：`kvm_arch_vcpu_create()` (arm.c:673)

### 4.3 free 实现

`kvm_arm_vcpu_free_hdbss()` (dirty_bit.c:47-56)：

```c
void kvm_arm_vcpu_free_hdbss(struct kvm_vcpu *vcpu)
{
    if (!vcpu->arch.hdbss.hdbss_pg)
        return;

    __free_pages(vcpu->arch.hdbss.hdbss_pg, vcpu->arch.hdbss.buddy_order);

    vcpu->arch.hdbss.hdbss_pg = NULL;
    vcpu->arch.hdbss.hdbssbr_el2 = 0;
}
```

调用点：`kvm_arm_vcpu_destroy()` (reset.c:166)

### 4.4 buddy_order 修复

v4 用 `HDBSSBR_EL2.SZ` 编码（`ilog2(size)-12`）作为 `__free_pages()` 的 order 参数。在 4KB 页上碰巧正确（SZ 编码 = buddy order），但 16KB/64KB 页上 SZ 编码 ≠ buddy order：

| 页大小 | buffer size | SZ 编码 | buddy order | v4 free 用的值 | 结果 |
|--------|------------|---------|-------------|-------------|------|
| 4KB | 4KB | 0 | 0 | 0 | ✅ 正确 |
| 16KB | 16KB | 2 | 0 | 2 | ❌ 释放 4 个 16KB 页 = 64KB，越界 |
| 64KB | 64KB | 4 | 0 | 4 | ❌ 释放 16 个 64KB 页 = 1MB，严重越界 |

v5 在 `vcpu_hdbss_state` 中新增 `buddy_order` 字段，free 时直接用存储的值。同时用 `struct page *hdbss_pg` 替代 `base_phys`，消除 PA=0 的泄漏 bug（Sashiko S11）。

### 4.5 ioctl 配置接口

`KVM_CAP_ARM_HDBSS_BUFFER_SIZE` (cap 号 251)：

- **单位**：bytes（与 `KVM_CAP_DIRTY_LOG_RING` 一致）
- **QEMU 属性**：`hdbss-buffer-size=<entries>`（entries 为单位，QEMU 转 bytes 传 ioctl）
- **约束**：power of 2，范围 [PAGE_SIZE, SZ_2M]，必须在 vCPU 创建前设置
- **互斥**：与 dirty ring 互斥（dirty ring 模式下 kernel 自动配置）

---

## 5. Flush 路径设计

### 5.1 v4 多路径 Flush（有问题）

v4 在三个路径 flush HDBSS buffer：

| 路径 | 位置 | 问题 |
|------|------|------|
| `vcpu_put()` | `kvm_arch_vcpu_put()` 中调用 flush | **ABBA 死锁**：vcpu_put 在调度器 preempt notifier 上下文（持 rq->lock），flush 持 mmu_lock，其他路径持 mmu_lock 后 wake_up 需要 rq->lock |
| `check_vcpu_requests()` | 通过 `KVM_REQ_FLUSH_HDBSS` 触发 | **时序问题**：在 dirty_ring_check 之后执行，flush 设的 soft_full 本轮检查不到 |
| `sync_dirty_log()` | `KVM_REQ_FLUSH_HDBSS \| KVM_REQUEST_WAIT` | 功能正确但使用了 request 机制 |

### 5.2 v5 单路径 Flush（最终方案）

v5 只在一个地方 flush：**VM exit 后、`handle_exit_early()` 之前**（arm.c:1506-1518）。

```c
// kvm_arch_vcpu_ioctl_run() while 循环中
ret = kvm_arm_vcpu_enter_exit(vcpu);    // guest 运行

// ... sync hwstate ...

trace_kvm_exit(ret, ...);

// ★ 唯一 flush 点：每次 VM exit 都 flush
if (vcpu_hdbss_enabled(vcpu))
    kvm_flush_hdbss_buffer(vcpu);

handle_exit_early(vcpu, ret);
// ...
ret = handle_exit(vcpu, ret);
// → 回到 while 循环顶部 → check_vcpu_requests() → dirty_ring_check
```

### 5.3 为什么单路径是正确的

1. **每次 exit 都 flush**：跟 x86 PML 的 `__vmx_handle_exit()` 入口 `vmx_flush_pml_buffer()` 一致
2. **flush 后 dirty_ring_check 能检查到 soft_full**：flush 在 while 循环内的退出路径，下一轮的 `check_vcpu_requests()` → `kvm_dirty_ring_check_request()` 能看到 flush 推入的 entries
3. **不需要 vcpu_put 中 flush**：vcpu_put 在 while 循环外，flush 后设的 soft_full 要到下次 KVM_RUN 才检查，开销更大
4. **不需要 KVM_REQ_FLUSH_HDBSS**：每次 exit 无条件 flush，不需要 buffer-full fault 设 request

### 5.4 SRCU 保护

`kvm_flush_hdbss_buffer()` (dirty_bit.c:58-95) 中调用 `kvm_vcpu_mark_page_dirty()` → `mark_page_dirty_in_slot()` → `kvm_vcpu_gfn_to_memslot()` 访问 memslots 数组。memslots 数组由 SRCU 保护（不是 mmu_lock）。

```c
void kvm_flush_hdbss_buffer(struct kvm_vcpu *vcpu)
{
    // ...
    srcu_idx = srcu_read_lock(&kvm->srcu);          // ← SRCU 保护
    for (idx = 0; idx < min_t(u32, curr_idx, entries); idx++) {
        // ...
        kvm_vcpu_mark_page_dirty(vcpu, gpa >> PAGE_SHIFT);
        // → mark_page_dirty_in_slot() → set_bit_le() 或 kvm_dirty_ring_push()
    }
    srcu_read_unlock(&kvm->srcu, srcu_idx);

    write_sysreg_s(0, SYS_HDBSSPROD_EL2);  // reset producer index
    vcpu->arch.hdbss.hdbssprod_el2 = 0;
    isb();
}
```

`mark_page_dirty_in_slot()` 内部只做原子 `set_bit_le()` 或 per-vCPU `kvm_dirty_ring_push()`，不需要 mmu_lock。SRCU 保护 memslot 数组不被 `KVM_SET_USER_MEMORY_REGION` 并发重分配。

### 5.5 方案对比

| | v4 多路径 | v5 单路径 |
|---|---|---|
| flush 点 | vcpu_put + check_vcpu_requests + sync_dirty_log | VM exit 后唯一 |
| ABBA 风险 | 有（mmu_lock + rq->lock） | 无（无锁 + SRCU） |
| ring overflow 风险 | 有（vcpu_put flush 在 dirty_ring_check 之后） | 无（flush 在 dirty_ring_check 之前） |
| SRCU 保护 | 无（v4 没有） | 有 |
| x86 PML 对齐 | 不一致 | 一致 |

---

## 6. HDBSS Enable/Disable 与 VTCR 同步

### 6.1 arm64 VTCR_EL2 加载机制

VTCR_EL2 是 per-CPU 系统寄存器，只在 `kvm_vcpu_load_vhe()` (switch.c:228-236) 中通过 `__load_stage2(hw_mmu)` 加载：

```c
void kvm_vcpu_load_vhe(struct kvm_vcpu *vcpu)
{
    __vcpu_load_switch_sysregs(vcpu);
    __vcpu_load_activate_traps(vcpu);
    __load_stage2(vcpu->arch.hw_mmu);   // ← 写 VTCR_EL2 + VTTBR_EL2
    __load_hdbss(vcpu);                 // ← 写 HDBSSBR_EL2 + HDBSSPROD_EL2
}
```

`kvm_vcpu_load_vhe()` 在 `kvm_arch_vcpu_load()` 中调用，时机：
- KVM_RUN ioctl 开始时（`vcpu_load()`）
- CPU 迁移时（`kvm_sched_in()` preempt notifier）

**run loop 内部不 reload VTCR_EL2**。`__kvm_vcpu_run_vhe()` (switch.c:588-643) 注释明确：

```c
/*
 * Note that ARM erratum 1165522 requires us to configure both stage 1
 * and stage 2 translation for the guest context before we clear
 * HCR_EL2.TGE. The stage 1 and stage 2 guest context has already been
 * loaded on the CPU in kvm_vcpu_load_vhe().
 */
```

### 6.2 Enable/Disable 实现

`kvm_arm_enable_hdbss_global()` (dirty_bit.c:150-168)：

```c
static void kvm_arm_enable_hdbss_global(struct kvm *kvm)
{
    struct kvm_vcpu *vcpu;
    unsigned long i;

    if (!system_supports_hdbss())
        return;
    if (kvm_hdbss_enabled(kvm))  // 检查 sw VTCR
        return;

    kvm->arch.mmu.vtcr |= VTCR_EL2_HD | VTCR_EL2_HDBSS | VTCR_EL2_HA;

    kvm_for_each_vcpu(i, vcpu, kvm)
        kvm_vcpu_kick(vcpu);    // ← kick，不用 request
}
```

`kvm_arm_disable_hdbss_global()` (dirty_bit.c:173-192) 结构相同，清 VTCR 位 + kick。

### 6.3 为什么用 kick 而不是 request-handler

| 方案 | 描述 | stale 窗口 | 复杂度 |
|------|------|-----------|--------|
| kick（v5 最终） | 改 sw VTCR + `kvm_vcpu_kick` | 有（VTCR 在下次 vcpu_load 才 reload） | 低 |
| request-handler | 像 x86 的 `KVM_REQ_UPDATE_CPU_DIRTY_LOGGING`，handler 在 check_vcpu_requests 中 reload VTCR | 无 | 中 |
| KVM_REQ_OUTSIDE_GUEST_MODE | 改 sw VTCR + kick + 等待 vCPU 退出 | 有（同 kick，等待只等 IPI ack 不等 flush） | 中 |

选择 kick 的理由：

1. **arm64 无先例**：arm64 架构中除了 HDBSS，没有运行时修改 VTCR 的场景。arm64 的设计哲学是 VTCR 在 VM 创建时设好，之后不变。TLB flush 通过 `kvm_call_hyp()` 直接做，不需要 vCPU 参与
2. **stale 窗口可控**：
   - Enable 方向（sw=on, hw=off）：WC 页写在 HD=0 下走 software fault 路径，dirty tracking 正确，只是没有 HDBSS 收益。直到下次 KVM_RUN 的 vcpu_load 生效
   - Disable 方向（sw=off, hw=on）：标准迁移流程（stop vCPUs → final sync → disable）不会触发
3. **与 x86 sync_dirty_log 一致**：x86 的 `kvm_arch_sync_dirty_log()` 也用 `kvm_vcpu_kick()`
4. **HCR_EL2.VM=0 保证安全**：`kvm_vcpu_put_vhe()` → `__deactivate_traps()` → `write_sysreg_hcr(HCR_HOST_VHE_FLAGS)` 写 HCR_EL2.VM=0 关闭 stage-2，HDBSS 不能脱离 stage-2 单独工作

### 6.4 sync_dirty_log 用 kick

`kvm_arch_sync_dirty_log()` (arm.c:2090-2108)：

```c
void kvm_arch_sync_dirty_log(struct kvm *kvm, struct kvm_memory_slot *memslot)
{
    struct kvm_vcpu *vcpu;
    unsigned long i;

    if (!kvm_hdbss_enabled(kvm))
        return;

    kvm_for_each_vcpu(i, vcpu, kvm)
        kvm_vcpu_kick(vcpu);
}
```

与 x86 的 `kvm_arch_sync_dirty_log()` (x86.c:6705-6722) 完全一致。flush 在 VM exit path 中无条件执行（5.2 节），kick 只是加速 vCPU 退出。dirty-log 协议（GET/CLEAR）容忍并发 bitmap 写：bits set after snapshot 不在 CLEAR 掩码里，存活到下一轮。

---

## 7. Dirty Ring 适配

### 7.1 Dirty Ring Reservation 机制

Dirty ring 有一套 reservation 机制，为 CPU-side dirty buffer（如 PML/HDBSS）预留空间：

```
rsvd = KVM_DIRTY_RING_RSVD_ENTRIES + kvm_cpu_dirty_log_size(kvm)
     = 64 + hdbss_entries

soft_limit = ring_size - rsvd
```

`kvm_cpu_dirty_log_size()` (mmu.c:2805) arm64 实现：

```c
int kvm_cpu_dirty_log_size(struct kvm *kvm)
{
    if (!system_supports_hdbss())
        return 0;
    return (kvm->arch.hdbss_buffer_size ?: KVM_ARM_HDBSS_DEFAULT_SIZE) /
           sizeof(u64);
}
```

`KVM_DIRTY_RING_RSVD_ENTRIES` = 64 (kvm_host.h:2508)，为 software dirty marking 预留。

### 7.2 Buffer Size 自动配置

`kvm_arch_dirty_ring_size_updated()` (arm.c:266-290) 在 dirty ring size 设置后调用：

```c
void kvm_arch_dirty_ring_size_updated(struct kvm *kvm)
{
    if (!system_supports_hdbss())
        return;

    // 保留用户通过 ioctl 配置的值
    if (kvm->arch.hdbss_buffer_size)
        return;

    // dirty-ring 模式下固定用 PAGE_SIZE（最小值）
    kvm->arch.hdbss_buffer_size = KVM_ARM_HDBSS_DEFAULT_SIZE;
}
```

### 7.3 为什么固定 PAGE_SIZE（不动态算最大值）

v5 最初动态计算最大 buffer size（`rounddown_pow_of_two((ring_entries - 64) * 8)`），但性能测试发现**buffer 越大性能越差**：

| ring_entries | hdbss_entries | rsvd | soft_limit | drain_interval |
|---|---|---|---|---|
| 65536 | 512 (PAGE_SIZE) | 576 | 64960 | **65024** |
| 65536 | 32768 (auto) | 32832 | 32704 | 32768 |

buffer 越大 → rsvd 越大 → soft_limit 越小 → **drain 越频繁**。drain 开销（vCPU 退出到 userspace + QEMU harvest + 重入）远大于多几次 VM exit 的开销。

PAGE_SIZE（512 entries on 4KB page）给出最大的 drain interval，与 x86 PML 的固定 512 entries 一致。

完整分析见 `docs/hdbss_dirty_ring_analysis.md`。

### 7.4 Ring Overflow Bug 与修复

**Bug**：v5 初版的多路径 flush 导致 `WARN_ON_ONCE(kvm_dirty_ring_full(ring))` 在 live migration 测试中触发。

**根因**：`vcpu_put()` 中的 flush 在 while 循环外执行，push 的 entries 不受 soft_limit 保护。一次 flush 可能 push 数千 entries 到 ring，导致 ring 溢出。

**调用链**：
```
kvm_flush_hdbss_buffer()
  → kvm_vcpu_mark_page_dirty()
    → mark_page_dirty_in_slot()
      → kvm_dirty_ring_push()           ← ring 满了！WARN
```

**修复**：改为单路径 flush（5.2 节），每次 exit 只 flush 一轮 buffer，flush 后 `check_vcpu_requests()` → `kvm_dirty_ring_check_request()` 能检查到 soft_full 并退出到 userspace。

### 7.5 check_vcpu_requests 中的顺序

```c
// check_vcpu_requests() (arm.c:1221-1270)
if (kvm_check_request(KVM_REQ_SUSPEND, vcpu))
    return kvm_vcpu_suspend(vcpu);

// dirty ring check 在 flush 之后（flush 在 exit path，check 在 loop top）
if (kvm_dirty_ring_check_request(vcpu))
    return 0;  // 退出到 userspace drain ring

check_nested_vcpu_requests(vcpu);
```

注意：v5 不在 `check_vcpu_requests()` 中 flush HDBSS（已移除 `KVM_REQ_FLUSH_HDBSS`）。flush 在 exit path 中无条件执行，先于 `check_vcpu_requests()`。

---

## 8. 嵌套虚拟化保护

### 8.1 两层检查

| 检查函数 | 定义位置 | 检查字段 | 过滤层级 | 使用场景 |
|---------|---------|---------|---------|---------|
| `kvm_hdbss_enabled(kvm)` | `kvm_dirty_bit.h:33` | `kvm->arch.mmu.vtcr` | L1 only | enable/disable/sync_dirty_log/destroy |
| `vcpu_hdbss_enabled(vcpu)` | `kvm_dirty_bit.h:49` | `vcpu->arch.hw_mmu->vtcr` | L1 + L2 | flush/fault/load/put |

### 8.2 hw_mmu 切换

`vcpu->arch.hw_mmu` 在 `kvm_arch_vcpu_load()` (arm.c:771-772) 中切换：

```c
if (vcpu_has_nv(vcpu))
    kvm_vcpu_load_hw_mmu(vcpu);
// → L1 运行: hw_mmu = &kvm->arch.mmu (有 HDBSS 位)
// → L2 运行: hw_mmu = shadow_s2_mmu (无 HDBSS 位)
```

`kvm_vcpu_load_hw_mmu()` (nested.c:862)：
- `is_hyp_ctxt(vcpu)`（跑 L1）：`hw_mmu = &kvm->arch.mmu` → 有 HDBSS 位
- `!is_hyp_ctxt(vcpu)`（跑 L2）：`hw_mmu = get_s2_mmu_nested(vcpu)` → shadow S2 的 VTCR 由 `kvm_get_vtcr()` 设置，不含 HDBSS 位

### 8.3 为什么需要两层检查

- VM 级检查（`kvm_hdbss_enabled`）：在 enable/disable/sync_dirty_log 中使用，这些是 VM 级操作，只操作 L1 VM 的 VTCR
- vCPU 级检查（`vcpu_hdbss_enabled`）：在 flush/load/put/fault 中使用，这些是 per-vCPU 操作，需要知道当前实际使用的 S2 MMU 是否启用了 HDBSS

如果只用 VM 级检查：跑 L2 时 `kvm->arch.mmu.vtcr` 有 HDBSS 位 → 检查返回 true → 软件尝试 load/flush HDBSS 寄存器，但硬件实际跑的是 shadow S2（无 HDBSS）→ 错误。

---

## 9. HDBSSPROD_EL2 保存/恢复

### 9.1 保存（vCPU put 时）

`kvm_vcpu_put_vhe()` (switch.c:238-247)：

```c
void kvm_vcpu_put_vhe(struct kvm_vcpu *vcpu)
{
    if (vcpu_hdbss_enabled(vcpu))
        vcpu->arch.hdbss.hdbssprod_el2 = read_sysreg_s(SYS_HDBSSPROD_EL2);

    __vcpu_put_deactivate_traps(vcpu);   // ← HCR_EL2.VM=0，stage-2 关闭
    __vcpu_put_switch_sysregs(vcpu);
}
```

保存 producer index（硬件写入的 entry 数量）到软件结构体，供跨 CPU 迁移时恢复。

### 9.2 恢复（vCPU load 时）

`__load_hdbss()` (switch.c:217-226)：

```c
static void __load_hdbss(struct kvm_vcpu *vcpu)
{
    if (!vcpu_hdbss_enabled(vcpu))
        return;

    write_sysreg_s(vcpu->arch.hdbss.hdbssbr_el2, SYS_HDBSSBR_EL2);
    write_sysreg_s(vcpu->arch.hdbss.hdbssprod_el2, SYS_HDBSSPROD_EL2);
    isb();
}
```

恢复 buffer base address 和 producer index。调用点：`kvm_vcpu_load_vhe()` (switch.c:235)。

### 9.3 flush 后重置

`kvm_flush_hdbss_buffer()` (dirty_bit.c:92-95) flush 完后：

```c
write_sysreg_s(0, SYS_HDBSSPROD_EL2);      // 硬件 producer index 归零
vcpu->arch.hdbss.hdbssprod_el2 = 0;        // 软件副本也归零
isb();
```

下次 guest 运行时，硬件从 index 0 开始写入新 entries。

---

## 10. HDBSS Fault 处理

### 10.1 Fault 入口

`user_mem_abort()` (mmu.c:2276-2277)：

```c
if (esr_iss2_is_hdbssf(esr))
    return kvm_handle_hdbss_fault(vcpu);
```

`esr_iss2_is_hdbssf()` 检查 ESR_EL2.ISS2 的 HDBSSF bit（bit[11]）。当 HDBSS buffer 满或出错时，guest 写 WC 页会产生带 HDBSSF 标志的 Permission fault。

### 10.2 Fault Handler

`kvm_handle_hdbss_fault()` (dirty_bit.c:101-127)：

```c
int kvm_handle_hdbss_fault(struct kvm_vcpu *vcpu)
{
    // 防御性检查
    if (WARN_ON_ONCE(!system_supports_hdbss()))
        return -EFAULT;
    if (WARN_ON_ONCE(!vcpu_hdbss_enabled(vcpu)))
        return -EFAULT;

    prod = read_sysreg_s(SYS_HDBSSPROD_EL2);
    fsc = FIELD_GET(HDBSSPROD_EL2_FSC_MASK, prod);

    switch (fsc) {
    case HDBSSPROD_EL2_FSC_OK:
        // Buffer full — 不需要设 request，exit path 会无条件 flush
        return 1;    // handled，继续到 exit path flush
    case HDBSSPROD_EL2_FSC_ExternalAbort:
    case HDBSSPROD_EL2_FSC_GPF:
        return -EFAULT;
    default:
        WARN_ONCE(1, "Unexpected HDBSS fault type, FSC: 0x%llx ...");
        return -EFAULT;
    }
}
```

FSC_OK（buffer full）返回 1 → exit path 的 `kvm_flush_hdbss_buffer()` 会 flush → producer index 归零 → 硬件继续工作。

---

## 11. UAF 安全分析

### 11.1 完整销毁时序

```
1. QEMU 关闭所有 vCPU fd
   → kvm_vcpu_release(filp):
     → kvm_put_kvm(vcpu->kvm)    ← 减引用计数
   → vCPU 线程的 KVM_RUN 已返回（fd 关闭前必须返回）
   → 最后一次 KVM_RUN 的退出路径已 flush HDBSS buffer
   → vcpu_put() 已调用:
     → kvm_vcpu_put_vhe():
       → 保存 HDBSSPROD_EL2
       → __deactivate_traps():
         → write_sysreg_hcr(HCR_HOST_VHE_FLAGS)  ← HCR_EL2.VM=0!
   → vCPU 不在 guest 中，HCR_EL2.VM=0，HDBSS 硬件不会记录

2. QEMU 关闭 VM fd（最后一个引用）
   → kvm_put_kvm → refcount == 0 → kvm_destroy_vm():
     → kvm_arch_destroy_vm():
       → if (kvm_hdbss_enabled(kvm))  ← 防御性 disable
            kvm_arm_disable_hdbss_global(kvm)  ← 清 sw VTCR + kick (no-op)
       → kvm_destroy_vcpus():
         → kvm_vcpu_destroy():
           → kvm_arch_vcpu_destroy():
             → kvm_arm_vcpu_destroy():
               → kvm_arm_vcpu_free_hdbss():  __free_pages()  ← 安全！
```

### 11.2 安全保证

1. **vCPU fd 引用计数**：`kvm_destroy_vm()` 只在所有 vCPU fd 关闭后调用（`refcount_dec_and_test`），vCPU 线程不可能还在 KVM_RUN 中
2. **HCR_EL2.VM=0**：`vcpu_put()` → `__deactivate_traps()` 恢复 host HCR_EL2（VM=0），stage-2 关闭，HDBSS 不能脱离 stage-2 工作
3. **buffer 只在 vCPU destroy 时释放**：disable 时不释放（PML-style），避免了 disable + free 的竞态窗口

### 11.3 v4 的 UAF 问题（Sashiko S18）

v4 在 `kvm_arm_disable_hdbss_global()` 中直接 free buffer，而 vCPU 可能还在 guest 中跑（硬件 HDBSS 还在写 buffer）。v5 修复：disable 只清 VTCR 位 + kick，buffer 在 vCPU destroy 时释放。

---

## 12. 已知限制与遗留问题

### 12.1 VHE-Only

当前实现是 VHE-only。`kvm_flush_hdbss_buffer()` 和 `kvm_handle_hdbss_fault()` 中直接访问 `SYS_HDBSSPROD_EL2` 等 EL2 寄存器，需要 EL2 访问权限。nVHE 模式下 host kernel 运行在 EL1，访问 EL2 寄存器会触发 undefined instruction。nVHE 支持需要将寄存器访问移到 hyp 代码中。

### 12.2 pKVM 未适配

pKVM 模式下 guest 的 stage-2 页表在 EL2 通过 `pkvm_guest_prepare_stage2()` 初始化，无条件传递 `flags=0`。v5 的 DBM 无条件设置（Phase 6.1）已移除了 flag 依赖，但 pKVM 的 stage-2 初始化路径仍需检查是否正确设置 DBM。pKVM 的 HDBSS 集成作为后续工作。

### 12.3 HDBSS Module Parameter 未实现

x86 PML 有 `enable_pml` module parameter（`kvm_intel.pml=0` 全局禁用）。HDBSS 目前没有对应的 module parameter，用户无法在运行时禁用 HDBSS 回退到纯软件 dirty tracking。作为后续工作，参考 x86 添加 `kvm_arm.hdbss=0`。

### 12.4 stale-hardware 窗口

enable/disable 后，硬件 VTCR_EL2 到下次 `vcpu_load` 才更新。标准迁移流程安全（stop vCPUs → sync → disable），但非标准流程（vCPU 跑着时切 dirty logging）理论上可能触发 HDBSS buffer full fault（disable 方向）。详见 6.3 节分析。
