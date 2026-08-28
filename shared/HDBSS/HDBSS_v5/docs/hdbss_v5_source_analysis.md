# HDBSS v5 源码分析

本文档对 HDBSS v5 的最终实现进行逐函数源码分析，不含 v4 对比。所有代码引用基于最终提交的 v5 patch 系列。

---

## 目录

1. [数据结构](#1-数据结构)
2. [Buffer 分配与释放](#2-buffer-分配与释放)
3. [HDBSS 寄存器加载/保存](#3-hdbss-寄存器加载保存)
4. [HDBSS Enable/Disable](#4-hdbss-enabledisable)
5. [Flush 实现](#5-flush-实现)
6. [Fault 处理](#6-fault-处理)
7. [DBM 三态模型](#7-dbm-三态模型)
8. [Dirty Ring 适配](#8-dirty-ring-适配)
9. [Ioctl 接口](#9-ioctl-接口)
10. [sync_dirty_log 与 VM destroy](#10-sync_dirty_log-与-vm-destroy)

---

## 1. 数据结构

### 1.1 vcpu_hdbss_state

**文件**：`arch/arm64/include/asm/kvm_host.h`

```c
struct vcpu_hdbss_state {
    struct page *hdbss_pg;     /* HDBSS buffer page */
    u64 hdbssbr_el2;           /* load directly */
    u64 hdbssprod_el2;         /* save directly */
    unsigned int buddy_order;  /* allocation order for __free_pages */
};
```

| 字段 | 用途 | 何时写 | 何时读 |
|------|------|--------|--------|
| `hdbss_pg` | buffer 的 struct page 指针，NULL 表示未分配 | alloc 时设，free 时清 NULL | free 时检查是否已分配；flush 时 page_address() |
| `hdbssbr_el2` | HDBSSBR_EL2 寄存器值（base addr + SZ 编码） | alloc 时计算并存储 | `__load_hdbss()` 写硬件 |
| `hdbssprod_el2` | HDBSSPROD_EL2 寄存器值（producer index） | `kvm_vcpu_put_vhe()` 保存硬件值；flush 后重置为 0 | `__load_hdbss()` 写硬件恢复 |
| `buddy_order` | `alloc_pages()` 时的 buddy order | alloc 时 `get_order(size)` | `kvm_arm_vcpu_free_hdbss()` 传给 `__free_pages()` |

设计要点：
- 用 `struct page *` 替代 `base_phys`（v4 的物理地址），NULL 检查可靠，消除 PA=0 的泄漏 bug
- `buddy_order` 独立存储，修复 v4 中 SZ 编码被错误用作 free order 的 16KB/64KB 页 bug

### 1.2 kvm_arch 中的 HDBSS 字段

**文件**：`arch/arm64/include/asm/kvm_host.h`

```c
struct kvm_arch {
    ...
    struct kvm_s2_mmu mmu;    /* 包含 vtcr 字段 */
    u32 hdbss_buffer_size;    /* per-VM buffer size in bytes (0 = not configured, use default) */
    ...
};
```

`hdbss_buffer_size` 的来源：
- 用户通过 `KVM_CAP_ARM_HDBSS_BUFFER_SIZE` ioctl 配置（dirty-bitmap 模式）
- `kvm_arch_dirty_ring_size_updated()` 自动设为 `KVM_ARM_HDBSS_DEFAULT_SIZE`（dirty-ring 模式）
- 未配置时为 0，alloc 时 fallback 到 `KVM_ARM_HDBSS_DEFAULT_SIZE`（PAGE_SIZE）

### 1.3 HDBSS 检查函数

**文件**：`arch/arm64/include/asm/kvm_dirty_bit.h`

```c
/*
 * VM-level HDBSS check — L1 only, does not filter nested (L2).
 *
 * Tests kvm->arch.mmu.vtcr, which always reflects the L1 VM's HDBSS
 * state regardless of whether a vCPU is currently running L2.
 *
 * Use in VM-level control paths (enable/disable/destroy/sync_dirty_log)
 * that never touch HDBSS registers directly.
 */
static inline bool kvm_hdbss_enabled(struct kvm *kvm)
{
    return kvm->arch.mmu.vtcr & VTCR_EL2_HDBSS;
}

/*
 * vCPU-level HDBSS check — filters both L1 and L2.
 *
 * Tests hw_mmu->vtcr, the S2 MMU actually in use for this vCPU's
 * current execution context.  When running L1, hw_mmu points to
 * kvm->arch.mmu (HDBSS bits present).  When running L2, hw_mmu points
 * to a shadow S2 MMU (HDBSS bits absent).
 *
 * Use in all per-vCPU paths that directly touch HDBSS registers or
 * buffer (load, put, flush, fault handler).
 */
static inline bool vcpu_hdbss_enabled(struct kvm_vcpu *vcpu)
{
    return vcpu->arch.hw_mmu &&
        (vcpu->arch.hw_mmu->vtcr & VTCR_EL2_HDBSS);
}
```

两层检查的原因：嵌套虚拟化时，`hw_mmu` 指向 shadow S2 MMU（无 HDBSS 位），即使 L1 VM 的 VTCR 有 HDBSS 位。VM 级检查用于控制面（enable/disable），vCPU 级检查用于数据面（flush/load/put）。

### 1.4 常量定义

**文件**：`arch/arm64/include/asm/kvm_dirty_bit.h`

```c
#define HDBSS_ENTRY_VALID       BIT(0)
#define HDBSS_ENTRY_TTWL_SHIFT  (1)
#define HDBSS_ENTRY_TTWL_MASK   (GENMASK(3, 1))
#define HDBSS_ENTRY_TTWL(x) \
    (((x) << HDBSS_ENTRY_TTWL_SHIFT) & HDBSS_ENTRY_TTWL_MASK)
#define HDBSS_ENTRY_TTWL_RESV   HDBSS_ENTRY_TTWL(-4)
#define HDBSS_ENTRY_IPA         GENMASK_ULL(55, 12)

#define KVM_ARM_HDBSS_DEFAULT_SIZE  PAGE_SIZE
#define KVM_ARM_HDBSS_MAX_SIZE      SZ_2M
```

IPA 字段 [55:12] 共 44 位：HDBSS 记录的是页基地址（page-aligned IPA），低 12 位（页内偏移）为 0 不存储。ARM64 最大 IPA = 48 位，实际需要 [47:12] = 36 位，44 位远超需求。

---

## 2. Buffer 分配与释放

### 2.1 kvm_arm_vcpu_alloc_hdbss()

**文件**：`arch/arm64/kvm/dirty_bit.c:16`

调用点：`kvm_arch_vcpu_create()` (`arm.c:673`)，在 `kvm_share_hyp()` 成功后调用。

```c
int kvm_arm_vcpu_alloc_hdbss(struct kvm_vcpu *vcpu)
{
    struct page *hdbss_pg;
    u32 size;
    unsigned int buddy_order;
    u32 sz_encoded;

    // 已分配或硬件不支持 → 跳过
    if (vcpu->arch.hdbss.hdbss_pg || !system_supports_hdbss())
        return 0;

    // 读 VM 级配置，未配置用默认 PAGE_SIZE
    size = vcpu->kvm->arch.hdbss_buffer_size ?: KVM_ARM_HDBSS_DEFAULT_SIZE;

    // 分离计算 buddy order 和 HDBSSBR_EL2.SZ 编码
    // buddy_order: 给 alloc_pages 用，按 PAGE_SIZE 缩放
    // sz_encoded:  给 HDBSSBR_EL2 用，硬件编码（ilog2(bytes) - 12）
    buddy_order = get_order(size);
    sz_encoded = ilog2(size) - 12;

    hdbss_pg = alloc_pages(GFP_KERNEL_ACCOUNT, buddy_order);
    if (!hdbss_pg)
        return -ENOMEM;

    vcpu->arch.hdbss = (struct vcpu_hdbss_state) {
        .hdbss_pg = hdbss_pg,
        .hdbssbr_el2 = HDBSSBR_EL2(page_to_phys(hdbss_pg), sz_encoded),
        .hdbssprod_el2 = 0,
        .buddy_order = buddy_order,
    };

    return 0;
}
```

设计要点：
- **PML-style**：vCPU create 时分配，整个 vCPU 生命周期 buffer 存在，不管 dirty logging 是否开启
- **buddy_order vs sz_encoded 分离**：v4 把 SZ 编码当 buddy order 用，在 16KB/64KB 页上越界释放。v5 独立计算和存储
- **整体赋值**：`vcpu->arch.hdbss = (struct vcpu_hdbss_state){...}` 整体覆盖，不是逐字段 OR

### 2.2 kvm_arm_vcpu_free_hdbss()

**文件**：`arch/arm64/kvm/dirty_bit.c:47`

调用点：`kvm_arm_vcpu_destroy()` (`reset.c:166`)，在 `kvm_unshare_hyp()` 之后调用。

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

设计要点：
- **无条件调用**：`kvm_arm_vcpu_destroy()` 不检查 `enable_hdbss`（v4 检查，有 TOCTOU 泄漏 bug）
- **用存储的 buddy_order**：不从 `hdbssbr_el2` 反推 SZ 编码，避免 16KB/64KB 页的转换错误
- **NULL 检查**：`hdbss_pg == NULL` 表示未分配或已释放，直接返回

### 2.3 错误路径处理

`kvm_arch_vcpu_create()` (`arm.c:626`) 中的错误路径：

```c
err = kvm_share_hyp(vcpu, vcpu + 1);
if (err) {
    kvm_vgic_vcpu_destroy(vcpu);
    return err;                    // ← kvm_share_hyp 失败直接返回
}

err = kvm_arm_vcpu_alloc_hdbss(vcpu);
if (err) {
    kvm_unshare_hyp(vcpu, vcpu + 1);  // ← 回滚 kvm_share_hyp
    kvm_vgic_vcpu_destroy(vcpu);
    return err;
}
```

v4 的问题：`kvm_share_hyp` 失败时 `err` 被 HDBSS alloc 成功覆盖为 0；HDBSS alloc 失败时没调 `kvm_unshare_hyp`。v5 修复了两者。

---

## 3. HDBSS 寄存器加载/保存

### 3.1 __load_hdbss()

**文件**：`arch/arm64/kvm/hyp/vhe/switch.c:217`

调用点：`kvm_vcpu_load_vhe()` (switch.c:235)，在 `__load_stage2()` 之后调用。

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

- 两个 sysreg 写后统一一个 ISB，符合 arm64 kernel 惯例（`__load_stage2()` 同样批量写 VTCR+VTTBR 后一个 ISB）
- `vcpu_hdbss_enabled()` 检查 `hw_mmu->vtcr`，嵌套虚拟化跑 L2 时返回 false，跳过

### 3.2 kvm_vcpu_put_vhe() 中的保存

**文件**：`arch/arm64/kvm/hyp/vhe/switch.c:238`

```c
void kvm_vcpu_put_vhe(struct kvm_vcpu *vcpu)
{
    if (vcpu_hdbss_enabled(vcpu))
        vcpu->arch.hdbss.hdbssprod_el2 = read_sysreg_s(SYS_HDBSSPROD_EL2);

    __vcpu_put_deactivate_traps(vcpu);   // ← HCR_EL2.VM=0，stage-2 关闭
    __vcpu_put_switch_sysregs(vcpu);

    host_data_ptr(host_ctxt)->__hyp_running_vcpu = NULL;
}
```

- 只保存 `HDBSSPROD_EL2`（producer index），不保存 `HDBSSBR_EL2`（base addr 不变）
- `__vcpu_put_deactivate_traps()` 写 `HCR_EL2 = HCR_HOST_VHE_FLAGS`（VM=0），关闭 stage-2 → HDBSS 不能脱离 stage-2 工作
- 不在 put 时 flush（v5 已移出 vcpu_put，flush 在 VM exit path）

### 3.3 加载/保存的完整时序

```
vcpu_load (KVM_RUN 开始 / CPU 迁移):
  kvm_vcpu_load_vhe():
    __vcpu_load_switch_sysregs()
    __vcpu_load_activate_traps()
    __load_stage2(hw_mmu)     → 写 VTCR_EL2 + VTTBR_EL2
    __load_hdbss(vcpu)        → 写 HDBSSBR_EL2 + HDBSSPROD_EL2

  ... guest 运行 (可能多次 exit/re-enter，不重新加载以上寄存器) ...

  每次 VM exit:
    flush HDBSS buffer (见第 5 节)
    HDBSSPROD_EL2 重置为 0

vcpu_put (KVM_RUN 结束 / CPU 迁移):
  kvm_vcpu_put_vhe():
    保存 HDBSSPROD_EL2 → vcpu->arch.hdbss.hdbssprod_el2
    __vcpu_put_deactivate_traps() → HCR_EL2.VM=0
```

---

## 4. HDBSS Enable/Disable

### 4.1 kvm_arm_enable_hdbss_global()

**文件**：`arch/arm64/kvm/dirty_bit.c:150`

调用点：`kvm_arm_hdbss_on_dirty_logging_change()` (dirty_bit.c:200)，在 `kvm_arch_commit_memory_slot()` 中 dirty logging 开启时调用。

```c
static void kvm_arm_enable_hdbss_global(struct kvm *kvm)
{
    struct kvm_vcpu *vcpu;
    unsigned long i;

    if (!system_supports_hdbss())
        return;

    if (kvm_hdbss_enabled(kvm))  // 检查 sw VTCR，已开则跳过
        return;

    // 设软件 VTCR 的 HDBSS 位
    kvm->arch.mmu.vtcr |= VTCR_EL2_HD | VTCR_EL2_HDBSS | VTCR_EL2_HA;

    // kick 所有 vCPU 退出 guest
    // VTCR_EL2 在下次 vcpu_load (KVM_RUN 开始) 时通过 __load_stage2() 加载到硬件
    kvm_for_each_vcpu(i, vcpu, kvm)
        kvm_vcpu_kick(vcpu);
}
```

### 4.2 kvm_arm_disable_hdbss_global()

**文件**：`arch/arm64/kvm/dirty_bit.c:173`

```c
void kvm_arm_disable_hdbss_global(struct kvm *kvm)
{
    struct kvm_vcpu *vcpu;
    unsigned long i;

    if (!kvm_hdbss_enabled(kvm))  // 已关则跳过
        return;

    // 清软件 VTCR 的 HDBSS 位
    kvm->arch.mmu.vtcr &= ~(VTCR_EL2_HD | VTCR_EL2_HDBSS | VTCR_EL2_HA);

    // kick 所有 vCPU
    // buffer 不在这里释放（PML-style，只在 vCPU destroy 时释放）
    kvm_for_each_vcpu(i, vcpu, kvm)
        kvm_vcpu_kick(vcpu);
}
```

### 4.3 VTCR 同步方式：kick

arm64 的 VTCR_EL2 只在 `kvm_vcpu_load_vhe()` → `__load_stage2()` 中加载，run loop 内不 reload。用 kick（而非 request-handler）的原因：

1. arm64 架构无先例——VTCR 在 VM 创建时设好，之后不变；arm64 中没有运行时修改 VTCR 后在 run loop 中 reload 的机制
2. stale 窗口可控——enable 方向 WC 写走 software fault（正确），disable 方向标准迁移流程安全（vCPU 先停再 disable）
3. `vcpu_put` 时 `HCR_EL2.VM=0` 关闭 stage-2，HDBSS 不能脱离 stage-2 单独工作

### 4.4 kvm_arm_hdbss_on_dirty_logging_change()

**文件**：`arch/arm64/kvm/dirty_bit.c:195`

```c
void kvm_arm_hdbss_on_dirty_logging_change(struct kvm *kvm, int nr_memslots_logging)
{
    if (nr_memslots_logging > 0 && !kvm_hdbss_enabled(kvm))
        kvm_arm_enable_hdbss_global(kvm);
    else if (nr_memslots_logging == 0 && kvm_hdbss_enabled(kvm))
        kvm_arm_disable_hdbss_global(kvm);
}
```

调用点：`kvm_arch_commit_memory_region()` (mmu.c:2584)，传入 `atomic_read(&kvm->nr_memslots_dirty_logging)`。

---

## 5. Flush 实现

### 5.1 flush 的唯一调用点

**文件**：`arch/arm64/kvm/arm.c:1506`（`kvm_arch_vcpu_ioctl_run()` while 循环中）

```c
trace_kvm_exit(ret, kvm_vcpu_trap_get_class(vcpu), *vcpu_pc(vcpu));

/*
 * Flush HDBSS buffer on every VM exit, before handling the
 * exit reason.  This mirrors x86 PML's single-flush-point
 * design.  Flushing here ensures that entries pushed to the
 * dirty ring are accounted for when check_vcpu_requests() runs
 * dirty_ring_check_request() on the next loop iteration,
 * preventing ring overflow.
 */
if (vcpu_hdbss_enabled(vcpu))
    kvm_flush_hdbss_buffer(vcpu);

/* Exit types that need handling before we can be preempted */
handle_exit_early(vcpu, ret);
```

- **唯一 flush 点**：每次 VM exit 后、`handle_exit_early()` 之前
- 不在 `vcpu_put()` 中 flush（已移出）
- 不在 `check_vcpu_requests()` 中 flush（`KVM_REQ_FLUSH_HDBSS` 已删除）

### 5.2 kvm_flush_hdbss_buffer()

**文件**：`arch/arm64/kvm/dirty_bit.c:58`

```c
void kvm_flush_hdbss_buffer(struct kvm_vcpu *vcpu)
{
    int idx, curr_idx;
    u32 entries;
    u64 *hdbss_buf;
    struct kvm *kvm = vcpu->kvm;
    int srcu_idx;

    // vCPU 级检查（嵌套虚拟化过滤）
    if (!vcpu_hdbss_enabled(vcpu))
        return;

    // 读硬件 producer index（当前写入的 entry 数）
    curr_idx = HDBSSPROD_IDX(read_sysreg_s(SYS_HDBSSPROD_EL2));

    // buffer 为空或未分配 → 跳过
    if (curr_idx == 0 || !vcpu->arch.hdbss.hdbss_pg)
        return;

    hdbss_buf = page_address(vcpu->arch.hdbss.hdbss_pg);
    if (!hdbss_buf)
        return;

    // 计算 buffer entries 数量（用于防御性上限）
    entries = (vcpu->kvm->arch.hdbss_buffer_size ?: KVM_ARM_HDBSS_DEFAULT_SIZE) /
              sizeof(u64);

    // SRCU 保护 memslot 查找
    srcu_idx = srcu_read_lock(&kvm->srcu);
    for (idx = 0; idx < min_t(u32, curr_idx, entries); idx++) {
        u64 gpa;

        gpa = hdbss_buf[idx];
        if (!(gpa & HDBSS_ENTRY_VALID))   // 跳过无效 entry
            continue;

        gpa &= HDBSS_ENTRY_IPA;           // 取 [55:12] 页基地址
        kvm_vcpu_mark_page_dirty(vcpu, gpa >> PAGE_SHIFT);
        // → mark_page_dirty_in_slot()
        //   → set_bit_le(bitmap) 或 kvm_dirty_ring_push(ring)
    }
    srcu_read_unlock(&kvm->srcu, srcu_idx);

    // 重置硬件 producer index
    write_sysreg_s(0, SYS_HDBSSPROD_EL2);
    vcpu->arch.hdbss.hdbssprod_el2 = 0;
    isb();
}
```

设计要点：
- **SRCU 而非 mmu_lock**：`mark_page_dirty_in_slot()` 只做原子 `set_bit_le()` 或 per-vCPU `kvm_dirty_ring_push()`，不需要 mmu_lock；memslot 查找需要 SRCU
- **min(curr_idx, entries) 防御**：curr_idx 是硬件值，理论上不超过 entries，但防御性编程防硬件异常
- **flush 后重置**：producer index 归零，硬件从 buffer 开头继续写入

### 5.3 flush 后的 dirty ring check

```
VM exit → flush HDBSS (push entries to ring/bitmap)
→ handle_exit_early → handle_exit
→ 回到 while 循环顶部
→ check_vcpu_requests()
  → kvm_dirty_ring_check_request(vcpu)
    → if soft_full: 退出到 userspace drain ring
```

flush 在 `check_vcpu_requests()` 之前执行，确保 dirty ring 的 soft_full 检查能看到 flush 推入的 entries。

---

## 6. Fault 处理

### 6.1 fault 入口

**文件**：`arch/arm64/kvm/mmu.c:2276`（`user_mem_abort()` 中）

```c
if (esr_iss2_is_hdbssf(esr))
    return kvm_handle_hdbss_fault(vcpu);
```

`esr_iss2_is_hdbssf()` 检查 ESR_EL2.ISS2 bit[11]（HDBSSF）。当 HDBSS buffer 满或出错时，guest 写 WC 页产生带 HDBSSF 标志的 Permission fault。

### 6.2 kvm_handle_hdbss_fault()

**文件**：`arch/arm64/kvm/dirty_bit.c:101`

```c
int kvm_handle_hdbss_fault(struct kvm_vcpu *vcpu)
{
    u64 prod;
    u64 fsc;

    if (WARN_ON_ONCE(!system_supports_hdbss()))
        return -EFAULT;

    if (WARN_ON_ONCE(!vcpu_hdbss_enabled(vcpu)))
        return -EFAULT;

    prod = read_sysreg_s(SYS_HDBSSPROD_EL2);
    fsc = FIELD_GET(HDBSSPROD_EL2_FSC_MASK, prod);

    switch (fsc) {
    case HDBSSPROD_EL2_FSC_OK:
        // Buffer full — 不设 request，exit path 会无条件 flush
        return 1;
    case HDBSSPROD_EL2_FSC_ExternalAbort:
    case HDBSSPROD_EL2_FSC_GPF:
        return -EFAULT;
    default:
        WARN_ONCE(1, "Unexpected HDBSS fault type...");
        return -EFAULT;
    }
}
```

FSC_OK 返回 1 → exit path 的 `kvm_flush_hdbss_buffer()` 会 flush → producer index 归零 → 硬件继续工作。不需要设 `KVM_REQ_FLUSH_HDBSS`（已删除）。

---

## 7. DBM 三态模型

### 7.1 DBM 语义随 HD 位转变

HD=0 时：DBM 被忽略，S2AP[1] 是写权限位。
HD=1 时：DBM 变为写意图位，S2AP[1] 变为脏状态位。

### 7.2 stage2_set_prot_attr() — 无条件设 DBM

**文件**：`arch/arm64/kvm/hyp/pgtable.c:734`

```c
if (prot & KVM_PGTABLE_PROT_W) {
    attr |= KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W;
    attr |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;   // 无条件，不需要 flag
}
```

`*ptep = attr` 整体覆盖，有 W 必有 DBM。

### 7.3 stage2_attr_walker() — wrprotect block/page 区分

**文件**：`arch/arm64/kvm/hyp/pgtable.c:1249-1260`

```c
pte &= ~data->attr_clr;      // wrprotect: clears S2AP_W
pte |= data->attr_set;

// block entry: 额外清 DBM → RO
if (ctx->level < KVM_PGTABLE_LAST_LEVEL)
    pte &= ~KVM_PTE_LEAF_ATTR_HI_S2_DBM;
// level-3 page: 保留 DBM → WC
```

### 7.4 kvm_pgtable_stage2_relax_perms() — 无条件设 DBM

**文件**：`arch/arm64/kvm/hyp/pgtable.c:1395`

```c
if (prot & KVM_PGTABLE_PROT_W) {
    set |= KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W;
    set |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;   // 无条件
}
```

OR 操作，不管旧 DBM 状态如何，结果 DBM 必为 1。

### 7.5 DBM 加/清时机总结

| 步骤 | 操作 | DBM 变化 | 代码位置 |
|------|------|---------|---------|
| 初始映射 | `set_prot_attr(W)` | 设 DBM | `pgtable.c:749` |
| wrprotect (block) | `attr_walker` 清 W | 清 DBM | `pgtable.c:1260` |
| wrprotect (page) | `attr_walker` 清 W | 保留 DBM → WC | 不进 if |
| eager split | `set_prot_attr(R)` | 不设（继承 RO） | `pgtable.c:734` |
| 首次写 fault (eager) | `relax_perms(W)` | 设 DBM | `pgtable.c:1397` |
| lazy split fault | `map(W)` → `set_prot_attr(W)` | 设 DBM | `pgtable.c:749` |
| 下一轮 wp (page) | `attr_walker` 清 W | 保留 DBM → WC | 不进 if |
| HDBSS 硬件 C→D | 硬件设 W=1 | DBM 保持 1 | ARM Spec |

---

## 8. Dirty Ring 适配

### 8.1 kvm_cpu_dirty_log_size()

**文件**：`arch/arm64/kvm/mmu.c:2805`

```c
int kvm_cpu_dirty_log_size(struct kvm *kvm)
{
    if (!system_supports_hdbss())
        return 0;

    return (kvm->arch.hdbss_buffer_size ?: KVM_ARM_HDBSS_DEFAULT_SIZE) /
           sizeof(u64);
}
```

返回 HDBSS buffer 的 entry 数量，给 dirty ring 的 reservation 机制用：
```
rsvd = KVM_DIRTY_RING_RSVD_ENTRIES (64) + kvm_cpu_dirty_log_size()
soft_limit = ring_size - rsvd
```

### 8.2 kvm_arch_dirty_ring_size_updated()

**文件**：`arch/arm64/kvm/arm.c:266`

```c
void kvm_arch_dirty_ring_size_updated(struct kvm *kvm)
{
    if (!system_supports_hdbss())
        return;

    // 保留用户 ioctl 配置的值
    if (kvm->arch.hdbss_buffer_size)
        return;

    // dirty-ring 模式固定用 PAGE_SIZE（最小值）
    // buffer 越大 → rsvd 越大 → soft_limit 越小 → drain 越频繁 → 性能越差
    kvm->arch.hdbss_buffer_size = KVM_ARM_HDBSS_DEFAULT_SIZE;
}
```

调用点：`kvm_vm_ioctl_enable_dirty_log_ring()` (kvm_main.c:4972)，在 dirty ring size 设置后调用。

固定 PAGE_SIZE 的性能分析：

| ring_entries | hdbss_entries | rsvd | soft_limit | drain_interval |
|---|---|---|---|---|
| 65536 | 512 (PAGE_SIZE) | 576 | 64960 | 65024 |
| 65536 | 32768 (动态算最大值) | 32832 | 32704 | 32768 |

buffer 越大 → rsvd 越大 → soft_limit 越小 → drain 越频繁。PAGE_SIZE 给出最大 drain interval。

---

## 9. Ioctl 接口

### 9.1 KVM_CAP_ARM_HDBSS_BUFFER_SIZE

**文件**：`arch/arm64/kvm/arm.c:207`（`kvm_vm_ioctl_enable_cap()` 中）

```c
case KVM_CAP_ARM_HDBSS_BUFFER_SIZE: {
    u64 size = cap->args[0];

    // 单位：bytes（与 KVM_CAP_DIRTY_LOG_RING 一致）
    // QEMU 属性 hdbss-buffer-size 用 entries，QEMU 转 bytes 传 ioctl

    if (!system_supports_hdbss())
        break;
    if (kvm->dirty_ring_size)           // 与 dirty ring 互斥
        break;
    if (size < KVM_ARM_HDBSS_DEFAULT_SIZE ||
        size > KVM_ARM_HDBSS_MAX_SIZE)  // 范围 [PAGE_SIZE, SZ_2M]
        break;
    if (!is_power_of_2(size))            // 必须是 2 的幂
        break;

    mutex_lock(&kvm->lock);
    if (kvm->created_vcpus) {
        r = -EINVAL;                     // 必须在 vCPU 创建前设置
    } else if (kvm->arch.hdbss_buffer_size) {
        r = -EBUSY;                      // 只允许设置一次
    } else {
        kvm->arch.hdbss_buffer_size = size;
        r = 0;
    }
    mutex_unlock(&kvm->lock);
    break;
}
```

### 9.2 KVM_CHECK_EXTENSION

**文件**：`arch/arm64/kvm/arm.c:525`

```c
case KVM_CAP_ARM_HDBSS_BUFFER_SIZE:
    if (!system_supports_hdbss())
        r = 0;
    else if (kvm)
        r = kvm->arch.hdbss_buffer_size ?: KVM_ARM_HDBSS_DEFAULT_SIZE;
    else
        r = KVM_ARM_HDBSS_MAX_SIZE;    // 全局查询返回 max
    break;
```

---

## 10. sync_dirty_log 与 VM destroy

### 10.1 kvm_arch_sync_dirty_log()

**文件**：`arch/arm64/kvm/arm.c:2090`

```c
void kvm_arch_sync_dirty_log(struct kvm *kvm, struct kvm_memory_slot *memslot)
{
    struct kvm_vcpu *vcpu;
    unsigned long i;

    if (!kvm_hdbss_enabled(kvm))
        return;

    // kick 所有 vCPU 退出 guest
    // flush 在 VM exit path 中无条件执行
    // dirty-log 协议（GET/CLEAR）容忍并发 bitmap 写
    kvm_for_each_vcpu(i, vcpu, kvm)
        kvm_vcpu_kick(vcpu);
}
```

与 x86 的 `kvm_arch_sync_dirty_log()` 完全一致。kick 是异步的，flush 可能在 bitmap 快照后完成，但 GET/CLEAR 协议自愈：晚到的 bit 不在 CLEAR 掩码里，存活到下一轮。

### 10.2 kvm_arch_destroy_vm() 中的防御性 disable

**文件**：`arch/arm64/kvm/arm.c:411`

```c
void kvm_arch_destroy_vm(struct kvm *kvm)
{
    ...
    // 防御性：用户可能没关 dirty logging 就直接关 VM
    if (kvm_hdbss_enabled(kvm))
        kvm_arm_disable_hdbss_global(kvm);

    kvm_uninit_stage2_mmu(kvm);
    ...
    kvm_destroy_vcpus(kvm);   // ← free buffer 在这里
    ...
}
```

### 10.3 UAF 安全保证

```
vCPU fd 关闭 → kvm_vcpu_release() → kvm_put_kvm()
→ 所有 vCPU fd 关闭后 → kvm_put_kvm() refcount=0 → kvm_destroy_vm()
  → kvm_arch_destroy_vm():
    → disable HDBSS (kick，但 vCPU 已停，no-op)
    → kvm_destroy_vcpus():
      → kvm_vcpu_destroy():
        → kvm_arch_vcpu_destroy():
          → kvm_arm_vcpu_destroy():
            → kvm_arm_vcpu_free_hdbss(): __free_pages()  ← 安全
```

安全保证：
1. vCPU fd 引用计数：`kvm_destroy_vm()` 只在所有 vCPU fd 关闭后调用
2. `vcpu_put()` → `__deactivate_traps()` → `HCR_EL2.VM=0`：stage-2 关闭，HDBSS 不能单独工作
3. buffer 只在 vCPU destroy 时释放（PML-style），不在 disable 时释放
