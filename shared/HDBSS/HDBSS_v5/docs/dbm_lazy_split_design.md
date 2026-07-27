# DBM 适配 Lazy Split 方案设计

## 问题背景

### ARM Spec 关键规则 (D8.5.2.1)

ARM FEAT_HDBSS 下，stage-2 页表描述符有以下状态（VTCR_EL2.HD=1 时生效）：

| 状态 | HD | DBM (bit 51) | S2AP[1] | Guest 写行为 |
|------|-----|-------------|----------|-------------|
| Normal RO | 任意 | **0** | 0 | **Permission Fault** (spec RPZFQC) |
| writable-clean | 1 | **1** | **0** | **硬件静默升级 S2AP[1]=1 + 写 HDBSS, 不 fault** (spec RTYCNM) |
| writable-dirty | 1 | 1 | 1 | 硬件写 HDBSS |

硬件更新脏状态是描述符粒度的原子 read-modify-write (spec RPQJJR)：
- 描述符从 writable-clean → writable-dirty 是**一次性**状态迁移
- HDBSS 只在 clean→dirty transition 时记录 entry
- 一旦描述符已 dirty，后续写入不再产生新 HDBSS 记录

### 当前 v4 代码的问题

`kvm_pgtable_stage2_wrprotect` 只清除 S2AP_W，不清除 DBM：

```c
// arch/arm64/kvm/hyp/pgtable.c:1302
int kvm_pgtable_stage2_wrprotect(struct kvm_pgtable *pgt, u64 addr, u64 size)
{
    return stage2_update_leaf_attrs(pgt, addr, size, 0,
                    KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W,   // 只清 W
                    NULL, NULL, KVM_PGTABLE_WALK_IGNORE_EAGAIN);
}
```

dirty logging 启动后 `kvm_arm_enable_hdbss_global` 设置 HD=1，此时 block 描述符状态：
- DBM=1 + S2AP[1]=0 + HD=1 → **writable-clean**
- Guest 写 → 硬件静默升级，不产生 fault
- **lazy split 永远不会触发**

### Lazy split 的必要性

即使 HDBSS 记录 4KB 精度的 IPA，block 描述符的原子更新使整个 2MB 范围一次 dirty 后再无记录。CLEAR ioctl 想 wrprotect 单个 4KB 页时，block 映射最小 wrprotect 粒度是 2MB，迫使未迁页面也 fault。只有拆成独立 4KB PTE 才能实现 per-page 独立 dirty state 管理和细粒度 wrprotect。

### 与 eager split 的差异

当前 v4 走 eager split，在 kvm_arch_commit_memory_region 中 split 后 wrprotect，4KB PTE 上 DBM=1 + S2AP[1]=0 是 writable-clean，每个 4KB 描述符独立状态，HDBSS 跟踪正确。如果改为 lazy split（不主动拆），则需要解决上述 block entry DBM 问题。

---

## 方案 A：Level-aware wrprotect

### 思路

修改 `kvm_pgtable_stage2_wrprotect`，使其在 block entry（level < 3）上同时清除 DBM 和 W，在 page entry（level == 3）上只清除 W 保留 DBM。每次 wrprotect 自动正确处理。

### 修改文件

**arch/arm64/kvm/hyp/pgtable.c**

1. `stage2_attr_data` 加控制字段：

```c
struct stage2_attr_data {
    kvm_pte_t   attr_set;
    kvm_pte_t   attr_clr;
    kvm_pte_t   pte;
    s8          level;
    bool        dbm_page_keep;   // NEW
};
```

2. `stage2_attr_walker` 加条件判断：

```c
static int stage2_attr_walker(const struct kvm_pgtable_visit_ctx *ctx,
                              enum kvm_pgtable_walk_flags visit)
{
    kvm_pte_t pte = ctx->old;
    struct stage2_attr_data *data = ctx->arg;
    struct kvm_pgtable_mm_ops *mm_ops = ctx->mm_ops;

    if (!kvm_pte_valid(ctx->old))
        return -EAGAIN;

    data->level = ctx->level;
    data->pte = pte;
    pte &= ~data->attr_clr;
    pte |= data->attr_set;

+   if (data->dbm_page_keep &&
+       (data->attr_clr & KVM_PTE_LEAF_ATTR_HI_S2_DBM) &&
+       ctx->level >= KVM_PGTABLE_LAST_LEVEL)
+       pte |= KVM_PTE_LEAF_ATTR_HI_S2_DBM;

    if (data->pte != pte) {
        ... // icache inval + try_set_pte unchanged
    }
    return 0;
}
```

3. `stage2_update_leaf_attrs` 加参数（static 函数，无外部 API 影响）：

```c
static int stage2_update_leaf_attrs(struct kvm_pgtable *pgt, u64 addr,
                                    u64 size, kvm_pte_t attr_set,
                                    kvm_pte_t attr_clr, kvm_pte_t *orig_pte,
                                    s8 *level, enum kvm_pgtable_walk_flags flags,
+                                   bool dbm_page_keep)
{
    struct stage2_attr_data data = {
        .attr_set       = attr_set & attr_mask,
        .attr_clr       = attr_clr & attr_mask,
+       .dbm_page_keep  = dbm_page_keep,
    };
    ...
}
```

4. `kvm_pgtable_stage2_wrprotect` 调用更新：

```c
int kvm_pgtable_stage2_wrprotect(struct kvm_pgtable *pgt, u64 addr, u64 size)
{
    return stage2_update_leaf_attrs(pgt, addr, size, 0,
-                   KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W,
+                   KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W |
+                   KVM_PTE_LEAF_ATTR_HI_S2_DBM,
                    NULL, NULL,
-                   KVM_PGTABLE_WALK_IGNORE_EAGAIN);
+                   KVM_PGTABLE_WALK_IGNORE_EAGAIN,
+                   true);
}
```

5. 其余 2 个调用点传 `false`（行为不变）：

```c
// stage2_relax_perms (line 1411)
ret = stage2_update_leaf_attrs(pgt, addr, 1, set, clr, NULL, &level,
-                              flags);
+                              flags, false);

// kvm_pgtable_stage2_mkyoung (line 1315)  
ret = stage2_update_leaf_attrs(pgt, addr, 1, KVM_PTE_LEAF_ATTR_LO_S2_AF, 0,
-                              NULL, NULL, flags);
+                              NULL, NULL, flags, false);
```

### 语义对照

| 调用者 | dbm_page_keep | DBM 在 clr? | 效果 |
|--------|:---:|:---:|------|
| wrprotect | true | yes | block clr DBM+W→fault→lazy split；page clr W only→HDBSS |
| relax_perms W→RO | false | yes | block & page 都清 DBM→真正只读 |
| mkyoung | false | no | 不受影响 |

### 优点

- 零额外 page table walk
- 行为内聚在 wrprotect 语义中

### 缺点

- 改动 3 个 static 函数 + 1 个 struct，影响通用基础设施
- `stage2_attr_walker` 是页表走查的共享路径，risky

---

## 方案 B：迁移开始时清一次 DBM（推荐）

### 思路

`kvm_pgtable_stage2_wrprotect` 保持现状不动。在 dirty logging 启用时（`kvm_arch_commit_memory_region`），HDBSS enable 之后、wrprotect 之前，加一次 walk 清掉所有 leaf entry 的 DBM。后续 wrprotect 只清 W。

迁移期间新 fault 创建的总是 4KB PTE（`kvm_s2_resolve_vma_size` 在 logging slot 下强制 `max_map_size = PAGE_SIZE`），且 `stage2_set_prot_attr` 对新 PTE 设 DBM=1，不存在"清后又冒出新 block entry"的问题。

### 完整时序

```
初始: 2MB block: DBM=1 W=1  HD=0           ← 正常
        ↓
migration start:
  kvm_arm_enable_hdbss_global → HD=1
  kvm_mmu_clear_dbm_memory_region           ← 新增：清所有 leaf DBM
    → block: DBM=0 W=1                      ← W=1 写仍正常
  kvm_mmu_wp_memory_region → wrprotect
    → block: DBM=0 W=0
        ↓
Round 1 Guest 写:
  block DBM=0 W=0 → Permission Fault ✅
  → vma_pagesize=PAGE_SIZE → stage2_map(PAGE_SIZE) → lazy split 4KB
  → stage2_set_prot_attr → DBM=1 W=1
  → mark dirty → sync → 迁走
        ↓
Round 1 wrprotect (只清 W):
  unsplit block: DBM=0 W=0 → fault → split
  已拆 4KB PTE: DBM=1 W=0 → writable-clean → HDBSS 硬件跟踪 ✅
        ↓
Round 2+:
  所有 4KB PTE: HDBSS 零 fault 跟踪 ✅
```

### 修改文件

**1. arch/arm64/include/asm/kvm_pgtable.h**：新函数声明

```c
int kvm_pgtable_stage2_clear_dbm(struct kvm_pgtable *pgt, u64 addr, u64 size);
```

**2. arch/arm64/kvm/hyp/pgtable.c**：新函数实现（直接复用 `stage2_update_leaf_attrs`）

```c
int kvm_pgtable_stage2_clear_dbm(struct kvm_pgtable *pgt, u64 addr, u64 size)
{
    return stage2_update_leaf_attrs(pgt, addr, size, 0,
                    KVM_PTE_LEAF_ATTR_HI_S2_DBM,
                    NULL, NULL,
                    KVM_PGTABLE_WALK_IGNORE_EAGAIN);
}
```

**3. arch/arm64/kvm/mmu.c**：在 `kvm_arch_commit_memory_region` 中调用

```c
// 新增 wrapper，对称于 kvm_stage2_wp_range
static void kvm_stage2_clear_dbm_range(struct kvm_s2_mmu *mmu,
                                       phys_addr_t addr, phys_addr_t end)
{
    stage2_apply_range_resched(mmu, addr, end,
        KVM_PGT_FN(kvm_pgtable_stage2_clear_dbm));
}

static void kvm_mmu_clear_dbm_memory_region(struct kvm *kvm, int slot)
{
    struct kvm_memslots *slots = kvm_memslots(kvm);
    struct kvm_memory_slot *memslot = id_to_memslot(slots, slot);
    phys_addr_t start, end;

    if (WARN_ON_ONCE(!memslot))
        return;

    start = memslot->base_gfn << PAGE_SHIFT;
    end = (memslot->base_gfn + memslot->npages) << PAGE_SHIFT;

    write_lock(&kvm->mmu_lock);
    kvm_stage2_clear_dbm_range(&kvm->arch.mmu, start, end);
    write_unlock(&kvm->mmu_lock);
}

// 在 kvm_arch_commit_memory_region 中：
void kvm_arch_commit_memory_region(...)
{
    kvm_arm_hdbss_on_dirty_logging_change(kvm,
        atomic_read(&kvm->nr_memslots_dirty_logging));

    if (log_dirty_pages) {
        if (change == KVM_MR_DELETE)
            return;
        if (kvm_dirty_log_manual_protect_and_init_set(kvm))
            return;

+       // 清 DBM: 确保 block entry 写操作产生 fault → lazy split
+       if (system_supports_hdbss())
+           kvm_mmu_clear_dbm_memory_region(kvm, new->id);

        kvm_mmu_wp_memory_region(kvm, new->id);
        kvm_mmu_split_memory_region(kvm, new->id);
    }
    ...
}
```

### 优点

- **零改动通用基础设施**——`stage2_attr_walker`、`stage2_attr_data`、`stage2_update_leaf_attrs`、`kvm_pgtable_stage2_wrprotect` 全部不动
- 风险集中在新增调用路径，独立可控，便于测试和回归
- 语义清晰："迁移开始清一次旧账，之后 wrprotect 不再干预 DBM"

### 缺点

- 迁移开始时多一次 page table walk
- 已拆成 4KB 的页首轮多一次 permission fault（DBM 被清 → 首次写 fault → relax 恢复）

---

## 性能对比

以 256GB VM 为例，2MB block 约 131K 个 leaf entry。

| 指标 | 方案 A | 方案 B |
|------|--------|--------|
| 额外 walk 次数 | 0 | 1 次 / migration start |
| 额外 walk 操作量 | 0 | ~131K 次 PTE 读改写 |
| 额外 walk 耗时 | 0 | <500ms |
| 4KB 页 round 1 行为 | 0 fault（DBM 保留，HDBSS 直接跟踪） | 1 fault/页（DBM 被清 → 首次写 fault → relax 恢复 DBM，仅一轮） |
| block 页 round 1 | fault → lazy split | fault → lazy split（同 A） |
| round 2+ | HDBSS 零 fault | HDBSS 零 fault（同 A） |

方案 B 的一次 walk 消耗 <500ms，远低于热迁移本身拷贝 256GB 数据的网络和内存开销。4KB 页首轮多一次 fault 仅影响第一轮迭代，之后全部硬件跟踪。

### 为什幺 4KB 页只多一轮 fault

HDBSS 清 DBM 时 W=1，Guest 读写正常进行。wrprotect 后 W=0，首次写触发 fault → `kvm_s2_fault_map` 检测 `mapping_size == perm_fault_granule`（都是 PAGE_SIZE）→ 走 `stage2_relax_perms` → 设置 DBM=1 W=1 → mark dirty。round 2 wrprotect 只清 W 不碰 DBM → DBM=1 W=0 (writable-clean) → HDBSS 接管。

---

## 两条 wrprotect 路径的完整调用栈

最终两条路径都到达同一个 `stage2_attr_walker`，区别在入口和操作粒度。

### 路径 1：迁移初始化（migration start）

```
kvm_arch_commit_memory_region                         (mmu.c:2584)
│
├─ kvm_arm_hdbss_on_dirty_logging_change              (dirty_bit.c:209)
│   └─ kvm_arm_enable_hdbss_global                     → VTCR_EL2.HD=1
│
├─ [方案B] kvm_mmu_clear_dbm_memory_region             (mmu.c:NEW)
│   │ 遍历 memslot 全范围
│   │
│   ├─ write_lock(&kvm->mmu_lock)
│   ├─ kvm_stage2_clear_dbm_range                      (mmu.c:NEW)
│   │   └─ stage2_apply_range_resched(mmu, addr, end,
│   │         KVM_PGT_FN(kvm_pgtable_stage2_clear_dbm))
│   │       └─ stage2_apply_range                      (mmu.c:63)
│   │           │ do {
│   │           │   next = stage2_range_addr_end()     ← 按 block size 切 chunk
│   │           │   fn(pgt, addr, next-addr)
│   │           │   cond_resched_rwlock_write()        ← 定期放锁
│   │           │ } while (addr != end)
│   │           │
│   │           └─ kvm_pgtable_stage2_clear_dbm        (pgtable.c:NEW)
│   │               └─ stage2_update_leaf_attrs(
│   │                     attr_set=0,
│   │                     attr_clr=DBM)                 ← 只清 DBM
│   │                   └─ kvm_pgtable_walk
│   │                       └─ stage2_attr_walker
│   │                            pte &= ~DBM
│   │                            stage2_try_set_pte()
│   └─ write_unlock(&kvm->mmu_lock)
│
├─ kvm_mmu_wp_memory_region                            (mmu.c:1275)
│   │
│   ├─ write_lock(&kvm->mmu_lock)
│   ├─ kvm_stage2_wp_range                             (mmu.c:1257)
│   │   └─ stage2_apply_range_resched(mmu, addr, end,
│   │         KVM_PGT_FN(kvm_pgtable_stage2_wrprotect))
│   │       └─ stage2_apply_range                      ← 同一 chunk 机制
│   │           └─ kvm_pgtable_stage2_wrprotect        (pgtable.c:1302)
│   │               └─ stage2_update_leaf_attrs(
│   │                     attr_set=0,
│   │                     attr_clr=S2AP_W)              ← 只清 W，DBM 不动
│   │                   └─ kvm_pgtable_walk
│   │                       └─ stage2_attr_walker       (pgtable.c:1236)
│   │                            pte &= ~S2AP_W
│   │                            stage2_try_set_pte()
│   ├─ kvm_nested_s2_wp(kvm)
│   ├─ write_unlock(&kvm->mmu_lock)
│   └─ kvm_flush_remote_tlbs_memslot
│
├─ kvm_mmu_split_memory_region                          (mmu.c:1303)
│   │
│   ├─ write_lock(&kvm->mmu_lock)
│   ├─ kvm_mmu_split_huge_pages                        (mmu.c:121)
│   │   │ 内部分 chunk 机制同 stage2_apply_range
│   │   └─ kvm_pgtable_stage2_split                   (pgtable.c:1588)
│   │       └─ stage2_split_walker                     (pgtable.c:1520)
│   │           对每个 block entry:
│   │             create_unlinked → 分配下级页表页
│   │             try_break_pte  → 原子替换为 table PTE
│   │             make_pte       → 挂上新 table
│   └─ write_unlock(&kvm->mmu_lock)
│
└─ kvm_mmu_free_memory_cache                            ← 清理（非 logging 时）
```

### 路径 2：迭代轮次（CLEAR ioctl）

```
KVM_CLEAR_DIRTY_LOG ioctl
│
└─ kvm_vm_ioctl_clear_dirty_log                         (kvm_main.c:2407)
    │
    └─ kvm_clear_dirty_log_protect                       (kvm_main.c:2331)
       │  mutex_lock(&kvm->slots_lock)
       │
       ├─ kvm_arch_sync_dirty_log                        (arm.c)
       │   │ HDBSS 模式下: 遍历所有 vCPU，flush HDBSS buffer
       │   │ mark_page_dirty_in_slot → 更新软件 dirty bitmap
       │
       ├─ copy_from_user(dirty_bitmap_buffer)            ← QEMU 传来的 dirty 位图
       │
       ├─ KVM_MMU_LOCK(kvm)
       │
       ├─ for each dirty page set:
       │     atomic_long_fetch_andnot(mask, &dirty_bitmap[i])  ← 原子清 dirty
       │     │
       │     └─ kvm_arch_mmu_enable_log_dirty_pt_masked  (mmu.c:1333)
       │          │
       │          ├─ kvm_stage2_wp_range(&kvm->arch.mmu,  (mmu.c:1257)
       │          │     start, end)                       ← mask → addr
       │          │   └─ stage2_apply_range_resched       ← 同一入口
       │          │       └─ stage2_apply_range
       │          │           └─ kvm_pgtable_stage2_wrprotect
       │          │               └─ stage2_update_leaf_attrs
       │          │                   └─ kvm_pgtable_walk
       │          │                       └─ stage2_attr_walker
       │          │                           │ 此时已是 4KB PTE
       │          │                           │ pte &= ~S2AP_W  ← 只清 W
       │          │                           │ DBM 保持 =1
       │          │                           │ stage2_try_set_pte()
       │          │
       │          └─ kvm_mmu_split_huge_pages            ← 未拆 block 补拆
       │
       ├─ KVM_MMU_UNLOCK(kvm)
       │
       └─ kvm_flush_remote_tlbs_memslot
```

### 两条路径的差异

| | 路径 1（初始化） | 路径 2（迭代轮） |
|---|---|---|
| 入口 | `kvm_arch_commit_memory_region` | `KVM_CLEAR_DIRTY_LOG` ioctl |
| wrprotect wrapper | `kvm_mmu_wp_memory_region` | `kvm_arch_mmu_enable_log_dirty_pt_masked` |
| 范围 | 整个 memslot | 仅 dirty 的 4KB 页集合 |
| 操作粒度 | block + 4KB 混合 | 4KB PTE 为主 |
| 锁范围 | mmu_lock 内部锁 | slots_lock + mmu_lock |
| 到达 walker 路径 | `stage2_apply_range_resched` → … | `stage2_apply_range_resched` → … |
| DBM 状态（方案B后） | 已清过，此时 DBM=0 | fault 后 DBM=1，wrprotect 保留 |

---

## 性能测试方案：TRACE_EVENT 埋点

### 设计思路

不改内核源码进行 walk 计时，而是在 `kvm_mmu_clear_dbm_memory_region` 上下加 `ktime_get()` 打点，通过 TRACE_EVENT 输出到 ftrace ring buffer。tracepoint 未启用时开销为零（nop），启用后可被 ftrace/perf/trace-cmd 消费。

### 改动清单

**1. `include/trace/events/kvm.h`**：新增 `kvm_clear_dbm` tracepoint

```c
TRACE_EVENT(kvm_clear_dbm,

    TP_PROTO(struct kvm *kvm, int slot, unsigned long npages,
             u64 dbm_ns, u64 total_ns),

    TP_ARGS(kvm, slot, npages, dbm_ns, total_ns),

    TP_STRUCT__entry(
        __field(int,           slot)
        __field(unsigned long, npages)
        __field(u64,           dbm_ns)
        __field(u64,           total_ns)
    ),

    TP_fast_assign(
        __entry->slot     = slot;
        __entry->npages   = npages;
        __entry->dbm_ns   = dbm_ns;
        __entry->total_ns = total_ns;
    ),

    TP_printk("slot=%d npages=%lu "
              "dbm_clr=%llu ns total=%llu ns (%.1f%%)",
        __entry->slot, __entry->npages,
        __entry->dbm_ns, __entry->total_ns,
        (double)__entry->dbm_ns * 100 / (__entry->total_ns ?: 1))
);
```

**2. `arch/arm64/kvm/mmu.c`**：加头文件 + 计时 + tracepoint 调用

```c
#include <linux/ktime.h>
#include <trace/events/kvm.h>

void kvm_arch_commit_memory_region(...)
{
    ktime_t t_enter, t_dbm, t_exit;
    ...
    if (log_dirty_pages) {
        ...
        t_enter = ktime_get();

        if (system_supports_hdbss())
            kvm_mmu_clear_dbm_memory_region(kvm, new->id);

        t_dbm = ktime_get();

        if (kvm_dirty_log_manual_protect_and_init_set(kvm))
            return;

        kvm_mmu_wp_memory_region(kvm, new->id);
        kvm_mmu_split_memory_region(kvm, new->id);

        t_exit = ktime_get();

        trace_kvm_clear_dbm(kvm, new->id, new->npages,
                            ktime_to_ns(ktime_sub(t_dbm, t_enter)),
                            ktime_to_ns(ktime_sub(t_exit, t_enter)));
    }
}
```

### 使用方式

```bash
# 启用 tracepoint
echo 1 > /sys/kernel/debug/tracing/events/kvm/kvm_clear_dbm/enable

# 按大页过滤（只看 > 16GB 的 VM）
echo 'npages > 4194304' > /sys/kernel/debug/tracing/events/kvm/kvm_clear_dbm/filter

# 启动热迁移，查看结果
cat /sys/kernel/debug/tracing/trace

# 也可以用 perf
perf record -e kvm:kvm_clear_dbm -a -- qemu-kvm ...

# 关闭
echo 0 > /sys/kernel/debug/tracing/events/kvm/kvm_clear_dbm/enable
```

### 输出示例

```
qemu-kvm-12345 [001] .... 124.820: kvm_clear_dbm:
  slot=0 npages=67108864
  dbm_clr=423000000 ns total=2120000000 ns (19.9%)
```

### 字段含义

| 字段 | 含义 |
|------|------|
| `dbm_ns` | `kvm_mmu_clear_dbm_memory_region` 耗时（ns） |
| `total_ns` | `kvm_arch_commit_memory_region` logging 分支总耗时（DBM清 + wrprotect + split） |
| 占比 | `dbm_ns / total_ns × 100%`：清 DBM 在 memslot commit 中的开销占比 |

### vs trace_printk

| | trace_printk | TRACE_EVENT |
|---|---|---|
| 运行时开关 | ❌ 编译决定 | ✅ `/sys/.../enable` |
| 未启用开销 | 有（每次调都写 ring buffer） | **零**（相当于 nop） |
| 结构化过滤 | ❌ 纯文本 | ✅ 可按字段聚合/过滤 |
| perf 兼容 | ❌ | ✅ `perf record -e kvm:...` |
| 可随 patch 提交 | 不建议 | ✅ |

---

## 推荐方案

**方案 B**，理由：

1. 不动 `stage2_attr_walker` 这一核心共享路径
2. 新代码路径独立，git bisect 定位问题直接
3. 额外 walk 开销可忽略（<500ms vs 迁移总耗时）
4. 首轮多一次 fault 仅影响已拆 4KB 的页（eager split 场景）或不存在 lazy split 场景，与迁移总开销相比极微
