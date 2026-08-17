# HDBSS Dirty Ring 支持方案及 HACDBS 配合方案

## 一、问题陈述

### 1.1 现状

HDBSS v4 代码仅支持 Dirty Bitmap 模式。在 Dirty Ring 模式下存在两个 P0 级问题：

| 问题 | 级别 | 描述 |
|------|------|------|
| **双重标脏** | P0 | Write fault handler 推 ring + HDBSS flush 推 ring = 同一页两次 ring entry |
| **Ring 溢出** | P0 | HDBSS flush 不检查 ring 余量，`kvm_dirty_ring_push()` 在 ring 满时 `WARN_ON_ONCE` 并覆盖已有 entry，脏页丢失 |

### 1.2 双重标脏的根源

当前代码有两条路径同时向 dirty ring 推同一个页：

```
路径1: Write Fault Handler
  user_mem_abort() / gmem_abort()
    → (prot & PROT_W) && !ret
    → mark_page_dirty_in_slot(kvm, memslot, gfn)     ← 推 ring entry (A)

路径2: HDBSS Flush
  kvm_flush_hdbss_buffer()
    → kvm_vcpu_mark_page_dirty(vcpu, gpa >> PAGE_SHIFT)
    → mark_page_dirty_in_slot()
    → kvm_dirty_ring_push(vcpu, slot, rel_gfn)       ← 推 ring entry (B)
```

同一个页的首次写入同时触发两条路径：fault handler 处理写入并推 ring(A)，HDBSS 硬件也记录了这个 IPA，后续 flush 又推一次 ring(B)。

在 Dirty Bitmap 模式下双重标脏无害（`set_bit_le()` 幂等），但 Dirty Ring 模式下同一页两次推 ring = ring 空间浪费 + 可能溢出。

### 1.3 相关代码位置

| 代码 | 文件 | 行号 | 作用 |
|------|------|------|------|
| Fault handler 标脏 | `mmu.c` | 1660 | `mark_page_dirty_in_slot()` — gmem_abort 路径 |
| Fault handler 标脏 | `mmu.c` | 2071 | `mark_page_dirty_in_slot()` — user_mem_abort 路径 |
| HDBSS DBM 设置 | `mmu.c` | 1964 | `*prot |= KVM_PGTABLE_PROT_DBM` |
| HDBSS flush | `mmu.c` | 2241 | `kvm_vcpu_mark_page_dirty()` |
| Ring push 路由 | `kvm_main.c` | 3531-3532 | `kvm_dirty_ring_push()` / `set_bit_le()` 互斥分支 |
| Ring overflow 检查 | `dirty_ring.c` | 225 | `WARN_ON_ONCE(kvm_dirty_ring_full(ring))` |
| Ring soft-full 检查 | `dirty_ring.c` | 240-241 | `kvm_dirty_ring_soft_full()` → `KVM_REQ_DIRTY_RING_SOFT_FULL` |
| HDBSS flush 触发 | `arm.c` | 1244 | `KVM_REQ_FLUSH_HDBSS` vCPU request |
| HDBSS flush 触发 | `mmu.c` | 2261 | HDBSS buffer full fault |
| Sync dirty log | `arm.c` | 2045-2055 | `kvm_arch_sync_dirty_log()` → kick all vCPUs |

---

## 二、方案设计：HDBSS 接管标脏，Fault Handler 退让

### 2.1 核心思路

**当 HDBSS + Dirty Ring 同时启用时，write fault handler 不推 ring，由 HDBSS flush 统一推 ring。HDBSS 成为 Dirty Ring 模式下的唯一标脏源。**

### 2.2 设计原则

1. **单一标脏源**：HDBSS flush 是 Dirty Ring 模式下的唯一 ring push 路径，避免双重标脏
2. **Fault handler 仍设 DBM**：PTE 映射 + DBM 设置不变，只是跳过 `mark_page_dirty_in_slot()` 调用
3. **Bitmap 模式不变**：`!dirty_ring_size` 时保持原行为，双重标脏对 bitmap 无害
4. **Ring 溢出保护**：HDBSS flush 逐条检查 ring 余量，soft-full 时停止 flush 并保留未 flush 的条目

### 2.3 数据流对比

**Before（双重标脏）：**
```
Guest写页X → write fault → fault handler 设DBM + push ring(A)
                         → HDBSS硬件记录IPA_X
                         → 后续flush → push ring(B) ← 重复!
```

**After（HDBSS 接管）：**
```
Guest写页X → write fault → fault handler 设DBM，不推ring
                         → HDBSS硬件记录IPA_X
                         → vCPU exit flush → push ring ← 唯一入口
```

---

## 三、代码改动详解

### 3.1 改动1：Write Fault Handler 跳过 Ring Push

**文件**：`arch/arm64/kvm/mmu.c`

**位置1**：`gmem_abort()` 路径（mmu.c:1659-1660）

```c
// Before:
if ((prot & KVM_PGTABLE_PROT_W) && !ret)
    mark_page_dirty_in_slot(kvm, s2fd->memslot, gfn);

// After:
if ((prot & KVM_PGTABLE_PROT_W) && !ret) {
    if (!kvm->arch.enable_hdbss || !kvm->dirty_ring_size)
        mark_page_dirty_in_slot(kvm, s2fd->memslot, gfn);
}
```

**位置2**：`user_mem_abort()` 路径（mmu.c:2068-2071）

```c
// Before:
if (writable && !ret) {
    phys_addr_t ipa = gfn_to_gpa(get_canonical_gfn(s2fd, s2vi));
    ipa &= ~(mapping_size - 1);
    mark_page_dirty_in_slot(kvm, s2fd->memslot, gpa_to_gfn(ipa));
}

// After:
if (writable && !ret) {
    phys_addr_t ipa = gfn_to_gpa(get_canonical_gfn(s2fd, s2vi));
    ipa &= ~(mapping_size - 1);
    if (!s2fd->vcpu->kvm->arch.enable_hdbss ||
        !s2fd->vcpu->kvm->dirty_ring_size)
        mark_page_dirty_in_slot(kvm, s2fd->memslot, gpa_to_gfn(ipa));
}
```

**逻辑说明**：

| 条件 | 行为 |
|------|------|
| `!enable_hdbss` | HDBSS 未启用，走原路径推 ring/bitmap |
| `!dirty_ring_size` | Dirty Ring 未启用（Bitmap 模式），HDBSS flush 推 bitmap 是幂等的，保持原行为 |
| `enable_hdbss && dirty_ring_size` | 两者同时启用，fault handler 退让，HDBSS flush 接管 |

### 3.2 改动2：HDBSS Flush 处理 Ring 溢出

**文件**：`arch/arm64/kvm/mmu.c` — `kvm_flush_hdbss_buffer()`

**核心变化**：
1. 每次推 ring 前检查 `kvm_dirty_ring_soft_full()`
2. Soft-full 时停止 flush，保留未 flush 条目在 HDBSS buffer
3. 将未 flush 的条目压缩到 buffer 前部，避免索引混乱

```c
void kvm_flush_hdbss_buffer(struct kvm_vcpu *vcpu)
{
    int idx, curr_idx, flushed, remaining;
    u64 br_el2;
    u64 *hdbss_buf;
    struct kvm *kvm = vcpu->kvm;

    if (!kvm->arch.enable_hdbss)
        return;

    curr_idx = HDBSSPROD_IDX(read_sysreg_s(SYS_HDBSSPROD_EL2));
    br_el2 = HDBSSBR_EL2(vcpu->arch.hdbss.base_phys, vcpu->arch.hdbss.size);

    if (curr_idx == 0 || br_el2 == 0)
        return;

    hdbss_buf = page_address(phys_to_page(vcpu->arch.hdbss.base_phys));
    if (!hdbss_buf)
        return;

    guard(write_lock_irqsave)(&vcpu->kvm->mmu_lock);

    flushed = 0;
    for (idx = 0; idx < curr_idx; idx++) {
        u64 gpa;

        gpa = hdbss_buf[idx];
        if (!(gpa & HDBSS_ENTRY_VALID))
            continue;

        if (kvm->dirty_ring_size &&
            kvm_dirty_ring_soft_full(&vcpu->dirty_ring)) {
            kvm_make_request(KVM_REQ_DIRTY_RING_SOFT_FULL, vcpu);
            break;
        }

        gpa &= HDBSS_ENTRY_IPA;
        kvm_vcpu_mark_page_dirty(vcpu, gpa >> PAGE_SHIFT);
        flushed++;
    }

    remaining = curr_idx - flushed;
    if (remaining) {
        /* 压缩未flush的条目到buffer前部 */
        for (idx = 0; idx < remaining; idx++)
            hdbss_buf[idx] = hdbss_buf[flushed + idx];
        write_sysreg_s(HDBSSPROD_IDX(remaining), SYS_HDBSSPROD_EL2);
        vcpu->arch.hdbss.next_index = remaining;
    } else {
        /* 全部flush完成，清空buffer */
        write_sysreg_s(0, SYS_HDBSSPROD_EL2);
        vcpu->arch.hdbss.next_index = 0;
    }
    isb();
}
```

**残留条目压缩的安全性**：

压缩 `hdbss_buf` 时 `hdbss_buf[idx] = hdbss_buf[flushed + idx]`，此操作安全因为：
- flush 在 `check_vcpu_requests()` 或 `kvm_handle_hdbss_fault()` 中调用
- 此时 vCPU 不在 guest 中运行，HDBSS 硬件不会并发写 buffer
- mmu_lock 写锁已持有，无其他 CPU 并发修改

**Ring soft-full 停止后的恢复流程**：

```
HDBSS flush → ring soft-full → 停止flush → 保留未flush条目
    ↓
kvm_make_request(KVM_REQ_DIRTY_RING_SOFT_FULL)
    ↓
vCPU exit → KVM_EXIT_DIRTY_RING_FULL → QEMU harvest ring
    ↓
QEMU: KVM_RESET_DIRTY_RINGS → ring 有空间
    ↓
下次 vCPU exit 或 KVM_REQ_FLUSH_HDBSS → 继续flush残留条目
```

### 3.3 改动3：增加 HDBSS Flush 触发频率

Dirty Ring 模式下 QEMU 不调用 `KVM_GET_DIRTY_LOG`，`kvm_arch_sync_dirty_log()` 可能不被触发。HDBSS buffer flush 需要更及时的触发机制。

#### 现有触发点

| 触发机制 | 触发时机 | Dirty Bitmap | Dirty Ring |
|----------|---------|-------------|------------|
| `KVM_REQ_FLUSH_HDBSS` | `kvm_arch_sync_dirty_log()` kick all vCPUs | ✅ QEMU 主动调用 | ⚠️ 不一定被调用 |
| HDBSS buffer full fault | Buffer 写满 256 条目 | ✅ 自动触发 | ✅ 自动触发 |
| vCPU exit (新) | 每次 vCPU 从 guest exit | 不需要 | ✅ 及时 |

#### 方案：vCPU Exit 时主动 Flush

在 `kvm_handle_guest_abort()` 或 `kvm_vcpu_run()` 返回路径中，Dirty Ring 模式下检查 HDBSS buffer 是否有条目，有则 flush：

```c
/* 在 vCPU exit 回到 KVM 主循环之前 */
if (kvm->arch.enable_hdbss && kvm->dirty_ring_size) {
    u64 prod = read_sysreg_s(SYS_HDBSSPROD_EL2);
    if (HDBSSPROD_IDX(prod) > 0)
        kvm_flush_hdbss_buffer(vcpu);
}
```

**折中优化**：不是每次 vCPU exit 都 flush，而是在以下条件满足时 flush：
- Dirty Ring 模式 + HDBSS 启用
- HDBSS buffer 有条目（`HDBSSPROD_IDX > 0`）
- Ring 未 soft-full

这样保证：
- 首次写入到 ring 推送的时间差 ≤ 一个 vCPU guest 运行周期（通常很短）
- 不会在 ring soft-full 时重复尝试 flush
- HDBSS buffer 满时（256 条目）仍然自动触发 flush

#### 可选增强：周期性 Flush

对长时间在 guest 中运行的 vCPU（如计算密集型 workload），HDBSS buffer 可能积累大量条目但迟迟不 exit。可以考虑：

- 在 vCPU timer interrupt exit 时检查 HDBSS buffer（利用已有 guest timer 退出）
- 或设置 HDBSS buffer threshold 中断（硬件已支持，buffer 写到特定比例时触发 exit）

### 3.4 改动4：Bitmap 模式行为不变

Bitmap 模式下（`!kvm->dirty_ring_size`）：

- Fault handler 的 `mark_page_dirty_in_slot()` 正常调用 → `set_bit_le()` 推 bitmap
- HDBSS flush 的 `kvm_vcpu_mark_page_dirty()` → `mark_page_dirty_in_slot()` → `set_bit_le()` 推 bitmap
- 双重标脏幂等无害

改动1 的条件 `!kvm->dirty_ring_size` 确保 Bitmap 模式下 fault handler 不跳过，行为完全不变。

改动2 的 ring soft-full 检查仅在 `kvm->dirty_ring_size != 0` 时生效，Bitmap 模式下 `kvm_dirty_ring_soft_full()` 不被调用，行为完全不变。

---

## 四、时序保证分析

### 4.1 首次写入的完整时序

```
Guest 写页 X
    ↓ (Stage-2 write fault)
kvm_handle_guest_abort()
    ↓
user_mem_abort()
    → 映射 PTE: PROT_R | PROT_W | PROT_DBM   ← DBM 设置
    → 跳过 mark_page_dirty_in_slot()           ← 不推 ring
    ↓
HDBSS 硬件记录 IPA_X
    ↓ (vCPU exit: 下一次 guest exit 或 HDBSS buffer full)
kvm_flush_hdbss_buffer()
    → kvm_vcpu_mark_page_dirty(X)              ← 推 ring (唯一入口)
    ↓
QEMU Reaper 线程 / vCPU exit
    → kvm_dirty_ring_reap_one()
    → 看到 X 脏页
    → 传输到目标端
```

**时序延迟**：首次写入到 ring 推送的时间差 = vCPU 在 guest 内运行到 exit 的时间。通常很短（一次 guest exit 就 flush）。

### 4.2 HDBSS Buffer 满时的时序

```
HDBSS buffer 写满 256 条目
    ↓ (HDBSS hardware fault: FSC=HDBSSPROD_EL2_FSC_OK)
kvm_handle_hdbss_fault()
    ↓
kvm_flush_hdbss_buffer()
    → 256 条目全部推 ring
    → buffer 清空 (HDBSSPROD_EL2 = 0)
```

**延迟**：零延迟，HDBSS buffer 满时立即 flush。

### 4.3 Ring Soft-full 时的时序

```
HDBSS flush 推 ring → ring soft-full
    ↓
停止 flush，保留未 flush 条目
    ↓
kvm_make_request(KVM_REQ_DIRTY_RING_SOFT_FULL)
    ↓
vCPU exit → KVM_EXIT_DIRTY_RING_FULL
    ↓
QEMU: harvest ring → KVM_RESET_DIRTY_RINGS
    ↓ (ring 有空间了)
下次 vCPU exit / KVM_REQ_FLUSH_HDBSS
    ↓
继续 flush 残留条目
```

**延迟**：取决于 QEMU harvest ring 的速度。通常 Reaper 线程 1s 一次轮询，紧急时 vCPU exit 通知触发立即 harvest。

---

## 五、与 HACDBS 的配合方案

### 5.1 无 HACDBS 时（当前 v4）

**HDBSS 记录脏页的时机**：仅记录 writable-clean → writable-dirty 的首次转换。

```
Guest首次写页X → fault → 设DBM → 页变为writable-dirty
                                    ↓
                        HDBSS硬件记录IPA_X
                                    ↓
                        flush → 推ring → QEMU看到X脏

Guest再次写页X → 无fault（PTE已有DBM+W） → 硬件不改HDBSS状态
                                    ↓
                        页仍为writable-dirty，不需要再记录
                                    ↓
                        ring中已有X的entry，QEMU已经知道X脏
```

**结论**：无 HACDBS 时，HDBSS 只记录首次写入，后续写入不产生新的 HDBSS 条目。但 ring 中已有 entry 覆盖了这些后续写入（页一直脏），不需要再推 ring。

### 5.2 有 HACDBS 时（未来）

HACDBS 清除 DBM 后，页变为 writable-clean。后续写入会再次触发 HDBSS 记录 + fault。此时形成闭环：

```
┌──────────────────────────────────────────────────────────────┐
│                      迁移迭代循环                              │
│                                                              │
│  1. QEMU harvest ring → 收集脏页 → 传输到目标端               │
│                                                              │
│  2. HACDBS 清 DBM → 页 writable-dirty → writable-clean       │
│     └──────────────────────────────────────────────┘          │
│                                     ↓                         │
│  3. Guest 再写 → 页 writable-clean → writable-dirty            │
│              ↓                  ↓                              │
│     Stage-2 write fault     HDBSS硬件记录IPA                   │
│              ↓                  ↓                              │
│     fault handler 设DBM    (不推ring，HDBSS接管)               │
│              ↓                  ↓                              │
│     ───────────────── kvm_flush_hdbss_buffer()                │
│                           ↓                                   │
│                    推ring → QEMU看到新脏页                      │
│                           ↓                                   │
│                    回到步骤1                                   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**关键**：HACDBS 清 DBM 后的再写入，HDBSS flush 成为唯一的 ring push 机制。方案天然兼容 HACDBS。

### 5.3 HACDBS + HDBSS + Dirty Ring 的完整数据流

```
                  Guest 写内存
                      │
                      ▼
              ┌─── Stage-2 Fault ───┐
              │                      │
         fault handler           HDBSS 硬件
         设 DBM 位              记录 IPA
         (不推 ring)            到 buffer
              │                      │
              └──────────────────────┘
                      │
                      ▼
              vCPU exit / buffer full
                      │
                      ▼
           kvm_flush_hdbss_buffer()
              │           │
              │     ring soft-full?
              │      ↓YES      ↓NO
              │   停止flush   全量推ring
              │   保留残留    清空buffer
              │      │          │
              └──────┴──────────┘
                      │
                      ▼
              QEMU harvest ring
                      │
                      ▼
              HACDBS 清 DBM (writable-dirty → writable-clean)
                      │
                      ▼
              Guest 再写 → 回到开头
```

### 5.4 HACDBS Ring 清脏路径的适配

当前 HACDBS 的 Dirty Ring 清脏路径：

```c
__kvm_arch_dirty_ring_clear()
    → 遍历 ring harvested entries
    → 转为 HDBSS entries (hw_entries[])
    → dirty_bit_clear(kvm, hw_entries, size)
        → HACDBS 硬件清 DBM
    → 成功的 entry → kvm_dirty_gfn_set_invalid()
```

**与 HDBSS 接管方案的兼容性**：

| 环节 | 兼容性 | 说明 |
|------|--------|------|
| Ring harvested entries 来源 | ✅ | HDBSS flush 推 ring → QEMU harvest → ring reset → HACDBS 读 harvested entries |
| HACDBS 清 DBM | ✅ | 清 DBM 后页变 writable-clean，后续写触发 HDBSS 记录 |
| Ring 清脏后重标脏 | ✅ | HACDBS 清脏 → Guest 再写 → HDBSS 记录 → flush 推 ring → 新 entry |

**无额外改动**：HACDBS 的 `__kvm_arch_dirty_ring_clear()` 不需要修改。它读取的是 ring entries（由 HDBSS flush 推入），不是 HDBSS buffer 条目，数据路径天然对接。

### 5.5 HACDBS Bitmap 清脏路径的适配

当前 HACDBS 的 Dirty Bitmap 清脏路径：

```c
__kvm_arch_dirty_log_clear()
    → 遍历 bitmap dirty bits
    → 转为 HDBSS entries
    → dirty_bit_clear(kvm, hw_entries, size)
        → HACDBS 硬件清 DBM
    → 成功 → 清 bitmap bits
    → 失败 → 回写 bitmap (hdbss_to_bitmap fallback)
```

**此路径在 Dirty Ring 模式下不使用**：Bitmap 清脏路径仅在 `kvm_get_dirty_log_protect()` / `kvm_clear_dirty_log_protect()` 中调用，这些是 Dirty Bitmap 模式专用的 ioctl。Dirty Ring 模式走 `kvm_dirty_ring_reset()` → `__kvm_arch_dirty_ring_clear()`。

### 5.6 Eager Splitting 与 HACDBS 的交互

| 模式 | Eager Splitting | HACDBS 清脏 | 说明 |
|------|----------------|------------|------|
| Dirty Bitmap + manual-protect | ✅ 有 | ✅ 有 | `__kvm_arch_dirty_log_clear()` 拆大页 + HACDBS 清 DBM |
| Dirty Ring | ⚠️ 无 | ✅ 有 | `__kvm_arch_dirty_ring_clear()` 不拆大页，但 ring 模式要求页预先 write-protect |

**Dirty Ring + HACDBS 的拆大页策略**：

Dirty Ring 模式下 HACDBS 清脏后会将页设为 writable-clean。如果页是大页（block mapping），后续写会触发 permission fault，fault handler 需要拆大页。

当前 `__kvm_arch_dirty_ring_clear()` 不拆大页。两种策略：

1. **依赖 eager splitting**：HDBSS enable 时 `split_page_chunk_size = PAGE_SIZE`，commit 阶段全量拆大页。后续所有页都是 PAGE_SIZE mapping，不存在大页问题。
2. **HACDBS ring 清脏时拆大页**：在 `__kvm_arch_dirty_ring_clear()` 中加入拆大页逻辑（类似 bitmap 模式的 `kvm_mmu_split_huge_pages()`）。

**推荐策略1**：依赖 eager splitting。理由：
- HDBSS 已默认 `split_page_chunk_size = PAGE_SIZE`，commit 时全量拆大页
- 避免在 HACDBS ring 清脏路径中引入 mmu_lock 写锁 + 拆大页开销
- Ring 清脏路径不需要 mmu_lock（当前无 mmu_lock），加入拆大页需要持锁，增加复杂度

---

## 六、模式组合总结

### 6.1 无本方案时（HDBSS v4 现状）

| 模式组合 | 能工作吗？ | 说明 |
|----------|-----------|------|
| Dirty Bitmap（无 HDBSS） | ✅ | 传统方式 |
| Dirty Bitmap + HDBSS | ✅ | HDBSS flush → bitmap，幂等无害 |
| Dirty Ring（无 HDBSS） | ✅ | 传统方式 |
| Dirty Ring + HDBSS | ❌ | 双重标脏 + ring 溢出 |

### 6.2 有本方案后

| 模式组合 | 能工作吗？ | 说明 |
|----------|-----------|------|
| Dirty Bitmap（无 HDBSS） | ✅ | 不变 |
| Dirty Bitmap + HDBSS | ✅ | 不变（条件 `!dirty_ring_size` 使 fault handler 不跳过） |
| Dirty Ring（无 HDBSS） | ✅ | 不变（条件 `!enable_hdbss` 使 fault handler 不跳过） |
| Dirty Ring + HDBSS | ✅ | HDBSS 接管标脏，fault handler 退让，ring 溓出保护 |
| Dirty Ring + HDBSS + HACDBS | ✅ | HDBSS flush 推 ring → HACDBS 读 ring 清 DBM → 闭环 |

### 6.3 与旧分析文档的对比

旧文档（`HDBSS-HACDBS-analysis.md` 第七章）结论："HDBSS + Dirty Ring 不行"。本方案推翻此结论：

- 旧结论基于 HDBSS flush 只推 bitmap、ring 为空的假设
- 实际上 `kvm_vcpu_mark_page_dirty()` → `mark_page_dirty_in_slot()` 已经包含 ring 分支（`kvm_main.c:3531`），HDBSS flush 天然支持推 ring
- 真正的问题是双重标脏和 ring 溢出，而非 "ring 为空"

---

## 七、风险评估

| 风险 | 级别 | 缓解措施 |
|------|------|---------|
| 残留条目压缩时硬件并发写 | 低 | flush 期间 vCPU 不在 guest，硬件不写 buffer |
| vCPU exit flush 频率过高 | 中 | 仅在 dirty ring 模式 + buffer 有条目时 flush；可进一步优化为仅在特定 exit reason 时 flush |
| Fault handler 跳过 push 后 vCPU crash 导致 HDBSS 条目丢失 | 低 | HDBSS buffer 在物理内存中，vCPU crash 后 QEMU 最终 flush |
| `enable_hdbss` 将改为内核自动启用，条件判断需同步更新 | 低 | 使用 `system_supports_hdbss()` 而非 `kvm->arch.enable_hdbss` 判断（与现有 eager splitting 方案一致） |
| HACDBS ring 清脏不拆大页 | 低 | 依赖 eager splitting（`split_page_chunk_size = PAGE_SIZE`）已全量拆 |

---

## 八、改动清单

| # | 文件 | 改动 | 影响范围 |
|---|------|------|---------|
| 1 | `arch/arm64/kvm/mmu.c:1659-1660` | gmem_abort 跳过 `mark_page_dirty_in_slot()` | HDBSS+ring |
| 2 | `arch/arm64/kvm/mmu.c:2068-2071` | user_mem_abort 跳过 `mark_page_dirty_in_slot()` | HDBSS+ring |
| 3 | `arch/arm64/kvm/mmu.c:2211-2248` | `kvm_flush_hdbss_buffer()` ring soft-full 检查 + 部分 flush + 残留压缩 | HDBSS+ring |
| 4 | `arch/arm64/kvm/mmu.c` 或 `arm.c` | vCPU exit 时主动 flush HDBSS buffer | HDBSS+ring |
| 5 | 无需改动 | Bitmap 模式行为不变 | 无 |

---

## 九、测试验证要点

### 9.1 功能测试

| 测试项 | 方法 | 预期 |
|--------|------|------|
| Dirty Ring + HDBSS 基本迁移 | QEMU `-dirty-ring-size=65536` + HDBSS enable | 迁移成功，无脏页丢失 |
| 双重标脏消除 | 迁移期间统计 ring entries 数量 vs 脏页数 | ring entries ≤ 脏页数（1:1 或 1:N 合理比例，无重复） |
| Ring 溢出保护 | 高频写 workload + 小 ring size | 无 `WARN_ON_ONCE` 触发，soft-full 正确退出到 QEMU |
| 残留条目恢复 | ring soft-full 后继续写 → QEMU harvest → 再 flush | 残留条目全部推入 ring，无丢失 |
| Bitmap 模式不变 | `-dirty-ring-size=0`（默认 bitmap） | 行为与改动前完全一致 |

### 9.2 性能测试

| 测试项 | 方法 | 预期 |
|--------|------|------|
| Ring 推送延迟 | 测量首次写入到 ring entry 出现的时间 | ≤ 一个 vCPU guest 运行周期 |
| Flush 开销 | vCPU exit 时 flush 频率 + 耗时 | 仅在有 HDBSS 条目时 flush，无条目时零开销 |
| 迁移吞吐 | 对比 bitmap+HDBSS vs ring+HDBSS 迁移时间 | ring 模式应持平或优于 bitmap |

### 9.3 边界测试

| 测试项 | 方法 | 预期 |
|--------|------|------|
| 4K/16K/64K 页大小 | 不同 `CONFIG_ARM64_*_PAGES` 配置 | PAGE_SIZE 均为合法 chunk_size |
| HDBSS buffer 全满 | 写满 256 条目 | 自动触发 flush，ring 正常 |
| Ring size 极小 | `dirty-ring-size=` 最小值 | soft-full 快速触发，正确退出 |
| 多 vCPU | 4+ vCPU 各自 ring | 各 vCPU flush 自己的 HDBSS buffer，无交叉 |

---

*整理时间：2026-06-13*
