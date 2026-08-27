# HDBSS DBM 与 S2AP 修改路径分析

## 1. 背景

ARM64 Stage-2 页表使用三态模型管理 dirty state：

| 状态 | DBM | S2AP[1] (W) | 含义 |
|------|-----|-------------|------|
| N (Non-writable) | 0 | 0 | 写 → fault |
| C (Writable-clean) | 1 | 0 | 写 → 硬件 C→D + HDBSS 记录 |
| D (Writable-dirty) | 1 | 1 | 可写，无 fault |

**设计原则**：所有修改 S2AP 的软件路径必须紧跟 DBM 的修改，确保不会出现 DBM 和 S2AP 不一致的状态。

## 2. 所有修改 DBM 的代码路径

### 2.1 `stage2_set_prot_attr()` — 初始映射

**文件**：`arch/arm64/kvm/hyp/pgtable.c:734-750`

```c
if (prot & KVM_PGTABLE_PROT_W) {
    attr |= KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W;    // 设 W
    attr |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;       // 设 DBM
}
```

**分析**：S2AP_W 和 DBM 在同一个 `if (prot & KVM_PGTABLE_PROT_W)` 块中设置。有 W 就有 DBM，没有 W 就都没有。

**调用场景**：
- 初始页表映射（`kvm_pgtable_stage2_map`）
- 大页 split 的子页创建（`kvm_pgtable_stage2_create_unlinked`）

**结论**：✅ S2AP_W 和 DBM 紧跟

### 2.2 `kvm_pgtable_stage2_wrprotect()` — 写保护

**文件**：`arch/arm64/kvm/hyp/pgtable.c:1313-1319`

```c
int kvm_pgtable_stage2_wrprotect(struct kvm_pgtable *pgt, u64 addr, u64 size)
{
    return stage2_update_leaf_attrs(pgt, addr, size, 0,
                    KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W,  // 清 W
                    NULL, NULL, KVM_PGTABLE_WALK_IGNORE_EAGAIN);
}
```

walker 回调 `stage2_attr_walker()` (line 1249-1260)：

```c
pte &= ~data->attr_clr;      // 清 S2AP_W
pte |= data->attr_set;

// block entry 额外清 DBM
if (ctx->level < KVM_PGTABLE_LAST_LEVEL)
    pte &= ~KVM_PTE_LEAF_ATTR_HI_S2_DBM;
```

**分析**：
- Block entry：清 S2AP_W + 清 DBM → RO 状态 (DBM=0, W=0)
- Level-3 page：清 S2AP_W + 保留 DBM → WC 状态 (DBM=1, W=0)

**调用场景**：
- `kvm_mmu_wp_memory_region()` — dirty logging 开启时写保护整个 memslot
- `kvm_arch_mmu_enable_log_dirty_pt_masked()` — CLEAR ioctl 逐批写保护

**结论**：✅ S2AP_W 和 DBM 紧跟（block 清 DBM，page 保留 DBM 符合设计）

### 2.3 `kvm_pgtable_stage2_relax_perms()` — 放宽权限

**文件**：`arch/arm64/kvm/hyp/pgtable.c:1395-1398`

```c
if (prot & KVM_PGTABLE_PROT_W) {
    set |= KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W;    // 设 W
    set |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;       // 设 DBM
}
```

**分析**：S2AP_W 和 DBM 在同一个 `if (prot & KVM_PGTABLE_PROT_W)` 块中设置。

**调用场景**：
- `user_mem_abort()` — write fault 后恢复写权限 (RO → WD)
- 页面从 RO/WC 状态恢复为 WD (DBM=1, S2AP_W=1)

**结论**：✅ S2AP_W 和 DBM 紧跟

## 3. Split 路径的 DBM 继承

### 3.1 大页 split 流程

```
stage2_split_walker()
  → prot = kvm_pgtable_stage2_pte_prot(pte)  // 提取原 block 的 prot
  → kvm_pgtable_stage2_create_unlinked(phys, level, prot, ...)
    → stage2_set_prot_attr(pgt, prot, &map_data.attr)  // 用 prot 设置子页属性
    → stage2_map_walker_try_leaf()  // 创建子页 PTE
```

### 3.2 Split 时的 block 状态

Split 总是在 wrprotect **之后**执行：

```
kvm_arch_commit_memory_region():
  kvm_mmu_wp_memory_region()   // 1. wrprotect: block → RO (DBM=0, W=0)
  kvm_mmu_split_memory_region() // 2. split: 拆成 level-3 pages
```

wrprotect 后 block 状态为 RO (DBM=0, S2AP_W=0)。split 提取 prot 时 `prot` 不含 W，`stage2_set_prot_attr` 不会设 S2AP_W 也不会设 DBM。

**子页状态**：DBM=0, S2AP_W=0 (RO) — 继承 block 的 RO 状态。

### 3.3 首次写 fault 后恢复

子页 RO → guest 写 → fault → `user_mem_abort()` → `kvm_pgtable_stage2_relax_perms(prot=W)` → 设 S2AP_W + DBM → WD 状态。

**结论**：✅ Split 路径正确继承 RO 状态，首次写 fault 后由 relax_perms 恢复 W + DBM

## 4. 硬件自动更新路径

### 4.1 C→D 转换（HDBSS 启用时）

当 guest 写 WC 页 (DBM=1, S2AP_W=0)：
- 硬件自动设 S2AP_W=1 → 页变为 WD
- 硬件记录 IPA 到 HDBSS buffer
- **不需要软件干预**
- DBM 保持 1（不需要改）

### 4.2 C→D 转换（HDBSS 未启用，HD=0）

当 guest 写 WC 页 (DBM=1, S2AP_W=0)：
- 硬件自动设 S2AP_W=1 → 页变为 WD
- **不记录到 HDBSS**（HDBSS 未启用）
- 软件通过 write-protect fault 检测脏页

### 4.3 D→C 转换（软件操作）

软件通过 `kvm_pgtable_stage2_wrprotect()` 做 D→C：
- 清 S2AP_W → 页变为 WC (page) 或 RO (block)
- page 保留 DBM=1 → HDBSS 可重新 arm
- block 清 DBM=0 → 强制 fault → split

## 5. 完整生命周期

### 5.1 Dirty logging 开启

```
1. wrprotect:
   - Block → RO (DBM=0, S2AP_W=0)
   - Level-3 page → WC (DBM=1, S2AP_W=0)

2. split (eager):
   - Block 拆成 level-3 pages, 子页继承 RO (DBM=0, S2AP_W=0)
```

### 5.2 Guest 写页

```
3a. WC page (DBM=1, S2AP_W=0):
    → 硬件 C→D: 设 S2AP_W=1, 记录 HDBSS → WD (DBM=1, S2AP_W=1)

3b. RO page (DBM=0, S2AP_W=0):
    → write fault → user_mem_abort() → relax_perms(W)
    → 设 S2AP_W=1 + DBM=1 → WD (DBM=1, S2AP_W=1)
```

### 5.3 下一轮 dirty tracking

```
4. wrprotect:
   - WD page → WC (清 S2AP_W, 保留 DBM)
   - Block → RO (清 S2AP_W + 清 DBM)

5. 回到 step 3
```

## 6. 总结

| 路径 | S2AP 修改 | DBM 修改 | 跟随？ |
|------|----------|---------|--------|
| `stage2_set_prot_attr` (初始映射) | 设 W | 设 DBM | ✅ 同一 if 块 |
| `kvm_pgtable_stage2_wrprotect` (block) | 清 W | 清 DBM | ✅ walker 中 |
| `kvm_pgtable_stage2_wrprotect` (page) | 清 W | 保留 DBM | ✅ 设计如此 (WC) |
| `kvm_pgtable_stage2_relax_perms` (W 放宽) | 设 W | 设 DBM | ✅ 同一 if 块 |
| `stage2_split_walker` (split) | 继承 prot (无 W) | 不设 DBM | ✅ 继承 RO |
| 硬件 C→D (HDBSS) | 硬件设 W=1 | DBM 保持 1 | ✅ 硬件行为 |

**没有遗漏。** 所有修改 S2AP 的软件路径都紧跟 DBM 的修改。hardware update 路径不需要软件干预。
