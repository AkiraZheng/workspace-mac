# 动态添加 DBM 标签设计方案分析

## 一、DBM 在 Stage-2 页表中的位置和作用

### 1.1 Stage-2 PTE 结构

```
┌─────────────────────────────────────────────────────────────┐
│  Stage-2 PTE (64-bit)                                      │
├─────────────────────────────────────────────────────────────┤
│  Bit 63-52: reserved or implementation-defined              │
│  Bit 51:    DBM (Dirty Bit Modifier) ← 关键!              │
│  Bit 7:     S2AP_W (Write Permission)                     │
│  Bit 6:     S2AP_R (Read Permission)                      │
│  ...                                                        │
└─────────────────────────────────────────────────────────────┘
```

**定义**：
```c
#define PTE_DBM          BIT(51)     // Dirty Bit Management
#define S2AP_W           BIT(7)      // Stage-2 Write Permission
#define S2AP_R           BIT(6)      // Stage-2 Read Permission
```

### 1.2 DBM 的工作机制

```
初始状态：
    S2 PTE: Writable-Clean (DBM=1, S2AP_W=0)

Guest写内存触发：
    硬件自动完成：
    1. 允许写入
    2. S2AP_W 从 0 → 1 (变成 Writable-Dirty)
    3. 将页记录到 HDBSS buffer
```

---

## 二、Writable-Clean vs Writable-Dirty 详解

### 2.1 S2AP 位定义

| S2AP[1:0] | 权限 |
|-----------|------|
| 00 | 无访问 |
| 01 | 只读 (R=1, W=0) |
| 10 | 保留 |
| 11 | 读写 (R=1, W=1) |

### 2.2 三种状态对比

| 状态 | DBM (51) | S2AP_W (7) | S2AP_R (6) | 含义 |
|------|----------|-------------|-------------|------|
| **RO** (只读) | 0 | 0 | 1 | 只读，不能写 |
| **WC** (Writable-Clean) | 1 | 0 | 1 | 可写，首次写变脏 |
| **WD** (Writable-Dirty) | 1 | 1 | 1 | 可写，已脏 |

### 2.3 关键理解

**Writable-Clean 的 "Clean" 不是指 "只读"**：
- S2AP_W = 0（写入会被允许，只是会触发脏跟踪）
- DBM = 1（启用脏跟踪）

**Writable-Clean 的含义**：
- 软件视角：还没脏，可以安全读取
- 物理上：第一次写入会成功，并触发脏状态转换

**硬件行为**：
```
WC (DBM=1, S2AP_W=0):
    Guest发起写
    ↓
    硬件允许写入
    ↓
    S2AP_W 0→1 (变成WD)
    ↓
    记录到HDBSS buffer
```

---

## 三、当前 HDBSS 设计中的 DBM 处理

### 3.1 启用/禁用流程

**启用**：
```c
if (enable) {
    // 为每个VCPU分配HDBSS buffer页
    // 设置VTCR_EL2的HD/HDBSS/HA位
    kvm->arch.mmu.vtcr |= VTCR_EL2_HD | VTCR_EL2_HDBSS | VTCR_EL2_HA;
    kvm->arch.enable_hdbss = true;
}
```

**禁用**：
```c
if (!enable) {
    // 清除VTCR_EL2的HDBSS位
    kvm->arch.mmu.vtcr &= ~(VTCR_EL2_HD | VTCR_EL2_HDBSS | VTCR_EL2_HA);
    // 释放buffer
    kvm_for_each_vcpu(i, vcpu, kvm)
        kvm_arm_vcpu_free_hdbss(vcpu);
    kvm->arch.enable_hdbss = false;
}
```

### 3.2 当前实现的限制

**当前设计中**：
- ✅ 启用时添加 DBM
- ❌ **禁用时没有清除 DBM 的操作**

这意味着：
1. DBM 是累积的
2. 迁移完成后 HDBSS 虽然禁用，但 DBM 位仍在页表中
3. 如果 VTCR_EL2.HDBSS=0 时 Guest 写内存，行为可能不符合预期

---

## 四、两种设计方案对比

### 4.1 当前设计（迁移时才加DBM）

| 阶段 | 操作 |
|------|------|
| 预迁移 | 遍历所有可写页，添加DBM |
| 迭代迁移 | HDBSS跟踪脏页 |
| 迁移完成 | 禁用HDBSS（不清除DBM） |

**优点**：
- 权限变更路径简单

**缺点**：
- 迁移开始时有抖动（大量write fault）

### 4.2 提议设计（创建时就加DBM）

| 阶段 | 操作 |
|------|------|
| 页创建 | 添加DBM |
| 正常运行 | HDBSS跟踪脏页 |
| 迁移 | 直接开始，无抖动 |

**优点**：
- 无迁移开始时的抖动

**缺点**：
- 需要在所有权限变更路径上处理DBM

---

## 五、需要防护的代码路径

### 5.1 添加 DBM 的路径

| 路径 | 触发场景 | 需要添加DBM？ |
|------|---------|-------------|
| `user_mem_abort()` | Guest写fault (RO→RW) | ✅ 已实现 |
| `kvm_pgtable_stage2_relax_perms()` | RO → RW | ✅ 需要检查 |
| `kvm_pgtable_stage2_map()` | 新建可写映射 | ✅ 需要检查 |
| `stage2_set_prot_attr()` | 设置权限 | ✅ 需要检查 |

### 5.2 清除 DBM 的路径

| 路径 | 触发场景 | 需要清除DBM？ |
|------|---------|-------------|
| 改成 RO | KVM_PGTABLE_PROT_W → 移除 | ✅ 需要 |
| 改成 Device/Normal-NC | 非RAM类型 | ✅ 需要 |
| 页unmap | 删除映射 | ❌ 自然消失 |
| 页删除 | 整个slot删除 | ❌ 自然消失 |

### 5.3 不需要处理的路径

| 路径 | 场景 | 为什么不需要 |
|------|------|------------|
| `stage2_wp_range()` | 迁移清除脏位 | 只是临时清除S2AP_W，不改变权限 |
| HDBSS enable/disable | 开关特性 | DBM是页的属性，不是全局开关 |

---

## 六、关键问题：如何区分临时清除和权限变更

### 6.1 临时清除 S2AP_W（迁移清除）

```
stage2_wp_range() 当前实现：
    清除 S2AP_W，但不清除 DBM

    WC (DBM=1, S2AP_W=0)
        ↓
    Guest下次写 → WD + 记录 (继续跟踪) ✓
```

### 6.2 权限变更导致的只读

```
需要清除DBM的场景：
    RW → RO：清除DBM ✓
    RW → Device：清除DBM ✓
    RW → Normal-NC：清除DBM ✓
```

### 6.3 迁移场景分析

```
正常热迁移流程：

源端 WD (DBM=1, S2AP_W=1)
    ↓
迁移开始，stage2_wp_range
    ↓
WC (DBM=1, S2AP_W=0) ← 迁移清除脏位，但DBM保持 ✓

    ...迁移进行中，页被复制到目标端...

迁移完成后，源端VM：
    可能1：页继续使用 → WC → Guest写 → WD + HDBSS记录
    可能2：页被释放/swap/变成只读 → 需要检查是否清DBM
```

### 6.4 核心原则

**不需要区分的场景**：
- 迁移清除脏位：WC，保持 DBM ✅（`stage2_wp_range` 只清 S2AP_W）
- 继续跟踪：Guest写 → WD + 记录 ✅

**需要清除DBM的场景**：
- 永久改变权限（RO/Device）→ 清除 DBM ✅

---

## 七、清除 DBM 的策略

### 7.1 迁出端 vs 迁入端的 DBM 处理

**关键认知**：
```
HDBSS 的使用场景：
    迁出端（Source）：  启用 HDBSS → 迁移 → 禁用 HDBSS
    迁入端（Destination）：不使用 HDBSS（只接收脏页）
```

**迁出端禁用 HDBSS 时清除 DBM 是多余的**：
```
迁出端：
    页已迁移到目标端
    源端页表项是 RO 或释放
    在源端清 DBM → 没有任何影响 ❌

迁入端：
    页正常可写
    如果页权限变更 → 可能需要清除 DBM ✅
```

**结论**：迁入端没有"禁用 HDBSS"的说法，因为迁入端本来就不使用 HDBSS。

### 7.2 唯一需要清除 DBM 的场景

| 场景 | 是否清除 DBM | 说明 |
|------|-------------|------|
| **页权限变更：Writable → Non-writable** | ✅ 需要 | 迁入端实际使用的页 |
| HDBSS 迁出端禁用 | ❌ 不需要 | 页已迁走，无意义 |
| HDBSS 迁入端禁用 | ❌ 不存在 | 迁入端不启用 HDBSS |

**代码路径**：
```c
// 在权限变更函数中（如 kvm_pgtable_stage2_relax_perms）
if (old_prot & KVM_PGTABLE_PROT_W && !(new_prot & KVM_PGTABLE_PROT_W)) {
    // 可写 → 非可写
    if (ptep->dbm) {
        clear DBM;  // ← 变成非可写时清除 DBM
    }
}
```

**注意**：`stage2_wp_range()` 临时清除 S2AP_W 是迁移清除，不应该清除 DBM，因为迁移清除后页仍然是 Writable-Clean 状态，需要继续跟踪脏页。

---

## 八、Stage-2 页表权限变更场景分析

### 8.1 权限变更的代码路径

| 场景 | 函数 | 触发条件 |
|------|------|---------|
| **Permission Fault 解决** | `kvm_pgtable_stage2_relax_perms()` | RO→RW（Guest写只读页） |
| **普通内存映射** | `kvm_pgtable_stage2_map()` | 新建映射，fault时 |
| **Device MMIO 重映射** | `kvm_pgtable_stage2_map()` | Device内存映射 |
| **脏页日志（写保护）** | `kvm_pgtable_stage2_wrprotect()` | RW→RO（dirty logging） |
| **CoW 页面处理** | `kvm_pgtable_stage2_map()` | CoW时R→RW |
| **Access Fault** | `kvm_pgtable_stage2_mkyoung()` | 只改AF位，不改权限 |

### 8.2 非迁移场景的 W→R 路径分析

**结论：不存在非迁移场景的 W→R 权限变更。**

`kvm_pgtable_stage2_wrprotect()` 是唯一清除 S2AP_W 的函数，但它的调用者**只有两个**：

| 位置 | 函数 | 用途 |
|------|------|------|
| `mmu.c:1190` | `kvm_mmu_wp_memory_region()` | Dirty logging / 迁移 |
| `mmu.c:1251` | `kvm_arch_mmu_enable_log_dirty_pt_masked()` | Dirty logging / 迁移 |

**没有其他调用者**。

这意味着：**不需要在非迁移路径清除 DBM**。

### 8.3 Huge Page 拆分时 DBM 丢失

**问题**：`kvm_pgtable_stage2_pte_prot()` 不提取 DBM，导致拆分时 DBM 丢失。

```c
// pgtable.c:721-736
enum kvm_pgtable_prot kvm_pgtable_stage2_pte_prot(kvm_pte_t pte)
{
    // ...
    if (pte & KVM_PTE_LEAF_ATTR_LO_S2_S2AP_R)
        prot |= KVM_PGTABLE_PROT_R;
    if (pte & KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W)
        prot |= KVM_PGTABLE_PROT_W;
    if (!(pte & KVM_PTE_LEAF_ATTR_HI_S2_XN))
        prot |= KVM_PGTABLE_PROT_X;
    
    // ❌ 没有提取 DBM！
    return prot;
}
```

**拆分流程**：
```
大页 DBM=1
    ↓
stage2_split_walker()
    ↓
prot = kvm_pgtable_stage2_pte_prot(pte)  // DBM 未提取
    ↓
kvm_pgtable_stage2_create_unlinked(..., prot, ...)
    ↓
小页 DBM=0 ❌
```

**解决方案**：在 `kvm_pgtable_stage2_pte_prot()` 中添加 DBM 提取：
```c
if (pte & KVM_PTE_LEAF_ATTR_HI_S2_DBM)
    prot |= KVM_PGTABLE_PROT_DBM;
```

**Fault 时添加 DBM 方案的优势**：大页拆成小页后，第一次访问每个小页会触发 fault，自然会添加 DBM，无需在拆分时传递。

---

## 九、关键 Bug：`stage2_pte_needs_update` 把 DBM 视为无关位

### 9.1 问题描述

```c
// pgtable.c:738-744
static bool stage2_pte_needs_update(kvm_pte_t old, kvm_pte_t new)
{
    if (!kvm_pte_valid(old) || !kvm_pte_valid(new))
        return true;

    return ((old ^ new) & (~KVM_PTE_LEAF_ATTR_S2_PERMS));
}
```

`KVM_PTE_LEAF_ATTR_S2_PERMS` 只包含：
- S2AP_R (bit 6)
- S2AP_W (bit 7)
- S2_XN (bit 54)

**DBM (bit 51) 不在 S2_PERMS 里**，所以如果新旧 PTE 只有 DBM 不同，函数返回 `false`，PTE **不会被更新**！

### 9.2 问题场景

**场景 1：尝试清除 DBM（但其他权限不变）**

```c
// old PTE: DBM=1, S2AP_W=1
// new PTE: DBM=0, S2AP_W=1

// 差异只有 DBM
(old ^ new) & (~KVM_PTE_LEAF_ATTR_S2_PERMS) = DBM bit
// 但 ~KVM_PTE_LEAF_ATTR_S2_PERMS 不包含 DBM
// 结果 = 0 → 返回 false → PTE 不更新 ❌
```

**场景 2：PTE 重映射时 DBM 变化被忽略**

```c
// stage2_map_walker_try_leaf() 中
if (!stage2_pte_needs_update(ctx->old, new))
    return -EAGAIN;  // DBM 变化被忽略
```

### 9.3 解决方案

**方案 1**：修改 `stage2_pte_needs_update`，把 DBM 加入比较
```c
#define KVM_PTE_LEAF_ATTR_S2_PERMS   (KVM_PTE_LEAF_ATTR_LO_S2_S2AP_R | \
                                       KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W | \
                                       KVM_PTE_LEAF_ATTR_HI_S2_XN | \
                                       KVM_PTE_LEAF_ATTR_HI_S2_DBM)  // 添加
```

**方案 2**：单独处理 DBM 的情况
```c
static bool stage2_pte_needs_update(kvm_pte_t old, kvm_pte_t new)
{
    if (!kvm_pte_valid(old) || !kvm_pte_valid(new))
        return true;

    if ((old ^ new) & ~KVM_PTE_LEAF_ATTR_S2_PERMS)
        return true;
    
    if ((old ^ new) & KVM_PTE_LEAF_ATTR_HI_S2_DBM)
        return true;
    
    return false;
}
```

---

## 十、DBM 丢失场景总结

| 场景 | 是否会丢 DBM | 原因 |
|------|-------------|------|
| **大页拆分** | ❌ 丢 | `kvm_pgtable_stage2_pte_prot()` 不提取 DBM |
| **尝试清除 DBM（其他权限不变）** | ❌ 丢 | `stage2_pte_needs_update` 把 DBM 视为无关 |
| **PTE 重映射时 DBM 变化** | ❌ 被忽略 | 同上 |
| **Unmap** | ✅ 自然丢失 | PTE 被清零 |

---

## 十一、其他属性位丢失情况

`kvm_pgtable_stage2_pte_prot()` 还丢失以下位：

| 位 | 说明 | 是否需要修复 |
|---|---|---|
| **DBM** | Dirty Bit Management | ✅ 需要 |
| SH | Shareability | ⚠️ 拆分时强制为 Inner-Sharable |
| AF | Access Flag | ⚠️ 拆分时强制为 1 |
| MEMATTR | Memory Attributes | ⚠️ 拆分时强制为 Normal |

其他位（SH, AF, MEMATTR）当前被强制设置为默认值，这可能是预期行为。只有 DBM 需要修复，因为它影响 HDBSS 脏页跟踪功能。

---

## 十二、边界情况分析

### 12.1 Huge Page 拆分

```
大页 DBM=1 → 拆分后每个小页
    需要确保 DBM 状态传递到子页
```

### 12.2 Memory Slot 属性变更

```
场景：从 Normal RAM → Device MMIO
    需要清除 DBM ✓
```

### 12.3 Page Migration (页迁移)

```
问题：页移动到新物理地址，DBM状态需要跟随吗？

分析：
    - DBM 跟踪的是 GPA (Guest物理地址)
    - 页迁移后，GPA 不变，HPA 变了
    - 所以 DBM 不需要"跟随"页
    - 但迁移过程中源页变成只读，需要处理
```

---

## 十三、总结：核心设计原则

### 13.1 添加 DBM 的时机

| 情况 | 是否添加DBM | 说明 |
|------|-----------|------|
| RO → RW | ✅ 添加 | 变成可写，需要跟踪 |
| 新建可写映射 | ✅ 添加 | 同上 |
| 临时清除 S2AP_W | ❌ 不添加 | 迁移清除，不需要 |
| HDBSS enable时批量添加 | ✅ 添加 | 迁移开始时 |

### 13.2 清除 DBM 的时机

| 情况 | 是否清除DBM | 说明 |
|------|-----------|------|
| RW → RO | ✅ 清除 | 不再需要跟踪 |
| RW → Device | ✅ 清除 | 非RAM类型 |
| 临时清除 S2AP_W | ❌ 清除 | 迁移清除，保持跟踪 |
| 页unmap/删除 | ❌ 清除 | 自然消失 |

### 13.3 最核心的规则

```
变成可写 → 添加DBM
变成非可写 → 清除DBM
临时清除S2AP_W (迁移清除) → 不动DBM
```

---

## 十四、结论

1. **Writable-Clean** 的 S2AP 位是 `01`（只读），但由于 DBM=1，写入会触发脏跟踪而非真正拒绝

2. **当前 HDBSS 实现** 在禁用时不清除 DBM，可能导致预期外的行为（但迁出端禁用 HDBSS 时不需要清除 DBM，因为页已迁移走）

3. **没有非迁移场景的 W→R 路径**，所以不需要在日常权限变更时清除 DBM

4. **`stage2_wp_range` 只需要清除 S2AP_W**，不需要清除 DBM（迁移清除是临时的）

5. **Huge Page 拆分时 DBM 丢失**：`kvm_pgtable_stage2_pte_prot()` 不提取 DBM，需要修复

6. **关键 Bug**：`stage2_pte_needs_update` 把 DBM 视为无关位，导致清除 DBM 操作被忽略，需要修复

7. **核心原则**：变成可写就加 DBM，变成非可写就清 DBM，迁移清除不动 DBM

8. **Fault 时添加 DBM 方案的优势**：大页拆成小页后，第一次访问每个小页会触发 fault，自然会添加 DBM，无需在拆分时传递

---

*整理时间：2026-05-08 22:00*
