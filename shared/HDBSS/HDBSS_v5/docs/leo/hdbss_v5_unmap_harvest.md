# HDBSS v5 设计增补：unmap 脏收割与 drain 收割

> 背景：`dbm_blindspots_and_risks.md` §7.1（folio 记账缺口 → 回收静默丢数据）的长期修复。
> 样板：stage-1 `zap_present_folio_ptes()`（mm/memory.c:1780）——unmap 时读回 PTE 脏位
> `folio_mark_dirty(folio)`（机制详解见 `stage1_dbm_reference.md` §2.4）。
> 结论先行：**方案可行且改动局部化；SW 缓存位方案否决**（见 §3）。

## 1. 问题回顾：为什么必须做

Leo 系列合入后，host folio 的脏记账只发生在 fault 时刻（`kvm_release_faultin_page`）。
WC 页（HAFDBS 机器、非迁移、读 fault 建的）交出去时是 clean，之后硬件免锁升脏 KVM 无感知：

```
读 fault 建 WC → release clean → 硬件免锁写脏（HD=1）→ S2AP_W=1，无任何 VM exit
→ host MM 视角 folio 干净 → 内存压力回收 → 丢写（静默数据损坏）
```

短期修复（fault 时刻投机标脏，即 `kvm_release_faultin_page` 改用 `prot & PROT_W`）覆盖
"页生命周期内 folio 恒被标脏"的效果，但**多付一次 set_page_dirty 的代价且语义是猜的**；
长期正确做法与 stage-1 相同：**拆除映射时收割 PTE 上的脏位**。arm64 KVM 的 unmap 路径
（mmu-notifier、memslot 删除、VM 销毁都会走）今天对 S2AP_W 完全无视。

一个重要澄清（回应"不是有 bitmap 吗"）：KVM dirty bitmap 只在 logging 期有效，
且非迁移 VM（HAFDBS 场景的主战场）根本没有 bitmap。**host folio 的脏信息在 WC+HD=1 模式下
唯一的持久落点就是 PTE 的 S2AP_W**——不收割就丢。

### 1.1 各实现形态的 folio 缺口对照（回应"我们的 v5 不是没这个问题吗"）

关键背景：QEMU 默认 RAM 是**匿名页**，KVM fault-in 时的 GUP 引用在映射存续期间**阻塞
swap-out**（refcount 抬高，`shrink_folio_list` 放弃）——所以"fault-in 标过脏"的匿名页
中途不可能被写回清脏，脏位一直活到 unmap。file-backed（`memory-backend-file`）才有
"迁移中 writeback 清脏 → 后续 guest 写无感知 → teardown 丢弃"的窗口。

| 形态 | WC 页来源 | fault-in 标 folio | 窄/宽缺口 |
|---|---|---|---|
| 经典主线（pre-DBM） | 无（HD 恒 0，wp 后即 RO） | ✅ `writable = prot & PROT_W`（**我们 v5 的原写法**） | 仅 file-backed 非迁移期理论缺口（上游一直存在） |
| **我们的 v5**（非迁移 HD 全关） | 仅迁移期 wp 产物 | ✅ 同经典 | **窄**：迁移期 WC 升脏不重标，但 fault-in 已标 + 匿名页 GUP 引用保脏 → 常规安全；file-backed+迁移中 writeback 才触雷 |
| Leo 系列 F2 前（非迁移 HAFDBS 常开） | 非迁移读 fault + 迁移期读 fault | ❌ **patch 2 把 fault-in 标脏改成了 DIRTY 门控**——读 fault 的 WC 页从此不标 | **宽（Critical）**：匿名页也丢——fault-in 端和 fault 端**同时**被打断（fault-in 不标了 + WC 让写绕过 fault），swap-in 后的干净页被硬件写脏而 folio 永无人标 |
| code_v5_3_leo（F2 + harvest） | 上述全部 | ✅ F2 **还原** `prot & PROT_W`（拆账：folio 用 W，bitmap 用 DIRTY） | 闭环：fault-in 投机 + wp/unmap/drain 收割 |

两个结论：

1. **"非迁移 WC"场景是 Leo patch 5 开出来的，我们的 v5 原本没有**——我们非迁移 HD 全关，
   全是 WD，folio 在 fault-in 就标了。但 **rebase 到 Leo 之后这个场景就是我们的了**（R1
   状态机在非迁移开 HAFDBS），而 Leo patch 2 恰好在共享的 fault 路径上把标脏从 W 门控改成
   DIRTY 门控。F2 的本质不是"给 HDBSS 加新行为"，是**把被 patch 2 悄悄改掉的我们自己
   的原语义还原回来**（`kvm_s2_fault_map` 的 release 参数，v5/主线 = `prot & PROT_W`）。
2. **我们的 v5 也并非零缺口**：迁移期 WC 升脏的页，folio 依赖 fault-in 时的旧标记活着；
   file-backed 页若在迁移中被 host writeback 清脏，后续 guest 写直到 teardown 前无人重标。
   经典 KVM 迁移期靠"每次写都 fault 重标"兜着，我们的 v5 把这条兜底去掉了（这正是免 fault
   的代价）。所以 wp/unmap 收割对 HDBSS 模式同样有意义。

### 1.2 drain 收割的冗余性分析（诚实结论）

枚举 WD 状态的所有出口，验证 F2 + wp 收割 + unmap 收割是否已构成完整闭环：

| WD 的出口 | 收割点 | 覆盖 |
|---|---|---|
| unmap/teardown（mmu-notifier、memslot 删除、VM 销毁） | `stage2_unmap_walker` 收割 | ✅ |
| wp（CLEAR 的 WD→WC，含未 drain 的 entry 场景） | `stage2_wrprotect_walker` 收割 | ✅ |
| 迁移期 epoch 内二次写（PTE 已 WD，无新 entry，folio 可能被 writeback 清过） | 下一次 CLEAR 的 wp 收割 / teardown 的 unmap 收割 | ✅ |
| 非迁移 HAFDBS 升脏（无 drain、无 fault） | wp（迁移开始）/ unmap（teardown）收割 | ✅ |

**结论：给定 F2 + wp + unmap 收割，drain 收割在正确性上是冗余的**——WD 的每个出口都有
更靠后的兜底。它的真实价值只剩：① 账本对称（每个 HDBSS entry 同时落 bitmap 和 folio，
不变式好陈述）；② 防御未枚举路径。代价是改了 flush 路径并引入 mmu 读锁。

**决策（已执行）：撤掉 drain 收割**（code_v5_3_leo，commit 8fc9342022ca）。flush 回到纯
SRCU 原设计；folio 账本 = "fault-in 投机（F2）+ wp/unmap 精确收割"，恰与 stage-1 的
`pte_mkdirty` + zap 收割同构。`kvm_s2_mark_page_dirty` 移至 mmu.c 作 `kvm_s2_mm_ops`
的 static 回调实现，drain 的 SRCU-only 设计不动。

## 2. 方案：stage2_unmap_walker 收割 S2AP_W

### 2.1 关键约束：pgtable.c 双编译

`arch/arm64/kvm/hyp/pgtable.c` 同源编进 host 内核与 nVHE hyp 镜像。`pfn_to_page`/`SetPageDirty`
是 host-only API，且 **pKVM host stage-2 的 unmap 也走同一个 walker**（hyp 侧 `__pkvm_host_unshare`
等），hyp 里既不能也不该碰 host 的 folio 标志。

解法（与 `dcache_clean_inval_poc` 等 op 同构）：**经 `struct kvm_pgtable_mm_ops` 加回调**，
只给 guest S2 的 pgt 接线，其余 pgt（pKVM host S2）留 NULL：

```c
/* arch/arm64/include/asm/kvm_pgtable.h */
struct kvm_pgtable_mm_ops {
	...
	void		(*dcache_clean_inval_poc)(void *addr, size_t size);
	void		(*icache_inval_pou)(void *addr, size_t size);
+	void		(*mark_harvested_page_dirty)(kvm_pfn_t pfn);   /* 新增 */
};
```

### 2.2 walker 侧改动

`stage2_unmap_walker` 的 leaf 分支（`kvm_pte_valid(ctx->old)` 且非 table），
在 `stage2_unmap_put_pte()` **之前**收割：

```c
/* arch/arm64/kvm/hyp/pgtable.c, stage2_unmap_walker() leaf 分支 */
	if (kvm_pte_valid(ctx->old) && !kvm_pte_table(ctx->old, ctx->level)) {
		/* Harvest the stage-2 dirty bit into the host folio before
		 * tearing the mapping down, mirroring zap_present_folio_ptes().
		 * S2AP_W may have been set by hardware (HAFDBS) without KVM
		 * ever seeing a write fault.
		 */
		if ((ctx->old & KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W) &&
		    ctx->mm_ops->mark_harvested_page_dirty)
			ctx->mm_ops->mark_harvested_page_dirty(
				kvm_pte_to_phys(ctx->old) >> PAGE_SHIFT);
	}
```

注：无 DBM 系列的旧世界此改动也成立（S2AP_W 就是"被写过"），但它不是必须——
若要缩小 v5 系列的影响面，可以加 `IS_ENABLED(CONFIG...)` 或干脆只在 Leo 系列之后存在。

### 2.3 host 侧实现（只接 guest pgt）

```c
/* arch/arm64/kvm/mmu.c —— kvm_pgtable_stage2_init 的 mm_ops 赋值处（guest 专用） */
static void kvm_mark_harvested_page_dirty(kvm_pfn_t pfn)
{
	struct page *page;

	/* pfn_to_page 只对正常内存合法：ioremap/PFNMAP 的 pfn 不受 PageDirty 体系管理 */
	if (!pfn_valid(pfn))
		return;

	page = pfn_to_page(pfn);
	if (kvm_is_ad_tracked_page(page))   /* 复用现有 gate（PG_reserved 不动） */
		kvm_set_page_dirty(page);
}
```

三个安全性论据：

1. **锁序合法**：unmap 在 `kvm->mmu_lock` 写锁下，`kvm_release_faultin_page` 的
   lockdep 注释已确认"folio 在 mmu_lock 内标脏"是既有契约（防与 writeback 竞态）。
2. **过标安全**：收割只在 `SetPageDirty`（幂等、导致一次多余回写），不做 put_page 等
   引用操作，对 gmem/ioremap/pKVM 无副作用（后者根本没接这个 op）。
3. **粒度**：block 映射的收割语义是"整块脏"——stage-1 对大页 zap 同样整页标脏，
   `folio_mark_dirty` 按 folio 而非按 PTE，天然一致。

### 2.4 调用链覆盖面（改一处，全链收）

```
mmu-notifier invalidate:  kvm_mmu_invalidate_end → kvm_unmap_gfn_range (mmu.c:2443)
memslot 删除 / VM 销毁:   kvm_mmu_zap_memslot / kvm_free_stage2_pgd
嵌套影子表回收:           kvm_nested_s2_unmap（walk 的是 shadow pgt，同一 walker）
  全部 → kvm_pgtable_stage2_unmap → stage2_unmap_walker ← 收割点（唯一）
```

## 3. SW 缓存位方案：否决

（完整论证见 `stage1_dbm_reference.md` §3.1）要点：

- 位是有的（SW2/SW3 无消费者；SW0/SW1 被 nested `KVM_NV_GUEST_MAP_SZ` 与 pKVM
  `PKVM_PAGE_STATE_PROT_MASK` 各自占用）；
- 但 stage-1 需要 `PTE_DIRTY` 是因为没有外部账本；stage-2 的 dirty bitmap 就是外部账本，
  S2AP_W 的每次置位都有配对记录（软件 map/relax 标 bitmap；硬件升脏由 HDBSS drain 记）；
- folio 记账缺口（§1）缺的是"把 S2AP_W 同步回 folio"的动作（§2 的收割），不是"另一份记录"；
- 引入 SW 脏位 = 三处状态同步（PTE/bitmap/SW），负收益。

## 4. HDBSS drain：不做 folio 收割（设计决策）

drain 处理器保持 v5 原设计——只标 bitmap，纯 SRCU，不碰页表也不碰 folio。

**曾实现过 drain 侧收割**（kvm_pgtable_get_leaf 反查 PTE → SetPageDirty，需加 mmu 读锁），
后经 §1.2 的冗余性分析**撤除**：给定 F2（fault-in 投机）+ wp/unmap 收割，WD 的每个出口
都有兜底，drain 收割对正确性无独立贡献，唯一代价是给 flush 引入 mmu 锁（stage-2 表页
经 put_page 直接进 buddy、不走 call_rcu，RCU-only walk 不安全，须读锁排除结构性写者）。
撤除后该锁问题随之消失。

**保留的分析记录**（若将来重新考虑 drain 收割，这两条约束仍然成立）：

1. **stage-2 walk 的表页安全**：HDBSS entry 只有 IPA，定位 folio 必须反查 PTE。链接态表页
   经 `kvm_s2_put_page()` → `put_page()` 直接进 buddy（不走 call_rcu——只有 eager split 的
   unlinked 表走 call_rcu，见 mmu.c:246；nVHE 完全禁止共享 walk，注释明说 "due to the
   lack of RCU"）。RCU-only walk 可能跟进已释放表页，从垃圾 PTE 收割出随机 folio。
2. **SetPageDirty 的既有契约**：`kvm_release_faultin_page` 注释明说 "folios can't be
   safely marked dirty outside of mmu_lock as doing so could race with writeback"。

## 5. 实施清单（已落地于 code_v5_3_leo）

| patch | 内容 | 状态 |
|---|---|---|
| F2 | fault-in 投机标脏（`prot & PROT_W`，拆账） | ✅ a7947d2ff031 |
| harvest | mm_ops 回调 + unmap/wp 两点收割（`kvm_s2_mark_page_dirty` 为 mmu.c static） | ✅ 8fc9342022ca |
| ~~drain 收割~~ | ~~`kvm_flush_hdbss_buffer` 加读锁 + PTE 反查~~ | ❌ 冗余，撤除（§1.2） |

harvest 的正确性不依赖 HDBSS：HAFDBS-only（无 HDBSS buffer）的机器上，HD=1 的 WC 页
硬件升脏后**只有** wp/unmap 收割能救 folio 记账——这是 Leo patch 5 开出来的新状态，
v5 应当把它补全。
