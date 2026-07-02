# 1: 去掉 ioctl + 自动使能 HDBSS + S2_DBM flag 方案

## 0. 目标

1. 取消 `KVM_ENABLE_CAP` ioctl 使能 HDBSS 的路径
2. 在第一个 vCPU 创建时自动 enable HDBSS, 后续 vCPU (含热插拔) 自动分配 buffer
3. 引入 `KVM_PGTABLE_S2_DBM` flag, DBM 由 pgtable 层自动管理, caller 不再需要关心
4. HDBSS 开启后 VM 生命周期内不关闭, 销毁时清理
5. buffer order 固定为 0 (4KB), 预留阶梯选择接口

---

## 1. 全局架构

```
QEMU                               Kernel
─────                               ──────
KVM_CREATE_VM
KVM_SET_USER_MEMORY_REGION
KVM_CREATE_VCPU (vcpu 0)  ──→      kvm_arch_vcpu_create()
                                      ├─ hdbss_alloc_vcpu_buffer(vcpu, 0)
                                      └─ hdbss_enable_internal(kvm)
                                         ├─ vtcr |= HD|HDBSS|HA
                                         └─ enable_hdbss = true
KVM_CREATE_VCPU (vcpu 1..N)  ──→    kvm_arch_vcpu_create()
                                      └─ hdbss_alloc_vcpu_buffer(vcpu, 0)
KVM_CREATE_VCPU (hotplug)    ──→    kvm_arch_vcpu_create()
                                      └─ hdbss_alloc_vcpu_buffer(vcpu, 0) // order 取自全局
KVM_RUN → guest 首次缺页   ──→      stage2_set_prot_attr()
                                      └─ flag & S2_DBM → PTE |= DBM (自动)
```

### 禁止 disable 的原因

- 关闭 HDBSS 需 clear VTCR HD/HDBSS/HA + 遍历百万级 S2 PTE 逐条清除 DBM + 暂停全部 vCPU
- ARM 规范: VTCR_EL2.HD=0 时 DBM 位被硬件忽略, 安全
- HDBSS buffer 持续记录无消费者仅浪费内存带宽, 无副作用
- 下次迁移时 HDBSS 已就位, DBM 全在 PTE 上, **省一次全量 write trap**

---

## 2. 修改详情

### 2.1 `arch/arm64/include/asm/kvm_pgtable.h` (1 处)

**行 255-258: enum 新增 BIT(2)**

```c
enum kvm_pgtable_stage2_flags {
    KVM_PGTABLE_S2_IDMAP        = BIT(0),
    KVM_PGTABLE_S2_AS_S1        = BIT(1),
    KVM_PGTABLE_S2_DBM          = BIT(2),
};
```

> 此 flag 存储在 `pgt->flags` 中, 在 `kvm_init_stage2_mmu()` 之后、首次页映射之前设置。
> pgtable 层的 `stage2_set_prot_attr()` / `relax_perms()` 据此自动处理 DBM。

---

### 2.2 `arch/arm64/kvm/hyp/pgtable.c` (3 处)

#### 2.2.1 `stage2_set_prot_attr()` — map 路径自动加 DBM (L737-738)

```c
// Before:
    if (prot & KVM_PGTABLE_PROT_DBM)
        attr |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;

// After:
    if (prot & KVM_PGTABLE_PROT_DBM)
        attr |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;
    else if ((pgt->flags & KVM_PGTABLE_S2_DBM) &&
             (prot & KVM_PGTABLE_PROT_W) &&
             !(prot & KVM_PGTABLE_PROT_DEVICE))
        attr |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;
```

> 调用方范围: `kvm_pgtable_stage2_map()`, `kvm_pgtable_stage2_create_unlinked()`
>
> **DBM 决策表:**
>
> | prot 含 W | prot 含 DEVICE | flag S2_DBM | 结果 |
> |:---:|:---:|:---:|------|
> | ✓ | × | ✓ | **自动加 DBM** (普通可写页首次创建) |
> | ✓ | ✓ | ✓ | 不加 (设备 MMIO, 由 DEVICE 过滤) |
> | × | × | ✓ | 不加 (只读页, caller 可显式传 DBM for RO+DBM) |
> | × | × | × | 不加 (HW 不支持) |

#### 2.2.2 `kvm_pgtable_stage2_relax_perms()` — fault 路径自动加 DBM (L1376-1377)

```c
// Before:
    if (prot & KVM_PGTABLE_PROT_DBM)
        set |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;

// After:
    if ((prot & KVM_PGTABLE_PROT_DBM) ||
        ((pgt->flags & KVM_PGTABLE_S2_DBM) && (prot & KVM_PGTABLE_PROT_W)))
        set |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;
```

> 首次缺页 `kvm_s2_fault_compute_prot` 计算出的 prot 不含 DBM (已删除),
> 但 flag + W 条件满足, relax_perms 自动给新增的可写页打上 DBM。

#### 2.2.3 `kvm_pgtable_stage2_relax_perms()` — 权限降级清除 DBM (L1377 之后)

```c
    // After the set lines, add:
    else
        clr |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;
```

> 非迁移场景下 W→RO 降级时清除 DBM, 防止硬件残留 DBM 位导致错误的写升级。
> 迁移 WP 路径 (`kvm_pgtable_stage2_wrprotect`) 只清 W 不清 DBM, 符合语义。

---

### 2.3 `arch/arm64/kvm/mmu.c` (4 处)

#### 2.3.1 新增 `hdbss_auto_select_order()` — 缓冲区大小选择

```c
/*
 * Automatically select HDBSS buffer order based on VM total memory.
 * Returns alloc_pages order (0 → 4KB, 3 → 32KB, 6 → 256KB, 9 → 2MB).
 *
 * Currently hardcoded to 0 (4KB). Future阶梯 selection logic is
 * commented out below for reference.
 */
unsigned int hdbss_auto_select_order(struct kvm *kvm)
{
#if 0  /* Future阶梯 selection, to be enabled after testing */
    unsigned long npages = 0;
    struct kvm_memory_slot *memslot;

    kvm_for_each_memslot(memslot, kvm_memslots(kvm))
        npages += memslot->npages;

    if (npages <= 16384)           /* ≤64MB VM   */  return 0;   /* 4KB    */
    else if (npages <= 262144)     /* ≤1GB VM    */  return 3;   /* 32KB   */
    else if (npages <= 4194304)    /* ≤16GB VM   */  return 6;   /* 256KB  */
    else                           /* >16GB VM   */  return 9;   /* 2MB    */
#endif
    return 0;
}
```

> 插入位置: `arch/arm64/kvm/mmu.c`, 建议在 `kvm_flush_hdbss_buffer()` 附近。

#### 2.3.2 新增 `hdbss_alloc_vcpu_buffer()` — 单个 vCPU buffer 分配

```c
/*
 * Allocate HDBSS hardware buffer for a single vCPU.
 * Must only be called when enable_hdbss is true or about to be set.
 * Returns 0 on success, -ENOMEM on allocation failure.
 */
static int hdbss_alloc_vcpu_buffer(struct kvm_vcpu *vcpu, unsigned int order)
{
    struct page *pg = alloc_pages(GFP_KERNEL_ACCOUNT, order);
    if (!pg)
        return -ENOMEM;

    vcpu->arch.hdbss = (struct vcpu_hdbss_state) {
        .base_phys  = page_to_phys(pg),
        .size       = order,
        .next_index = 0,
    };
    return 0;
}
```

> 插入位置: `arch/arm64/kvm/mmu.c`, 紧接 `hdbss_auto_select_order()` 下方。

#### 2.3.3 `kvm_init_stage2_mmu()` — init 后设置 S2_DBM flag (L1013 之后)

```c
// Before:
    err = KVM_PGT_FN(kvm_pgtable_stage2_init)(pgt, mmu, &kvm_s2_mm_ops);
    if (err)
        goto out_free_pgtable;

// After:
    err = KVM_PGT_FN(kvm_pgtable_stage2_init)(pgt, mmu, &kvm_s2_mm_ops);
    if (err)
        goto out_free_pgtable;

    /* Signal that this VM supports hardware dirty bit management */
    if (system_supports_hdbss())
        pgt->flags |= KVM_PGTABLE_S2_DBM;
```

> **时序安全**: flag 在 init 后设置, 但所有页映射只发生在 KVM_RUN 之后(guest 缺页),
> 此时全部 vCPU 已创建完成, flag 已就位。

#### 2.3.4 `kvm_s2_fault_compute_prot()` — 删除 DBM 设置 (L1992-1993)

```c
// Before:
    if ((*prot & KVM_PGTABLE_PROT_W) && kvm->arch.enable_hdbss && memslot_is_logging(s2fd->memslot))
        *prot |= KVM_PGTABLE_PROT_DBM;

// After:
    // DBM is now handled automatically by the pgtable layer via
    // KVM_PGTABLE_S2_DBM flag in stage2_set_prot_attr() and relax_perms().
    // Device pages are filtered by KVM_PGTABLE_PROT_DEVICE in the same path.
    // No explicit DBM setting needed at fault compute time.
```

> 删除后 caller (map / relax_perms) 不再需要关心 DBM, pgtable 层根据 flag 自动处理。

---

### 2.4 `arch/arm64/kvm/arm.c` (4 处)

#### 2.4.1 新增 `hdbss_enable_internal()` — 全局启用

```c
static void hdbss_enable_internal(struct kvm *kvm)
{
    kvm->arch.mmu.vtcr |= VTCR_EL2_HD | VTCR_EL2_HDBSS | VTCR_EL2_HA;
    kvm->arch.enable_hdbss = true;
}
```

> 插入位置: `kvm_arm_vcpu_free_hdbss()` 下方。

#### 2.4.2 `kvm_arch_vcpu_create()` — 尾部加 auto-enable (L655 return 之前)

```c
    err = kvm_share_hyp(vcpu, vcpu + 1);
    if (err)
        kvm_vgic_vcpu_destroy(vcpu);

+   /* --- HDBSS auto-enable --- */
+   if (system_supports_hdbss()) {
+       unsigned int order = hdbss_auto_select_order(vcpu->kvm);
+       int ret;
+
+       ret = hdbss_alloc_vcpu_buffer(vcpu, order);
+       if (ret) {
+           kvm_unshare_hyp(vcpu, vcpu + 1);
+           kvm_vgic_vcpu_destroy(vcpu);
+           return ret;
+       }
+
+       if (!vcpu->kvm->arch.enable_hdbss)
+           hdbss_enable_internal(vcpu->kvm);
+   }

    return err;
}
```

> **首个 vCPU**: alloc buffer + enable global flag + set VTCR
> **后续 vCPU (含热插拔)**: 仅 alloc buffer (flag 已设, 跳过 enable)
> **分配失败**: 返回 -ENOMEM, vCPU 创建失败, 其他 vCPU 不受影响, HDBSS 继续运行

#### 2.4.3 `kvm_cap_arm_enable_hdbss()` — 改为 no-op

```c
// Before (L146-214): full enable/disable logic
// After:
static int kvm_cap_arm_enable_hdbss(struct kvm *kvm,
                                    struct kvm_enable_cap *cap)
{
    /*
     * HDBSS is now auto-enabled at vCPU creation time (kvm_arch_vcpu_create)
     * and stays on for the entire VM lifetime.  This ioctl is kept as a no-op
     * for backward compatibility.  QEMU's migration code may still call it.
     */
    return 0;
}
```

> `kvm_vm_ioctl_enable_cap` case `KVM_CAP_ARM_HW_DIRTY_STATE_TRACK` 调用路径不变,
> 底层函数改为纯 no-op。

#### 2.4.4 `kvm_arch_destroy_vm()` — 加 bulk cleanup (before kvm_destroy_vcpus)

```c
void kvm_arch_destroy_vm(struct kvm *kvm)
{
    bitmap_free(kvm->arch.pmu_filter);
    free_cpumask_var(kvm->arch.supported_cpus);

    kvm_vgic_destroy(kvm);

    if (is_protected_kvm_enabled())
        pkvm_destroy_hyp_vm(kvm);

    kvm_uninit_stage2_mmu(kvm);
    kvm_destroy_mpidr_data(kvm);

    kfree(kvm->arch.sysreg_masks);

+   /* Free HDBSS buffers before destroying vCPUs */
+   if (kvm->arch.enable_hdbss) {
+       struct kvm_vcpu *vcpu;
+       unsigned long i;
+
+       kvm_for_each_vcpu(i, vcpu, kvm)
+           kvm_arm_vcpu_free_hdbss(vcpu);
+   }

    kvm_destroy_vcpus(kvm);

    kvm_unshare_hyp(kvm, kvm + 1);

    kvm_arm_teardown_hypercalls(kvm);
}
```

> 在 `kvm_destroy_vcpus` 之前遍历释放所有 vCPU buffer。
> 单 vCPU 热拔已在 `reset.c:kvm_arm_vcpu_destroy()` 中处理 (L165-166), 不受影响。

---

### 2.5 `arch/arm64/include/asm/sysreg.h` (1 处)

#### 2.5.1 `HDBSSBR_EL2` macro — 使用已定义的 field mask

```c
// Before:
#define HDBSSBR_EL2(baddr, sz)  (((baddr) & GENMASK(55, 12 + sz)) | \
                                 FIELD_PREP(HDBSSBR_EL2_SZ_MASK, sz))

// After:
#define HDBSSBR_EL2(baddr, sz)  (((baddr) & HDBSSBR_EL2_BADDR) | \
                                 FIELD_PREP(HDBSSBR_EL2_SZ_MASK, sz))
```

> `HDBSSBR_EL2_BADDR` = `GENMASK(55, 12)`, 已在 sysreg-defs.h 中定义。
> `alloc_pages(order)` 返回值天然 `PAGE_SIZE * 2^order` 对齐, PAGE_SIZE 对齐足以满足 BADDR 掩码要求。

---

### 2.6 QEMU 侧 (3 处, 可选)

#### 2.6.1 `migration/ram.c` — 删除 enable 调用 (L3553-3557)

```c
// DELETE:
// #ifdef TARGET_AARCH64
//     if (kvm_enabled()) {
//         kvm_update_hdbss_cap(true, migrate_hdbss_buffer_size());
//     }
// #endif
```

#### 2.6.2 `migration/ram.c` — 删除 disable 调用 (L3140-3144)

```c
// DELETE:
// #ifdef TARGET_AARCH64
//     if (kvm_enabled()) {
//         kvm_update_hdbss_cap(false, 0);
//     }
// #endif
```

#### 2.6.3 `accel/kvm/kvm-all.c` — `kvm_update_hdbss_cap()` 改为空函数

```c
void kvm_update_hdbss_cap(bool enable, int hdbss_buffer_size)
{
    /*
     * No-op: HDBSS is auto-enabled at vCPU creation time by the kernel.
     * The ioctl KVM_CAP_ARM_HW_DIRTY_STATE_TRACK always returns success.
     */
}
```

> QEMU 侧改动可推迟或完全不改——内核 ioctl 返回 0, 向后兼容。

---

## 3. 时序安全验证

```
QEMU                         Kernel                            Guest
────                         ──────                            ─────
KVM_CREATE_VM                                                    
  └→ kvm_init_stage2_mmu()       // pgt->flags |= S2_DBM  ← 此时 system_supports_hdbss() 已知
KVM_SET_USER_MEMORY_REGION×N
KVM_CREATE_VCPU (vcpu 0)
  └→ kvm_arch_vcpu_create()
       ├─ hdbss_alloc_vcpu_buffer()  // vcpu0 buffer 已分配
       └─ hdbss_enable_internal()    // VTCR HD|HDBSS|HA, enable_hdbss=true
KVM_CREATE_VCPU (vcpu 1..N)
  └→ kvm_arch_vcpu_create()
       └─ hdbss_alloc_vcpu_buffer()  // 只分配, flag 已设
KVM_RUN
                                        └→ first guest page fault
                                             └→ stage2_set_prot_attr()
                                                  └→ flag S2_DBM + prot W → PTE |= DBM ✓
```

**关键断言**:
1. `pgt->flags |= S2_DBM` 在 init 时设置, 早于任何映射 ✅
2. 所有 vCPU buffer 在 `KVM_RUN` 前分配完成 ✅
3. 热插拔 vCPU 在 `kvm_arch_vcpu_create` 中分配 buffer, flag 已存在 ✅
4. 热拔 vCPU 在 `kvm_arm_vcpu_destroy` 中释放 buffer, 已有代码 ✅

---

## 4. 热插拔风险

### 4.1 场景: 热迁移期间热插拔 vCPU

- 当前方案: `kvm_arch_vcpu_create` 中 `hdbss_alloc_vcpu_buffer` → 分配失败返回 -ENOMEM
- vCPU 创建失败 → QEMU 收到错误 → 其他 vCPU 不受影响 → HDBSS 持续运行
- **绝不 disable HDBSS** 作为恢复路径 (disable = 全量扫表清 DBM, 代价不可接受)

### 4.2 热拔路径

```c
// reset.c:165-166 — 已正确处理
if (vcpu->kvm->arch.enable_hdbss)
    kvm_arm_vcpu_free_hdbss(vcpu);
```

无需额外改动。

---

## 5. 验证清单

- [ ] `kvm_arch_vcpu_create` 首个 vCPU: enable_hdbss 从 false→true, VTCR 正确设置
- [ ] `kvm_arch_vcpu_create` 后续 vCPU: 仅分配 buffer, 不重复 enable
- [ ] `kvm_arch_vcpu_create` hotplug vCPU: buffer 分配成功, HDBSS 继续运行
- [ ] `kvm_arch_destroy_vm`: 所有 vCPU buffer 在 destroy_vcpus 前释放
- [ ] 首次缺页 (W + non-Device): DBM 自动添加到 PTE
- [ ] 设备页缺页 (W + DEVICE): DBM 不添加到 PTE
- [ ] 迁移 WP (wrprotect): DBM 保留 (W→RO+DBM)
- [ ] WP 后的写 fault (relax_perms): DBM 保留 + W 恢复
- [ ] ioctl KVM_CAP_ARM_HW_DIRTY_STATE_TRACK: 返回 0, VM 不受影响
- [ ] buffer order 固定为 0, `HDBSSBR_EL2` 宏使用 `HDBSSBR_EL2_BADDR`

---

## 6. 涉及文件汇总

| # | 文件 | 改动类型 | 行 |
|---|------|---------|-----|
| 1 | `arch/arm64/include/asm/kvm_pgtable.h` | enum 新增 flag | L255-258 |
| 2 | `arch/arm64/kvm/hyp/pgtable.c` | `stage2_set_prot_attr` 自动 DBM | L737-738 |
| 3 | `arch/arm64/kvm/hyp/pgtable.c` | `relax_perms` 自动 DBM | L1376-1377 |
| 4 | `arch/arm64/kvm/hyp/pgtable.c` | `relax_perms` 降级清 DBM | L1377+ |
| 5 | `arch/arm64/kvm/mmu.c` | 新增 `hdbss_auto_select_order()` | new |
| 6 | `arch/arm64/kvm/mmu.c` | 新增 `hdbss_alloc_vcpu_buffer()` | new |
| 7 | `arch/arm64/kvm/mmu.c` | init 后设 S2_DBM flag | L1013+ |
| 8 | `arch/arm64/kvm/mmu.c` | 删除 fault_prot 中 DBM 设置 | L1992-1993 |
| 9 | `arch/arm64/kvm/arm.c` | 新增 `hdbss_enable_internal()` | new |
| 10 | `arch/arm64/kvm/arm.c` | `kvm_arch_vcpu_create` 加 HDBSS | L655 |
| 11 | `arch/arm64/kvm/arm.c` | `kvm_cap_arm_enable_hdbss` → no-op | L146-214 |
| 12 | `arch/arm64/kvm/arm.c` | `kvm_arch_destroy_vm` 加 bulk free | L395-414 |
| 13 | `arch/arm64/include/asm/sysreg.h` | `HDBSSBR_EL2` macro 修复 | L1048-1049 |
| 14 | `migration/ram.c` (QEMU) | 删除 enable 调用 | L3553-3557 |
| 15 | `migration/ram.c` (QEMU) | 删除 disable 调用 | L3140-3144 |
| 16 | `accel/kvm/kvm-all.c` (QEMU) | `kvm_update_hdbss_cap` → 空函数 | L3383-3406 |
