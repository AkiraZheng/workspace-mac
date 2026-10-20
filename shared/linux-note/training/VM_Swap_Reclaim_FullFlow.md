# 虚拟化场景下页面 Swap 回收机制完整流程

> 基于 OLK-6.6 (Linux 6.6) + ARM64 KVM 源码分析
> 涵盖 Host S1、KVM Stage2、Guest OS 三层交互

---

## 1. 术语约定

| 术语 | 含义 |
|------|------|
| **S1 (Stage 1)** | Host 用户的页表（QEMU 进程的 VA→PA 映射），也指 Guest 内核的页表（Guest VA→GPA 映射） |
| **S2 (Stage 2)** | KVM 的 Stage 2 页表（GPA→HPA 映射），由 `kvm_pgtable` 管理 |
| **Host kernel** | 运行 KVM 的宿主机内核 |
| **Guest kernel** | 虚拟机内核 |
| **QEMU** | Host 用户态 VMM，通过 KVM ioctl 管理 VM |
| **mmu_notifier** | Host 内核→KVM 的回调机制，通知 S2 映射变更 |
| **IPA** | Intermediate Physical Address（Guest 物理地址） |
| **HPA** | Host Physical Address |

### 1.1 三层地址翻译

```
Guest VA  →  Guest PA (IPA)  →  Host PA
  S1 (Guest)     S2 (KVM)
  Guest 页表      kvm_pgtable
```

- **Guest S1**：Guest 内核维护，Guest 页表，完全在 Guest 控制内
- **Host S1**：QEMU 进程的页表，Host 内核维护，映射 QEMU 的 VA→HPA
- **KVM S2**：KVM 维护，映射 GPA→HPA，`arch/arm64/kvm/hyp/pgtable.c`

---

## 2. 整体架构：三层 LRU + 两套 swap

```
┌─────────────────────────────────────────────────────────┐
│  Guest OS (VM)                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Guest S1 页表 (VA→GPA)                           │  │
│  │  Guest LRU (folio on guest lruvec)                 │  │
│  │  Guest swap 分区/文件 (virtio-blk / virtio-nfs)   │  │
│  │  Guest vmscan: shrink_lruvec()                     │  │
│  └───────────────────────────────────────────────────┘  │
│                        ↕  fault → guest exit            │
├─────────────────────────────────────────────────────────┤
│  KVM (Host kernel module)                               │
│  ┌───────────────────────────────────────────────────┐  │
│  │  S2 页表 (GPA→HPA), kvm_pgtable                   │  │
│  │  mmu_notifier 回调 (7 个 hook)                     │  │
│  │  dirty_bitmap (KVM 自己的脏页位图, 用于迁移)       │  │
│  │  S2 young bit (kvm_pgtable_stage2_test_clear_young)│  │
│  └───────────────────────────────────────────────────┘  │
│                        ↕  mmu_notifier                  │
├─────────────────────────────────────────────────────────┤
│  Host kernel                                             │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Host S1 页表 (QEMU VA→HPA)                        │  │
│  │  Host LRU (folio on host lruvec)                   │  │
│  │  Host swap 分区/文件                               │  │
│  │  Host vmscan: shrink_lruvec()                      │  │
│  │  mmu_notifier 子系统                               │  │
│  └───────────────────────────────────────────────────┘  │
│                        ↕                                │
│  Host swap 设备 (磁盘/NVMe/zram)                        │
└─────────────────────────────────────────────────────────┘
```

**关键认知**：
1. **Guest 有自己的 swap**——Guest 内核可以独立做 swap-out/swap-in，走自己的 virtio-blk，完全不通知 Host
2. **Host 也可以 swap Guest 的内存**——Host 把 QEMU 进程的页 swap 出去，KVM 通过 mmu_notifier 同步拆 S2 映射
3. **两层 swap 独立但会互相影响**——Guest swap 了某页 → Host 对应的 page 变成 clean → Host 更容易回收

---

## 3. 场景一：Guest 自己做 Swap 回收

这是最简单的情况——Guest 内核自己决定回收内存。

### 3.1 Guest swap-out 流程

```
Guest 内核 kswapd / direct reclaim
  │
  ├── shrink_lruvec()  (Guest mm/)
  │     ├── 隔离冷页 (folio_test_active=0, referenced=0)
  │     ├── 检查 folio_test_dirty(folio)
  │     │     └── dirty=1 → pageout() → swap_write()
  │     │         → 写入 Guest swap 设备 (virtio-blk)
  │     │         → virtio_blk_queue_rq() → Host KVM 处理 I/O
  │     │           (Host 看到的是普通 virtio-blk I/O，不影响 Host 内存管理)
  │     │
  │     ├── try_to_unmap() → 解除 Guest S1 PTE
  │     │     (Guest PTE 被换成 swap entry)
  │     └── folio 释放回 buddy (Guest)
  │
  └── Guest S2 映射不变！
      (Host 不知道 Guest 把这页 swap 了，S2 PTE 还在，
       但 Host 的 page refcount 没变，Host 可能也把这页 swap 走)
```

**注意**：Guest swap 完成后：
- Guest S1 PTE 变成 swap entry（`swp_entry_t`）
- **Guest S2 PTE 仍然指向 Host 的 HPA**——Host 不知道 Guest 侧做了 swap
- Host 的 page 仍然在 Host LRU 上，Host 可以独立决定回收它
- **如果 Guest 再次访问这个地址** → Guest S1 page fault（不是 guest exit）→ Guest 内核 swap-in

### 3.2 Guest swap-in 流程

```
Guest 进程访问被 swap 的地址
  │
  ├── Guest S1 page fault (do_swap_page)
  │     ├── 从 Guest swap 设备读回数据
  │     │   (virtio-blk I/O → Host 处理)
  │     ├── 可能分配新的 Guest 物理页 (GPA)
  │     │   如果新 GPA 和原来的不同 → S2 映射需要更新
  │     │   → Guest 不会主动通知 Host
  │     │   → 只有当 Guest 再次访问这个 GPA 时
  │     │     → Guest exit → user_mem_abort()
  │     │     → 如果 S2 还在指向旧 HPA → 正好复用
  │     │     → 如果 Host 已经回收旧 HPA → S2 unmap 过 → 重新建立映射
  │     └── 恢复 Guest S1 PTE
```

**微妙之处**：Guest swap-in 可能分配**新的物理页（GPA）**，这个 GPA 在 S2 里可能：
- 还指向原来的 HPA（如果 Host 没动）→ **不需要 guest exit**
- S2 映射已被 Host 回收（见下一节）→ Guest 访问时 guest exit → `user_mem_abort()` 重建映射

---

## 4. 场景二：Host 回收 Guest 内存（核心场景）

**这是最复杂的路径**——Host 的 vmscan 决定回收属于 QEMU 进程的页面（即 Guest 内存的 backing page）。

### 4.1 总览：Host vmscan → mmu_notifier → KVM S2 unmap → Host swap

```
Host kswapd / direct reclaim
  │
  ├── shrink_lruvec() → 隔离 QEMU 进程的 folio
  │     (这个 folio 是 Guest 物理 GPA 对应的 Host HPA)
  │
  ├── try_to_unmap() → 解除 Host S1 PTE (QEMU 进程的映射)
  │     ├── mmu_notifier invalidate_range_start()
  │     │     → kvm_mmu_notifier_invalidate_range_start()
  │     │       → __kvm_handle_hva_range(kvm, &hva_range)
  │     │         → 遍历 memslot 找到 GFN 范围
  │     │         → kvm_unmap_gfn_range()
  │     │           → __unmap_stage2_range()  ★ 拆除 S2 PTE
  │     │             (kvm_pgtable_stage2_unmap)
  │     │
  │     ├── rmap walk → try_to_unmap_one()
  │     │     → 如果 PTE dirty → folio_mark_dirty(folio)
  │     │     (把 Host S1 PTE 的 dirty 迁移到 folio PG_dirty)
  │     └── Host S1 PTE 被清除
  │
  ├── 检查 folio_test_dirty(folio)
  │     ├── dirty=1 → pageout() → swap_write()
  │     │     → 写入 Host swap 设备 (磁盘/NVMe/zram)
  │     │     → folio_clear_dirty()
  │     └── dirty=0 → PAGE_CLEAN → 直接释放
  │
  └── folio 释放回 Host buddy

  ---- 之后 Guest 访问这个 GPA ----

  Guest 访问被回收的 GPA
  │
  ├── S2 PTE 不存在 → Translation fault
  │   → Guest exit
  │   → KVM: user_mem_abort()
  │     ├── __gfn_to_pfn_memslot() → 触发 Host page fault
  │     │   (Host S1 PTE 也不在了 → do_swap_page)
  │     │   → Host 内核 swap-in：从 swap 设备读回数据
  │     │   → 分配新 HPA (或复用旧的)
  │     ├── kvm_pgtable_stage2_map()  ★ 重建 S2 PTE
  │     └── Guest resume
```

### 4.2 详细步骤分解

#### Step 1: Host vmscan 隔离页

```c
// mm/vmscan.c — shrink_lruvec()
// Host 的 LRU 链表上有 QEMU 进程的 folio
// 这些 folio 通过 Host S1 PTE 映射到 QEMU 的用户空间
// 同时通过 S2 PTE 映射到 Guest 的 GPA

folio = lru_to_folio(src);  // 从 LRU 取 folio
// 检查 folio flags:
//   - PG_dirty: 内容比后端新，需要写回
//   - PG_active/referenced: 冷热状态
//   - PG_swapbacked: 匿名页，backed by swap
```

#### Step 2: mmu_notifier invalidate_range_start — 拆 S2

**这是 Host 和 KVM 的同步点**。Host 要修改/删除一个 PTE 前，必须通知 KVM 拆除对应的 S2 映射：

```c
// mm/rmap.c — try_to_unmap_one()
// Host 要清除一个映射了 folio 的 PTE
// 在清除 PTE 之前，先发 mmu_notifier

// mmu_notifier 链：
//   mmu_notifier_invalidate_range_start()
//     → kvm_mmu_notifier_invalidate_range_start()     [virt/kvm/kvm_main.c:788]
//       → __kvm_handle_hva_range(kvm, &hva_range)
//         → 遍历 KVM memslot，HVA 范围 → GFN 范围
//         → hva_range.handler = kvm_unmap_gfn_range
//         → KVM_MMU_LOCK(kvm)  ← 加锁保护 S2 页表
//         → kvm_unmap_gfn_range(kvm, &gfn_range)      [arch/arm64/kvm/mmu.c:1904]
//           → __unmap_stage2_range(&kvm->arch.mmu, ...)
//             → kvm_pgtable_stage2_unmap()              [arch/arm64/kvm/hyp/pgtable.c:1139]
//               ★ 遍历 S2 页表，清除所有覆盖该 GPA 范围的 PTE
//         → KVM_MMU_UNLOCK(kvm)
//         → 如果需要 → kvm_flush_remote_tlbs(kvm)
//           (广播 TLB invalidation 给所有运行 Guest 的 CPU)
```

**关键点**：
- KVM 的 `mmu_notifier_ops` 注册了 7 个回调（`virt/kvm/kvm_main.c:939`）：
  - `invalidate_range_start` — 拆 S2 映射（最核心）
  - `invalidate_range_end` — 完成通知
  - `clear_flush_young` — 清 S2 young bit + flush TLB
  - `clear_young` — 清 S2 young bit，不 flush
  - `test_young` — 查询 S2 young bit
  - `change_pte` — Host S1 PTE 变了（COW 等）
  - `release` — mm 销毁

#### Step 3: Host S1 PTE 清除 + dirty 迁移

```c
// mm/rmap.c:1800 — try_to_unmap_one()
// mmu_notifier 回来后，清除 Host S1 PTE
pteval = ptep_clear_flush(vma, address, pvmw.pte);

// PTE dirty 信息迁移到 folio
if (pte_dirty(pteval))
    folio_mark_dirty(folio);   // ← Host S1 PTE dirty → folio PG_dirty
```

**为什么这一步重要**：QEMU 是 Host 用户态进程，它对 Guest 内存的写操作会让 Host S1 PTE 变 dirty（硬件 DBM）。拆除 S1 PTE 时，必须把这个 dirty 信息保存到 folio，否则后续 swap 会误判为 clean 直接丢弃。

#### Step 4: dirty 检查 → pageout → swap write

```c
// mm/vmscan.c:1317 — shrink_folio()
if (folio_test_dirty(folio)) {
    // 脏页 → 必须 pageout
    switch (pageout(folio, mapping, &plug, folio_list)) {
    case PAGE_SUCCESS:
        // swap_write 成功
        // → folio_clear_dirty()
        break;
    case PAGE_ACTIVATE:
        // 写不了 → 保留
        goto keep_locked;
    }
}
```

**Swap 写回的底层调用链**：

```
pageout()
  → swap_write(page, &wbc)
    → __swap_writepage() / swap_writepage()
      → mm/page_io.c
        → 提交 bio 到 swap 设备
        → bio 确认写入完成
        → folio_end_writeback(folio)
        → folio_clear_dirty(folio)
```

#### Step 5: folio 释放

```
shrink_folio()
  → folio_put(folio)     // refcount -1
  → 如果 refcount == 0
    → __page_cache_release(folio)
      → lruvec_del_folio()  // 从 Host LRU 链表移除
      → __free_one_page()   // 回到 Host buddy allocator
```

**注意**：KVM 之前的 `gfn_to_pfn` 会调 `get_page()` 增加引用计数，mmu_notifier 拆 S2 时不一定减引用。所以这个 folio 可能还有 KVM 的引用，**只有所有引用都释放后才能真正回收**。

### 4.3 Guest 再次访问 → fault-back-in

```
Guest vCPU 执行 load/store 指令
  → S2 PTE 不存在 (被 step 2 拆了)
  → Stage 2 Translation Fault
  → Guest exit → Host KVM 处理

KVM: user_mem_abort()  [arch/arm64/kvm/mmu.c:1472]
  │
  ├── 从 ESR_EL2 读取 fault 信息 (fault_ipa, fault_status)
  ├── 判断是 read fault 还是 write fault
  ├── mmap_read_lock(current->mm)
  ├── vma = vma_lookup(current->mm, hva)  // 找 QEMU 的 VMA
  │
  ├── mmu_seq = vcpu->kvm->mmu_invalidate_seq
  │   (检测 invalidate 是否在并发进行)
  │
  ├── mmap_read_unlock(current->mm)
  │
  ├── pfn = __gfn_to_pfn_memslot(memslot, gfn, ...)  ★ 关键
  │   │
  │   ├── hva_to_pfn() → try to get Host physical page
  │   │   ├── Host S1 PTE 存在? → 直接用 pfn (fast path)
  │   │   └── Host S1 PTE 不存在? → 触发 Host page fault
  │   │       (因为 QEMU 的映射被 swap 了)
  │   │       → do_swap_page()
  │   │       → Host 内核从 swap 设备读回数据
  │   │       → 分配新 HPA (或复用 cache)
  │   │       → 建立 Host S1 PTE (QEMU VA→HPA)
  │   │       → 返回 pfn
  │   │
  │   └── 检查 mmu_invalidate_seq 是否变化
  │       (如果在上面过程中 Host 又发了 invalidate → 重来)
  │
  ├── kvm_pgtable_stage2_map(pgt, fault_ipa, PAGE_SIZE,
  │                            __pfn_to_phys(pfn), prot, ...)  ★ 重建 S2
  │   → 在 S2 页表中写入新的 PTE (GPA→HPA)
  │
  └── Guest vCPU resume
      → Guest 重新执行那条 load/store → 成功
```

---

## 5. KVM 的 Dirty 追踪机制（与 Host PG_dirty 并行）

### 5.1 两套 dirty 系统

| 系统 | 粒度 | 用途 | 存储位置 |
|------|------|------|----------|
| **Host PG_dirty** | per-folio | Host swap 决策 | `folio->flags` bit PG_dirty |
| **KVM dirty_bitmap** | per-GFN | VM 迁移/dirty logging | `kvm_memory_slot->dirty_bitmap` |

两者**完全独立**，不要混淆。

### 5.2 KVM dirty 标记路径

```c
// virt/kvm/kvm_main.c
void kvm_set_pfn_dirty(kvm_pfn_t pfn)
{
    if (pfn_valid(pfn))
        kvm_set_page_dirty(pfn_to_page(pfn));  // → SetPageDirty(page)
}
// 注意：这个其实也设了 Host PG_dirty！
// 但它的触发时机是 KVM 做 gfn_to_pfn 后

void mark_page_dirty_in_slot(struct kvm *kvm,
    struct kvm_memory_slot *memslot, gfn_t gfn)
{
    // 标记 KVM dirty_bitmap
    if (kvm_slot_dirty_track_enabled(memslot)) {
        // set bit in memslot->dirty_bitmap
    }
}
```

### 5.3 S2 PTE 的访问权限与 young bit

ARM64 KVM S2 PTE 有以下关键位：

```c
// arch/arm64/kvm/hyp/pgtable.c
// S2 PTE 叶子节点属性:
//   S2AP_R (bit[1:0] bit 0) — Read permission
//   S2AP_W (bit[1:0] bit 1) — Write permission
//   S2_AF  — Access Flag (young bit)
```

**S2 young bit 的清除和检查**由 mmu_notifier 的 `clear_young` / `test_young` 触发：

```c
// virt/kvm/kvm_main.c:895 — kvm_mmu_notifier_clear_young()
→ kvm_handle_hva_range_no_flush(mn, start, end, kvm_age_gfn)
  → kvm_age_gfn(kvm, &gfn_range)  [arch/arm64/kvm/mmu.c:1951]
    → kvm_pgtable_stage2_test_clear_young(pgt, addr, size, mkold=true)
      → stage2_age_walker()  // 遍历 S2 叶子 PTE
        → 如果 PTE 的 AF 位 set → data.young = true
        → 如果 mkold → 清除 AF 位
```

**Host rmap 怎么用 S2 young bit**：

```
Host vmscan want to know if a page is "young" (recently accessed)
  │
  ├── Host S1 PTE 的 accessed bit → check bit
  │
  ├── KVM S2 PTE 的 AF bit → mmu_notifier test_young
  │     → kvm_test_age_gfn()
  │       → kvm_pgtable_stage2_test_clear_young(mkold=false)
  │         → 查 S2 PTE 有没有 AF=1
  │
  └── 如果两边都 "not young" → page 是冷的 → 可以回收
      → 如果要清除 → clear_young
        → kvm_age_gfn(mkold=true)
          → 清 S2 AF bit (但不 flush TLB，允许短暂不一致)
```

**注意 `clear_young` 不 flush TLB**（注释在 `virt/kvm/kvm_main.c:901`）——这是性能优化，容忍短暂的 young bit 不一致，等下次 regular TLB flush 自然同步。

---

## 6. 完整时序图：Host Swap Out Guest 页面

```
Time →

Host kswapd          Host rmap          KVM mmu_notifier        S2 Page Table       Guest vCPU
    │                     │                     │                     │                  │
    │ isolate folio       │                     │                     │                  │
    │ (from LRU)          │                     │                     │                  │
    ├────────────────────►│                     │                     │                  │
    │                     │ try_to_unmap_one()  │                     │                  │
    │                     ├────────────────────►│                     │                  │
    │                     │ invalidate_range_   │                     │                  │
    │                     │   start()           │                     │                  │
    │                     │                     │ kvm_unmap_gfn_range │                  │
    │                     │                     ├────────────────────►│                  │
    │                     │                     │                     │ unmap S2 PTE     │
    │                     │                     │                     │ (GPA→HPA 删除)   │
    │                     │                     │                     │                  │
    │                     │                     │ kvm_flush_remote_   │                  │
    │                     │                     │   tlbs()            │  (TLB invalidation│
    │                     │                     │                     │   广播到所有 vCPU)│
    │                     │                     │                     │                  │
    │                     │ clear Host S1 PTE   │                     │                  │
    │                     │ (QEMU VA→HPA 删除)  │                     │                  │
    │                     │                     │                     │                  │
    │                     │ pte_dirty?          │                     │                  │
    │                     │ → folio_mark_dirty()│                     │                  │
    │                     │                     │                     │                  │
    │ folio_test_dirty()? │                     │                     │                  │
    │ → YES               │                     │                     │                  │
    │ pageout()           │                     │                     │                  │
    │ → swap_write()      │                     │                     │                  │
    │ → bio submit        │                     │                     │                  │
    │ → I/O complete      │                     │                     │                  │
    │ → folio_clear_dirty │                     │                     │                  │
    │                     │                     │                     │                  │
    │ folio_put()         │                     │                     │                  │
    │ → buddy free        │                     │                     │                  │
    │                     │                     │                     │                  │
    │                     │                     │                     │    (某时刻)       │
    │                     │                     │                     │    Guest 访问 GPA│
    │                     │                     │                     │   ──────────────►│
    │                     │                     │                     │  S2 fault!       │
    │                     │                     │                     │  Guest exit      │
    │                     │                     │                     │                  │
    │                     │                     │  user_mem_abort()  │                  │
    │                     │                     │◄───────────────────┤                  │
    │                     │                     │ gfn_to_pfn_memslot  │                  │
    │                     │                     │  → Host page fault  │                  │
    │                     │                     │  → do_swap_page()   │                  │
    │                     │                     │  → swap-in from disk │                  │
    │                     │                     │  → 新 HPA            │                  │
    │                     │                     │                     │                  │
    │                     │                     │ kvm_pgtable_stage2_ │                  │
    │                     │                     │   map()             │                  │
    │                     │                     ├────────────────────►│                  │
    │                     │                     │                     │ 重建 S2 PTE     │
    │                     │                     │                     │ (GPA→新HPA)     │
    │                     │                     │                     │                  │
    │                     │                     │                     │  Guest resume   │
    │                     │                     │                     │  ──────────────►│
    │                     │                     │                     │  load/store OK  │
```

---

## 7. 双层 Swap 交互分析

### 7.1 Guest swap 先于 Host

```
Guest 决定回收 GPA-X
  → Guest swap-out (写 Guest swap 设备)
  → Guest S1 PTE → swap entry
  → S2 PTE 仍然存在 (GPA-X → HPA-Y)
  → Host 的 page (HPA-Y) 仍在 Host LRU 上

  此时 Host 视角:
    - QEMU 的 S1 PTE 还映射着 HPA-Y (QEMU 访问 hva 时可能 fault，也可能正常)
    - Host 不知道 Guest swap 了这页
    - HPA-Y 的 PG_dirty 可能 = 1 (Guest 写过)
    - Host 可能也决定回收 HPA-Y
    - 回收时同样走 mmu_notifier → S2 unmap → Host swap out
    - 数据写了两份：一份在 Guest swap 设备，一份在 Host swap 设备
    (浪费但不是错误)
```

### 7.2 Host swap 先于 Guest

```
Host 决定回收 HPA-Y (对应 Guest GPA-X)
  → mmu_notifier → S2 unmap (GPA-X → 不存在)
  → Host swap-out HPA-Y 到 Host swap 设备

  此时 Guest 视角:
    - Guest S1 PTE 可能还存在 (GPA-X → Guest 物理页号 N)
    - Guest 不知道 Host 已经把这页 swap 了
    - Guest 访问 GPA-X → S2 fault → Guest exit
    - user_mem_abort() → gfn_to_pfn → Host swap-in
    - 重建 S2 PTE → Guest resume
    (Guest 透明地经历了一次 page fault，但 Guest 内核不知道细节)
```

### 7.3 两者同时（竞态）

```
Guest 正在 swap-out GPA-X  │  Host 正在 swap-out HPA-Y (GPA-X)
  (Guest S1 PTE 换 swap entry)  (S2 PTE 被 unmap)

竞态安全保证:
  - S2 unmap 时 KVM 持有 mmu_lock + srcu lock
  - Guest 的访问需要经过 S2，如果 S2 被拆了 → Guest exit → KVM 处理
  - Guest 的 swap 操作不涉及 Host (走 virtio-blk I/O)
  - 最终结果:
    Guest 侧: S1 PTE = swap entry, swap 设备有数据
    Host 侧: S1 PTE = 不存在, swap 设备有数据
    S2: 不存在
  
  Guest swap-in 时:
    → Guest S1 fault → 读 Guest swap → 可能看到 GPA 不变
    → Guest S1 恢复 → 访问 GPA → S2 fault → Host swap-in → 重建 S2
    → 最终数据一致
```

---

## 8. 源码关键路径索引

| 步骤 | 源码位置 | 函数 |
|------|----------|------|
| Host LRU 隔离 | mm/vmscan.c | `shrink_lruvec()` → `lru_to_folio()` |
| Host unmap | mm/rmap.c:1800 | `try_to_unmap_one()` |
| dirty 迁移 | mm/rmap.c:1800 | `pte_dirty(pteval)` → `folio_mark_dirty(folio)` |
| mmu_notifier 注册 | virt/kvm/kvm_main.c:951 | `kvm_init_mmu_notifier()` |
| mmu_notifier invalidate | virt/kvm/kvm_main.c:788 | `kvm_mmu_notifier_invalidate_range_start()` |
| HVA→GFN 遍历 | virt/kvm/kvm_main.c:596 | `__kvm_handle_hva_range()` |
| S2 unmap | arch/arm64/kvm/mmu.c:1904 | `kvm_unmap_gfn_range()` → `__unmap_stage2_range()` |
| S2 pgtable unmap | arch/arm64/kvm/hyp/pgtable.c:1139 | `kvm_pgtable_stage2_unmap()` |
| S2 young clear | arch/arm64/kvm/mmu.c:1951 | `kvm_age_gfn()` |
| S2 young test | arch/arm64/kvm/mmu.c:1967 | `kvm_test_age_gfn()` |
| S2 young walker | arch/arm64/kvm/hyp/pgtable.c:1285 | `kvm_pgtable_stage2_test_clear_young()` |
| Host swap write | mm/page_io.c | `swap_write()` → bio submit |
| Host swap read | mm/page_io.c | `swap_read_folio()` → bio submit |
| Guest S2 fault handler | arch/arm64/kvm/mmu.c:1472 | `user_mem_abort()` |
| GFN→PFN 解析 | virt/kvm/kvm_main.c:2833 | `__gfn_to_pfn_memslot()` |
| S2 map 重建 | arch/arm64/kvm/mmu.c (user_mem_abort) | `kvm_pgtable_stage2_map()` |
| KVM dirty bitmap | virt/kvm/kvm_main.c:3437 | `mark_page_dirty_in_slot()` |
| KVM set pfn dirty | virt/kvm/kvm_main.c:3087 | `kvm_set_pfn_dirty()` |
| TLB flush 广播 | virt/kvm/kvm_main.c (mmu_notifier) | `kvm_flush_remote_tlbs()` |

---

## 9. 深层问题分析

### 9.1 为什么 mmu_notifier 拆 S2 不需要 flush TLB（clear_young 路径）？

`clear_young` 只清 AF bit，不清 PTE。即使 Guest CPU 的 TLB 里还缓存着 AF=1，最坏结果是 Host 误判一页为"刚被访问过"——这只会让 Host **暂缓回收**这页，不会导致数据损坏。性能优化，容忍短暂时不一致。

但 `invalidate_range_start` **必须 flush TLB**——因为要删除整个 S2 PTE，如果 Guest CPU 的 TLB 里还缓存着旧映射，Guest 可能继续访问已经不存在的物理页。

### 9.2 三层 dirty 位的关系

```
Layer 1: Guest S1 PTE dirty
  → 由 Guest 硬件 DBM 或 Guest 软件设置
  → Guest 回收时迁移到 Guest folio PG_dirty
  → Host 看不到

Layer 2: Host S1 PTE dirty
  → QEMU 进程的 PTE，由 Host 硬件 DBM 设置
  → Host 回收时迁移到 Host folio PG_dirty
  → Host swap 决策依据

Layer 3: KVM dirty_bitmap
  → KVM 在 user_mem_abort / mark_page_dirty 时设置
  → 用于 VM 迁移（live migration）的脏页追踪
  → 与 swap 无关，但 kvm_set_pfn_dirty() 也会设 Host PG_dirty
```

### 9.3 zram 作为 Host swap 的特殊行为

如果 Host 用 zram（内存压缩）做 swap 设备：

```
Host swap-out:
  → swap_write(folio)
    → zram_write_entry()
    → 压缩页面内容，存到 zram pool（还在内存里）
    → 释放原 folio

Guest fault-back-in:
  → user_mem_abort() → gfn_to_pfn → Host page fault
  → do_swap_page() → zram_read_entry()
  → 解压数据到新 folio → 重建 S1 PTE
  → KVM 重建 S2 PTE
```

**zram 的效果**：Host 看起来在做 swap，但实际上是压缩+在内存里换个位置。对 Guest 完全透明，但减少了 Host 的实际内存使用量。

### 9.4 KVM 的 mmu_invalidate_seq 防竞态

```c
// arch/arm64/kvm/mmu.c:1600 — user_mem_abort()
mmu_seq = vcpu->kvm->mmu_invalidate_seq;
// ... 做 gfn_to_pfn ...
// 之后检查:
if (mmu_seq != vcpu->kvm->mmu_invalidate_seq) {
    // 在我做 gfn_to_pfn 期间，有人发了 invalidate
    // → 我拿到的 pfn 可能已经过时
    // → 放弃，重来 (return to guest, 让它再次 fault)
}
```

这保证了 **gfn_to_pfn 和 S2 map 之间不会有并发的 invalidate**——如果有，就丢弃本次结果让 Guest 再 fault 一次。

---

## 10. 总结

### 10.1 职责分层

```
┌──────────────┬──────────────────────────┬─────────────────────────┐
│              │  做什么                    │  怎么做                  │
├──────────────┼──────────────────────────┼─────────────────────────┤
│ Guest OS     │  自己的 LRU 回收           │  独立的 vmscan + swap    │
│              │  自己的 swap I/O          │  走 virtio-blk           │
│              │  不通知 Host              │                          │
├──────────────┼──────────────────────────┼─────────────────────────┤
│ KVM          │  S2 页表管理               │  mmu_notifier 回调        │
│              │  S2 unmap (被 Host 通知)   │  kvm_pgtable_stage2_*   │
│              │  S2 map (被 Guest 触发)    │  user_mem_abort()        │
│              │  dirty_bitmap (迁移用)     │  mark_page_dirty()       │
│              │  S2 young bit 管理         │  kvm_age_gfn()           │
├──────────────┼──────────────────────────┼─────────────────────────┤
│ Host kernel   │  Host LRU 回收            │  vmscan + swap           │
│              │  Host S1 PTE 管理          │  rmap + try_to_unmap     │
│              │  swap I/O (磁盘/NVMe/zram) │  page_io.c               │
│              │  通过 mmu_notifier 通知 KVM │  invalidate_range_start  │
└──────────────┴──────────────────────────┴─────────────────────────┘
```

### 10.2 一句话总结

**Guest swap 是 Guest 内核自己的事，走 virtio-blk，Host 透明不感知；Host swap 会通过 mmu_notifier 拆除 KVM S2 映射，Guest 下次访问时 guest exit 触发 fault-back-in 从 Host swap 设备读回——两层 swap 独立运行，通过 S2 页表的存在/缺失隐式同步。**
