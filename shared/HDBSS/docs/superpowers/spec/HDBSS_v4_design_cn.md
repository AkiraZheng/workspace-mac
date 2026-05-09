# HDBSS v4 实现设计方案

## 1. 概述

HDBSS (Hardware Dirty state tracking Structure) 是 ARM 架构特性 (FEAT_HDBSS)，提供硬件辅助的脏页追踪用于live migration。本文描述v4实现计划。

## 2. 需求来源

来自 v4.md 和社区反馈：

| 序号 | 需求 | 状态 |
|---|--------------|--------|
| 1 | 取消ioctl接口，migration时自动enable | TODO |
| 2 | 修复HDBSSBR_EL2定义（使用BADDR_MASK） | TODO |
| 3 | struct中size改名为order | TODO |
| 4 | 清理HDBSS flush触发位置 | TODO |
| 5 | 测试dirty ring脏页统计 | TODO |
| 6 | 合入HACDBS patch（独立步骤） | TODO |
| 7 | 将HDBSS代码归档到dirty_bit.c | TODO |
| 8 | migration后W->RO时去除DBM标志 | TODO |

## 3. 架构设计

### 3.1 代码组织

参考Leo的建议，所有HDBSS相关代码将集中到：
- `arch/arm64/include/asm/kvm_dirty_bit.h`（头文件）
- `arch/arm64/kvm/dirty_bit.c`（实现）

### 3.2 文件变更

| 文件 | 变更类型 | 说明 |
|------|-------------|---------|
| `arch/arm64/include/asm/kvm_dirty_bit.h` | 新建 | HDBSS公共接口 |
| `arch/arm64/include/asm/kvm_host.h` | 修改 | vcpu_hdbss_state结构更新 |
| `arch/arm64/kvm/dirty_bit.c` | 新建 | HDBSS实现 |
| `arch/arm64/kvm/arm.c` | 修改 | 删除HDBSS ioctl实现，添加头文件引用 |
| `arch/arm64/kvm/mmu.c` | 修改 | HDBSS可用时启用eager page split |
| `arch/arm64/kvm/hyp/pgtable.c` | 修改 | DBM属性处理 |
| `arch/arm64/kvm/virtcca_cvm.c` | 修改 | migration自动enable/disable |
| `arch/arm64/kvm/Makefile` | 修改 | 添加dirty_bit.o |
| `arch/arm64/kvm/vhe/switch.c` | 修改 | __load_hdbss()更新 |
| `arch/arm64/kvm/reset.c` | 修改 | vcpu destroy时释放hdbss |

### 3.3 vcpu_hdbss_state 结构

根据Leo的建议，存储完整的寄存器值以避免load/save时的masking操作：

```c
struct vcpu_hdbss_state {
    phys_addr_t base_phys;   // 用于释放内存
    u64 hdbssbr_el2;          // load时直接用
    u64 hdbssprod_el2;       // save时直接用
};
```

**优点：**
- load/save直接写回寄存器，无需计算
- enable时计算一次，disable时解析一次，中间无需操作

## 4. Flush触发机制设计

根据Leo和Marc的讨论，确定以下flush触发点：

| 位置 | 函数 | 说明 |
|------|------|------|
| Run loop退出 | `kvm_arch_vcpu_ioctl_run()` | vCPU退出run循环时flush |
| 调度出 | `kvm_sched_out()` | vCPU被调度出时flush |
| Request触发 | `check_vcpu_requests()` | sync_dirty_log时通过KVM_REQ_FLUSH_HDBSS |
| Fault处理 | `kvm_handle_hdbss_fault()` | **设置单vcpu request**，让下次exit时flush |

**重要说明**：
- `vcpu_put` 不应该包含flush操作，因为它是纯save/restore路径
- Fault处理时使用 `kvm_make_request(KVM_REQ_FLUSH_HDBSS, vcpu)`，不是 `kvm_make_all_cpus_request()`
- sync_dirty_log时使用 `kvm_make_all_cpus_request(kvm, KVM_REQ_FLUSH_HDBSS)` 触发批量flush

### 4.1 kvm_handle_hdbss_fault 行为

```c
static int kvm_handle_hdbss_fault(struct kvm_vcpu *vcpu)
{
    u64 prod = read_sysreg_s(SYS_HDBSSPROD_EL2);
    u64 fsc = FIELD_GET(HDBSSPROD_EL2_FSC_MASK, prod);

    switch (fsc) {
    case HDBSSPROD_EL2_FSC_OK:
        /* Buffer full，设置request让下次exit时flush，而不是立即flush */
        kvm_make_request(KVM_REQ_FLUSH_HDBSS, vcpu);
        return 1;
    case HDBSSPROD_EL2_FSC_ExternalAbort:
    case HDBSSPROD_EL2_FSC_GPF:
        return -EFAULT;
    default:
        return -EFAULT;
    }
}
```

## 5. 自动选择Order

```c
/**
 * hdbss_auto_select_order - 根据VM内存自动选择HDBSS buffer order
 *
 * HDBSSBR_EL2中SZ字段范围从0b0000 (4KB)到0b1001 (2MB)
 *
 * @kvm: KVM实例
 * 返回: order值 (0-9)
 *
 * 逻辑: 每个vCPU每1GB RAM增加一个order级别
 * - 2 vCPU, 2GB RAM -> 1 GB/vcpu -> order=1 (8KB)
 * - 4 vCPU, 64GB RAM -> 16 GB/vcpu -> order=4 (64KB)
 * - 4 vCPU, 256GB RAM -> 64 GB/vcpu -> order=6 (256KB)
 */
static unsigned int hdbss_auto_select_order(struct kvm *kvm)
{
    u64 total_ram = 0;
    u32 vcpu_count = kvm->online_vcpus;
    int i;

    if (vcpu_count == 0)
        return HDBSS_MAX_SIZE;

    for (i = 0; i < kvm->nr_memslots; i++) {
        struct kvm_memory_slot *slot = &kvm->memslots[i];
        if (slot->flags & KVM_MEM_LOG_DIRTY_PAGES)
            total_ram += slot->npages << PAGE_SHIFT;
    }

    u64 gb_per_vcpu = total_ram / vcpu_count / SZ_1G;
    u32 order = clamp((u32)ilog2(gb_per_vcpu + 1), 0, HDBSS_MAX_SIZE);

    return order;
}
```

## 6. Enable/Disable函数

```c
int kvm_arm_enable_hdbss_internal(struct kvm *kvm, unsigned long order);
int kvm_arm_disable_hdbss_internal(struct kvm *kvm);
```

这些函数替代原有的ioctl接口，在migration期间内部调用。

## 7. Migration集成点

位于 `virtcca_cvm.c`:

| 函数 | 动作 | 目的 |
|----------|--------|---------|
| `kvm_populate_ipa_cvm_range()` | 调用`kvm_arm_enable_hdbss_internal()` | 迁入时自动enable |
| `virtcca_mig_import_end()` | 调用`kvm_arm_disable_hdbss_internal()` | 迁入完成后自动disable |
| `virtcca_mig_export_abort()` | 调用`kvm_arm_disable_hdbss_internal()` | 迁出中止时自动disable |

## 8. HDBSSBR_EL2定义修复

根据Leo的建议，使用HDBSSBR_EL2_BADDR_MASK替代GENMASK(55, 12 + sz)：

```c
#define HDBSSBR_EL2_BADDR_MASK  GENMASK_ULL(55, 12)

#define HDBSSBR_EL2(baddr, sz)  (((baddr) & HDBSSBR_EL2_BADDR_MASK) | \
                                 FIELD_PREP(HDBSSBR_EL2_SZ_MASK, sz))
```

同时需要添加显式的对齐检查，因为alloc_pages返回的地址可能需要验证。

## 9. DBM属性处理

### 9.1 核心原则

```
变成可写 → 添加DBM
变成非可写 → 清除DBM
临时清除S2AP_W（迁移清除）→ 不动DBM
```

### 9.2 添加DBM

保持原有逻辑，在fault时添加：

```c
// mmu.c:user_mem_abort()
if (writable && kvm->arch.enable_hdbss && logging_active)
    prot |= KVM_PGTABLE_PROT_DBM;
```

### 9.3 清除DBM

在权限真正变更（W→RO）时清除，不是迁移清除：

```c
// stage2_set_prot_attr() 或 kvm_pgtable_stage2_relax_perms()
if (!(prot & KVM_PGTABLE_PROT_W) && (old & KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W)) {
    // 权限从W变成非W，不是迁移清除
    clr |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;
}
```

### 9.4 需要修复的Bug

**Bug 1: stage2_pte_needs_update 把 DBM 视为无关位**

```c
static bool stage2_pte_needs_update(kvm_pte_t old, kvm_pte_t new)
{
    if (!kvm_pte_valid(old) || !kvm_pte_valid(new))
        return true;

+   // DBM变化也需要更新PTE
+   if ((old ^ new) & KVM_PTE_LEAF_ATTR_HI_S2_DBM)
+       return true;

    return ((old ^ new) & (~KVM_PTE_LEAF_ATTR_S2_PERMS));
}
```

**Bug 2: kvm_pgtable_stage2_pte_prot() 不提取 DBM**

```c
enum kvm_pgtable_prot kvm_pgtable_stage2_pte_prot(kvm_pte_t pte)
{
    // ... R/W/X提取 ...
+   if (pte & KVM_PTE_LEAF_ATTR_HI_S2_DBM)
+       prot |= KVM_PGTABLE_PROT_DBM;

    return prot;
}
```

## 10. HugePage处理

在`kvm_init_stage2_mmu()`中检查HDBSS可用性，设置eager page split：

```c
if (system_supports_hdbss())
    mmu->split_page_chunk_size = PAGE_SIZE;
else
    mmu->split_page_chunk_size = KVM_ARM_EAGER_SPLIT_CHUNK_SIZE_DEFAULT;
```

这是因为HDBSS没有fault，所以无法做on-demand block splitting，必须提前eager split。

## 11. API设计

### 11.1 公共函数 (kvm_dirty_bit.h)

```c
/* HDBSS flush操作 */
void kvm_flush_hdbss_buffer(struct kvm_vcpu *vcpu);
void kvm_arm_vcpu_free_hdbss(struct kvm_vcpu *vcpu);

/* VM级HDBSS enable/disable */
int kvm_arm_enable_hdbss_internal(struct kvm *kvm, unsigned long order);
int kvm_arm_disable_hdbss_internal(struct kvm *kvm);

/* 同步脏页到memslot */
void kvm_flush_hdbss_to_memslot(struct kvm *kvm);

/* HDBSS trap handler */
int kvm_handle_hdbss_trap(struct kvm_vcpu *vcpu);

/* 自动选择order */
unsigned int hdbss_auto_select_order(struct kvm *kvm);
```

### 11.2 常量定义

```c
#define HDBSS_MAX_SIZE 9  /* 每个vCPU 2MB buffer */
#define KVM_REQ_FLUSH_HDBSS KVM_ARCH_REQ(10)

/* HDBSS entry字段定义 */
#define HDBSS_ENTRY_VALID BIT(0)
#define HDBSS_ENTRY_IPA  GENMASK_ULL(55, 12)

/* HDBSSBR_EL2定义 */
#define HDBSSBR_EL2_BADDR_MASK GENMASK_ULL(55, 12)
#define HDBSSBR_EL2(baddr, sz)  (((baddr) & HDBSSBR_EL2_BADDR_MASK) | \
                                 FIELD_PREP(HDBSSBR_EL2_SZ_MASK, sz))
#define HDBSSPROD_IDX(prod)  FIELD_GET(HDBSSPROD_EL2_INDEX_MASK, prod)
```

### 11.3 vcpu_hdbss_state 结构

```c
struct vcpu_hdbss_state {
    phys_addr_t base_phys;   // 用于释放内存
    u64 hdbssbr_el2;         // load时直接用
    u64 hdbssprod_el2;       // save时直接用
};
```

## 12. 实现步骤

### Step 1: Revert现有HDBSS代码
- Revert当前分支的所有v1-v3 HDBSS commits
- 从OLK-6.6基线重新开始

### Step 2: 合并v3代码
- 应用v3 patch系列

### Step 3: 创建dirty_bit.c和kvm_dirty_bit.h
- 从arm.c、mmu.c、hyp/pgtable.c集中HDBSS代码

### Step 4: 更新vcpu_hdbss_state结构
- 使用新的结构（base_phys + hdbssbr_el2 + hdbssprod_el2）

### Step 5: 修复HDBSSBR_EL2定义
- 使用`HDBSSBR_EL2_BADDR_MASK`
- 添加对齐检查

### Step 6: 实现flush触发机制
- 更新`kvm_arch_vcpu_ioctl_run()`
- 实现`kvm_sched_out()` hook
- 更新`check_vcpu_requests()`中的flush逻辑

### Step 7: 实现自动enable/disable
- 在virtcca_cvm.c中添加migration hooks

### Step 8: 实现自动size选择
- 添加`hdbss_auto_select_order()`函数

### Step 9: 修复DBM相关bug
- 更新`stage2_pte_needs_update()`
- 更新`kvm_pgtable_stage2_pte_prot()`

### Step 10: HugePage处理
- 在`kvm_init_stage2_mmu()`中设置split_page_chunk_size

### Step 11: HACDBS集成（独立步骤）
- 在v4稳定后再应用Leo的HACDBS patch

## 13. 测试计划

1. **基本功能**: 通过migration启用HDBSS，验证脏页追踪正常工作
2. **自动size**: 验证不同VM大小获得合适的buffer order
3. **Flush触发**: 验证run loop退出、调度出、request、fault都能正确触发flush
4. **Migration完成**: 验证migration结束后HDBSS正确disable
5. **Migration中止**: 验证migration中止时HDBSS正确disable
6. **Dirty ring集成**: 测试HDBSS激活时的dirty ring统计
7. **HugePage**: 验证透明大页场景下eager split正常工作

## 14. 待确认问题

1. HACDBS应该在v4提交上游之前还是之后集成？
2. 是否有最大并发脏页数量限制需要处理？