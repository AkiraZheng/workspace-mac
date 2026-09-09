# Stage-1 DBM 状态机：Stage-2 的标准答案库

> 定位：Leo 的 DBM 系列（合入本仓库 abf089b02d3c..96edd67e5e49）把 stage-2 带入三态世界后，
> `dbm_blindspots_and_risks.md`（下称"风险篇"）识别出 folio 记账、HA|HD、TLBI、VGA 悬崖等风险。
> 本文以 **Linux stage-1 的既有实现为参照系**：stage-1 在生产环境以"WC 模式"跑了多年，
> 我们缺的每个部件，stage-1 几乎都已备好样板。每节给出 stage-1 做法 → stage-2 差距 → 修复去向。

## 0. 两张表对照速览

### 0.1 位分配

| 位 | stage-1 描述符 | stage-2 描述符 |
|---|---|---|
| bit 7 | AP[2]，极性反（1=RO/干净，0=RW/脏） | S2AP[1]，极性正（1=可写/脏） |
| bit 10 | AF | AF |
| bit 51 | DBM（脏位修饰符） | DBM（同，Leo 引入） |
| **bit 55** | **PTE_DIRTY（软件脏缓存）** | KVM_PGTABLE_PROT_SW0（nested 层级 / pKVM 状态，见 §3.1） |

stage-1 的关键差异：**脏状态是双轨的**——硬件脏藏在 bit 7，软件脏存在 bit 55，`pte_dirty() = sw || hw`。
stage-2 只有单轨（S2AP_W），外加一份独立的外部记录（KVM dirty bitmap）。

### 0.2 三态对照

| 状态 | stage-1 (RDONLY, DBM) | stage-2 (S2AP_W, DBM) | 不懂 DBM 的 walker 眼中 |
|---|---|---|---|
| 不可写 | (1, 0) | (0, 0) | RO / 无访问（都读对） |
| 可写·干净 | **(1, 1)** | **(0, 1)** | **RO（都读错！）** |
| 可写·脏 | (0, 1) | (1, 1) | RW（都读对） |

注意两个"可写·干净"编码在各自描述符格式里都"长得像只读"——这就是共享表场景的坑源（风险篇 §5.1.1）。

## 1. 五件套：stage-1 的 pte 状态机

代码均在 `arch/arm64/include/asm/pgtable.h`（`PTE_DIRTY` 定义在 pgtable-prot.h:18）：

```c
#define pte_write(pte)		(!!(pte_val(pte) & PTE_WRITE))       /* PTE_WRITE == PTE_DBM (bit51) */
#define pte_hw_dirty(pte)	(pte_write(pte) && !pte_rdonly(pte)) /* 硬件脏 = RDONLY 清零 */
#define pte_dirty(pte)		(pte_sw_dirty(pte) || pte_hw_dirty(pte))  /* 双轨合一 */

static inline pte_t pte_mkwrite_novma(pte_t pte)     /* 建可写页 */
{
	pte = set_pte_bit(pte, __pgprot(PTE_WRITE));    /* 置 DBM —— 可写位就是 DBM */
	if (pte_sw_dirty(pte))
		pte = clear_pte_bit(pte, __pgprot(PTE_RDONLY));  /* 已脏 → 直接 dirty-writable */
	return pte;                                     /* 未脏 → 停在 clean-writable (=WC) */
}

static inline pte_t pte_mkdirty(pte_t pte)          /* 标脏（写 fault 兜底 / 软件标脏） */
{
	pte = set_pte_bit(pte, __pgprot(PTE_DIRTY));    /* 软件轨先记 */
	if (pte_write(pte))
		pte = clear_pte_bit(pte, __pgprot(PTE_RDONLY));  /* 硬件轨同步清 */
	return pte;
}

static inline pte_t pte_mkclean(pte_t pte)          /* 清脏（写回后） */
{
	pte = clear_pte_bit(pte, __pgprot(PTE_DIRTY));
	pte = set_pte_bit(pte, __pgprot(PTE_RDONLY));   /* 落回 clean-writable */
	return pte;
}

static inline pte_t pte_wrprotect(pte_t pte)        /* 收权 */
{
	if (pte_hw_dirty(pte))
		pte = set_pte_bit(pte, __pgprot(PTE_DIRTY));  /* ★ 先收割: hw 脏折算进 sw 脏 */
	pte = clear_pte_bit(pte, __pgprot(PTE_WRITE));
	pte = set_pte_bit(pte, __pgprot(PTE_RDONLY));
	return pte;
}
```

两个直接可借鉴的细节：

- **`pte_wrprotect` 的"先收割再收权"**：脏状态经软件位无损穿过权限收缩。stage-2 的
  `stage2_wrprotect_walker` 只清位不收割（WD→WC 时"它脏过"的信息就地蒸发）——风险篇 §7.1 的根因之一。
- **`pte_mkwrite` 未脏即停 WC**：stage-1 的 file 页在写回后常态处于 clean-writable，
  也就是说 **stage-1 常年运行在"WC 模式"**，HD=1 硬件免 fault 升脏，HD=0 靠写 fault 软件兜底（§2.1）。
  这证明三态 + 软件兜底的架构在大规模生产环境长期成立，Leo 的 stage-2 三态不是冒险。

## 2. 四条生命周期链

### 2.1 写 fault 软件兜底链（HD=0 / broken-DBM CPU 的活路）

```c
/* mm/memory.c, handle_pte_fault */
	if (vmf->flags & FAULT_FLAG_WRITE) {
		if (!pte_write(entry))
			return do_wp_page(vmf);       /* 真只读 → COW/mkwrite 流程 */
		entry = pte_mkdirty(entry);        /* ★ DBM=1 但 RDONLY=1: clean-writable */
	}                                        /*   软件 mkdirty 清 RDONLY 放行 + 标 sw 脏 */
```

对 clean-writable PTE 的写 fault（只有 HD=0 的 CPU 会产生），软件一行 `pte_mkdirty` 解决——
**这就是 stage-1 版的 relax_perms**。stage-2 的对应物（relax 置 DBM|S2AP_W + 写 fault 恒带 DIRTY）已等价，无差距。

### 2.2 读 fault 投机决策链

```c
/* mm/memory.c, finish_fault（:5712 附近） */
	if (write)
		entry = maybe_mkwrite(pte_mkdirty(entry), vma);   /* 写 fault: dirty-writable */
	else if (pte_write(entry) && folio_test_dirty(folio))
		entry = pte_mkdirty(entry);   /* ★ 读 fault 但 folio 本来就脏: 直接建 dirty */
	                                   /*   免掉下次写的 fault —— 投机 WD */
```

与 stage-2 `kvm_s2_fault_compute_prot` 的 DIRTY 决策思想一致（写已发生或没人接第一次写才给脏）。
差距在 VGA 场景（风险篇 §7.3）：stage-1 的投机判断是**动态**的（看 folio 实际脏否），
Leo 的是**静态能力**判断（`kvm_supports_hafdbs()`），HD 被全局关掉后仍建 WC → 每页一 fault。

### 2.3 写回清脏链（反向收割）

```
文件写回 (folio_writepage → writeback 完成)
  +-> folio_mkclean(folio)                    /* mm/rmap.c:1209 */
    +-> rmap_walk: 找到映射该 folio 的全部 VMA/PTE
      +-> page_mkclean_one()                  /* mm/rmap.c:1184 */
        +-> pte_mkclean + flush               /* 每个映射点清脏 (WD→WC 等价物) */
```

stage-1 有 rmap，能反向找到"谁映射了这页"。stage-2 无 rmap，反向清脏不存在；等价的正向操作是
dirty logging 的 wp（全量扫描），脏收割则交给 fault 标脏（bitmap）。此链无直接可搬的代码，
但概念上 HDBSS drain 是它的变体（从硬件 buffer 拿到"谁脏了"再正向处理）。

### 2.4 unmap 收割链（★ §7.1 长期修复的样板）

```c
/* mm/memory.c, zap_present_folio_ptes (:1774-1786) —— unmap/zap 时的标准动作 */
		ptent = get_and_clear_full_ptes(mm, addr, pte, nr, tlb->fullmm);
		if (pte_dirty(ptent)) {                 /* ★ 收割: PTE 脏位折算回 folio */
			folio_mark_dirty(folio);
			...
		}
		if (pte_young(ptent) && ...)
			folio_mark_accessed(folio);     /* AF 同理 */
```

**unmap 时读回 PTE 的脏位并 `folio_mark_dirty`**——这是 stage-1 对 folio 记账的兜底闭环：
无论脏位是谁置的（软件 mkdirty / 硬件 DBM 清 RDONLY），页表拆除时脏信息不丢。
stage-2 的 `stage2_unmap_walker` 只 `put_page`（页表页），对被映射页的 S2AP_W **不做任何收割**
——风险篇 §7.1（WC 页硬件免锁写脏 → host folio 永不标脏 → 回收丢数据）的正解就在这条链上：
**在 unmap walker 里读 S2AP_W → `kvm_set_page_dirty`**。实现草案见 `hdbss_v5_unmap_harvest.md`。

### 2.5 HD 使能链（★ §7.2/§7.5 的样板）

```c
/* arch/arm64/mm/proc.S, __cpu_setup —— 只开 HA，注释明说 HD 稍后 */
#ifdef CONFIG_ARM64_HW_AFDBM
	/*
	 * Enable hardware update of the Access Flags bit.
	 * Hardware dirty bit management is enabled later, via capabilities.
	 */
	mrs	x9, ID_AA64MMFR1_EL1
	ubfx	x9, x9, ID_AA64MMFR1_EL1_HAFDBS_SHIFT, #4
	cbz	x9, 1f
	orr	tcr, tcr, #TCR_EL1_HA
#endif

/* arch/arm64/kernel/cpufeature.c, cpu_enable_hw_dbm() —— 开 HD 的完整姿势 */
static inline void __cpu_enable_hw_dbm(void)
{
	u64 tcr = read_sysreg(tcr_el1) | TCR_EL1_HD;
	write_sysreg(tcr, tcr_el1);
	isb();
	local_flush_tlb_all();              /* ★ 翻 HD 必配 TLB 全刷 */
}
```

三个信息：① **HA 先于 HD 存在**（早期 HAFDBS 硬件可能只有 AF 更新）；② 开 HD **必配 TLBI**
（Leo 的 `kvm_set_hafdbs` 翻 VTCR.HD 只发 RELOAD 无 TLBI，风险篇 §7.5）；③ HD 由
`ARM64_HW_DBM` capability 延迟使能并带 broken-DBM erratum 排除（`has_hw_dbm` 查 cpuid + MIDR 黑名单）
——这个 cap 正是 `kvm_supports_hafdbs()` 检查的对象，erratum 排除 stage-2 已免费继承。

## 3. 八项对照总表（主体）

| # | stage-1 机制 | 位置 | stage-2 现状（Leo 系列） | 差距 | 修复去向 |
|---|---|---|---|---|---|
| 1 | 软件脏缓存 PTE_DIRTY(bit55)，`pte_dirty=sw\|\|hw` 双轨 | pgtable-prot.h:18, pgtable.h:174-176 | 无；脏只活在 S2AP_W + bitmap | 单轨 | **不搬**（见 §3.1 结论），bitmap 即外部记录 |
| 2 | `pte_wrprotect` 收权前先收割 hw 脏 → sw 脏 | pgtable.h:288-296 | `stage2_wrprotect_walker` 只清位 | 脏信息穿收权蒸发 | Leo 系列：wp 处可选加 folio 收割（过标安全） |
| 3 | `zap_present_folio_ptes`：unmap 收割 `pte_dirty → folio_mark_dirty` | mm/memory.c:1780 | `stage2_unmap_walker` 无收割 | **folio 记账缺口（风险篇 §7.1）** | **HDBSS v5：unmap 收割 S2AP_W**（见 C 文档） |
| 4 | 写 fault 对 clean-writable PTE 一行 `pte_mkdirty` 兜底 | mm/memory.c:6489 附近 | relax_perms 置 DBM\|S2AP_W，写 fault 恒带 DIRTY | 无 | 已等价 |
| 5 | 读 fault 投机决策：folio 已脏则直接建 dirty-writable | mm/memory.c:5716-5718 | compute_prot DIRTY 决策 | 判断是**静态能力**而非动态状态 | Leo 系列：改看 `vtcr & VTCR_EL2_HD` 动态位（§7.3） |
| 6 | `folio_mkclean` rmap 反向清脏 | mm/rmap.c:1209 | 无 rmap；正向 wp + bitmap | 结构性缺失 | HDBSS drain 是变体，无需 rmap |
| 7 | 开 HD 必配 TLBI；HA 先行 | cpufeature.c:1978-1988 | `kvm_set_hafdbs` 无 TLBI、不带 HA | **§7.2 + §7.5** | Leo 系列：`VTCR_EL2_HD\|VTCR_EL2_HA` + TLBI |
| 8 | broken-DBM erratum 排除 + capability 化 | cpufeature.c `has_hw_dbm` | `kvm_supports_hafdbs` 复用 ARM64_HW_DBM cap | 无 | 已免费继承 |

### 3.1 关于 #1：stage-2 要不要借 SW 位做软件脏缓存

事实：SW0/SW1（bit55/56）已被占用——nested 的 `KVM_NV_GUEST_MAP_SZ`（kvm_nested.h:248）与
pKVM 的 `PKVM_PAGE_STATE_PROT_MASK`（nvhe/memory.h:42）各用同两位（不同表，无直接冲突但语义已占）。
SW2（bit57）/SW3（bit58）全树无消费者，**位是有的**。

结论：**不值得借**。stage-1 需要 PTE_DIRTY 是因为它没有外部账本；stage-2 的 dirty bitmap 就是外部账本，
S2AP_W 的每次置位都有配对记录（软件 map/relax 时标 bitmap，硬件升脏时 HDBSS drain 记录）。
真正缺的不是"另一份脏记录"，而是把已有的 S2AP_W 脏**同步回 host folio**——那是 #3 的 unmap 收割，
不是新位。加 SW 缓存位只会引入三处状态同步（PTE/bitmap/SW 位）而无新收益。

## 4. 结论

1. **三态本身零风险**：stage-1 以 clean-writable 为常态跑了多年（HD=1 硬件升脏 / HD=0 软件兜底双模式都有生产验证），Leo 的 stage-2 改动在"编码"层面站在成熟范式上。
2. **stage-2 缺的是收割部件**：unmap 收割（#3）补 folio 记账闭环，动态投机（#5）补 VGA 场景，HD+TLBI+HA（#7）补开关正确性。三项都有 stage-1 现成样板，不是设计难题而是移植活。
3. **一项明确不搬**：SW 脏缓存位（#1）——bitmap 已是外部记录，加位是负收益（§3.1）。
