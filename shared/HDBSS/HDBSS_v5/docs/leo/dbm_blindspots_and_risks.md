# Leo DBM 系列：盲区补全与风险清单

> 分析对象：Leonardo Bras `[RFC 0/5] KVM: arm64: New PTE dirty-page encoding, HAFDBS new usage`（2026-09-01）
> 合入状态：已合入当前仓库（基线 a500db7819c5 之上）：
>
> | # | commit | 主题 |
> |---|---|---|
> | 1 | abf089b02d3c | pgtables: Change write bit from S2AP_W to DBM |
> | 2 | cc87c84b71bb | Add KVM_PGTABLE_PROT_DIRTY |
> | 3 | 14ef2b2dba5a | Introduce a dedicated walker for stage2 write-protect |
> | 4 | 6ddad18d396a | Add KVM_REQ_RELOAD_STAGE2 |
> | 5 | 96edd67e5e49 | Enable HAFDBS for guests not on migration |
>
> 本文定位：以 **Leo 的 patch 为主线**的全景分析。系列横跨 9 个文件：主链改动（编码/解码器、PERMS 掩码、wrprotect walker、HAFDBS 开关）之外，还动到了**嵌套虚拟化（nested.c）、设备页/ioremap、gmem、pKVM/hyp（PROT_RW 家族）** 四块——每处 diff 只有几行，背后却各牵一段深层子系统背景（嵌套下三张 S2 表的关系、设备页为何恒 WD、PROT_RW 为何必须补 DIRTY）。本文把这四块逐一吃透，并分析 **SMMU 侧影响**，汇总 **sashiko 暴露的问题与修复方案**，最后给出与 HDBSS v5 的 rebase 冲突清单和疑问快答表。

## 0. 前置速览：三态模型与两个关键事实

### 0.1 三态模型（引自本仓库 commit db21f07bc10a，与 Leo 终态一致）

| 状态 | DBM (bit51) | S2AP[1] (bit7) | 写访问的命运 |
|---|---|---|---|
| N（不可写） | 0 | 0 | Permission Fault |
| WC（可写·干净） | 1 | 0 | HD=1：硬件免 fault 放行写并升 S2AP[1]（WC→WD）；HD=0：**等同 RO，写 Permission Fault** |
| WD（可写·脏） | 1 | 1 | 畅通 |

架构出处（FEAT_HAFDBS，Armv8.1）：VTCR_EL2.HD=1 时，DBM=1 且 S2AP[1]=0 的描述符是 writable-clean，写由硬件执行并把描述符提升为 writable-dirty，不触发 Permission fault。**DBM 在 HD=0 时是惰性的：权限检查只看 S2AP**。——这句话是本系列全部正确性的支点，也是第 6、7 节所有风险的来源。

（DBM=0 且 S2AP[1]=1 的组合，即旧编码的"传统 RW"，本系列任何路径都不会产出；但**别人建的表**可能有，见第 1 节嵌套。）

### 0.2 软件枚举与 PTE 位的新契约

```
KVM_PGTABLE_PROT_W      <-> PTE DBM (bit 51)     （可写）
KVM_PGTABLE_PROT_DIRTY  <-> PTE S2AP_W (bit 7)   （脏）
```

- 编码器 `stage2_set_prot_attr()`：`W → DBM`，`W 且 DIRTY → 再加 S2AP_W`
- 解码器 `kvm_pgtable_stage2_pte_prot()`：`DBM → W`，`DBM 且 S2AP_W → DIRTY`
- **"两种脏"必须区分**：PTE 的 S2AP_W（硬件脏）之下还有两层软件记账——
  - **host folio dirty**（`SetPageDirty`，供 Linux MM 回收/写回判断，**允许过标**）
  - **KVM dirty bitmap**（`mark_page_dirty_in_slot`，供迁移增量拷贝，**必须精确**）
  - Leo patch 2 把两个记账都挂在 `prot & KVM_PGTABLE_PROT_DIRTY` 上——bitmap 那半是对的，folio 那半埋了本系列最重的一颗雷（§7.1）。

### 0.3 folio 五分钟入门：为什么 KVM 要关心 host 的页结构

**folio 是什么**：`struct page` 是 host 内核对每个 4K 物理页的元数据（flags、refcount、lru...）；
`struct folio` 是它的封装——"一个页，或一组复合页（THP 大页）的统一句柄"，2021 年由 Matthew
Wilcox 引入，目的只是让代码诚实面对"这个 page 可能是大页的尾页"。对本文而言只需记住一件事：

> **folio 是 host MM（回收/写回/swap）记账的单位。`SetPageDirty(folio)` 是告诉 host
> "这页内容变了，回收前必须写回" 的唯一通道。**

**为什么 guest 的写需要这个通道**：guest 写在物理上落在 host 的页上（GPA→HPA 翻译后的
真实内存）。这些页归 host MM 管：内存压力下回收，anon 页 swap out、file 页写回。回收判定
就一句话——**folio 干净 ⇒ 内容与后备存储一致 ⇒ 直接丢弃；folio 脏 ⇒ 先写回再丢**。

**CPU 正常进程的脏信息怎么流动**（stage-1 那套机制存在的理由）：

```
进程写 → S1 PTE 硬件置 dirty → unmap/zap 时收割: zap_present_folio_ptes()
  if (pte_dirty(ptent)) folio_mark_dirty(folio)   ← PTE 脏位活着走到 unmap, 折算回 folio
→ 回收看到 folio 脏 → 写回 → 丢页, 数据无损
```

**经典 KVM 为什么免费获得这一切**：经典流程每个 guest 写都 fault 到 KVM（wp 收权制造
fault），fault 处理器里 `kvm_release_faultin_page(dirty)` → `SetPageDirty`。写可见性是
fault 顺带的，所以 arm64 KVM 的 unmap 从来不需要收割 S2 脏位——**没有任何脏状态能绕过
fault 落到 S2 PTE 上**。

**硬件脏跟踪（HD=1）打破了这条免费通道**：WC→WD 由硬件做，零 VM exit，KVM 对这次写
完全无感知。一个具体的静默丢数据场景（sashiko Critical 的场景）：

```
1. host 页曾被 swap out 又 swap in → folio 此刻是"干净"的（内容与 swap slot 旧内容一致）
2. guest 读 fault → KVM 建 WC → release clean（F2 修复前的代码: 读 fault 不标 folio）
3. guest 写 WC 页 → 硬件免 fault 升 WD（KVM 无感知, folio 无人标脏）
4. 内存压力 → host 回收: folio 干净 + swap slot 有"旧"内容 → 直接丢页, 不写回
5. guest 再次访问 → swap in 回来的是旧数据 → 静默数据损坏
```

所以 bugfix 不是"突然关心 folio"，而是：**硬件把 KVM 从写路径上摘掉之后，folio dirty
成了 host MM 得知 guest 写的唯一渠道，这条记账必须有人补**。对应修复：

| 修复 | 语义 | 位置 |
|---|---|---|
| F2（投机） | 凡是映射可写的页，fault 时就标 folio 脏——过标安全（多一次回写而已），x86 同款契约 | `kvm_release_faultin_page` 改用 `prot & PROT_W` |
| Harvest（精确） | S2AP_W 位是硬件写的**唯一物证**：wp（清位前）、unmap（拆映射前）两处把它折算回 folio；drain 侧经冗余性分析放弃（F2+wp+unmap 已闭环，见 `hdbss_v5_unmap_harvest.md` §1.2） | `stage2_wrprotect_walker` / `stage2_unmap_walker` |

（file-backed 页同理且更凶：folio 脏与文件系统状态不一致会触发 ext4 BUG 一类的错误，
`pkvm_mem_abort` 拒绝 page-cache 页的注释就是在防这个。）

### 0.3.1 一个 folio，两扇门（澄清"folio 是不是靠 S1 标脏"）

PG_dirty 是**物理页自己的标志位，不属于任何页表**。QEMU 的一页 guest RAM 同时被两个 PTE
指向，分属两张表——写入有两条独立路径，标脏义务按"写从哪扇门进来"分配：

```
                host 物理页（struct folio，PG_dirty 在这）
                      ▲                        ▲
                      │                        │
        门 A: host S1 PTE              门 B: KVM S2 PTE
        （QEMU 用户态 HVA→HPA）         （guest GPA→HPA）
        ────────────────────           ────────────────────
        谁写: QEMU 自己                 谁写: guest CPU（写自己的内存）
        记录: VMA/rmap ✓               记录: 无 ✗（不在 rmap，mm 不 walk S2）
        记账人: mm 全责                 记账人: KVM 全责
```

- **门 A 的账 mm 全责**：mm 的 pte_wrprotect/mkclean/zap 本来就在遍历这张表（rmap 指路），
  S1 的硬件 DBM 位有人原生收割。KVM 零义务。
- **门 B 的账 KVM 全责**：guest CPU 的写经 GVA→(guest S1)→GPA→(**S2**)→HPA，最终落进
  host 物理页的那一步是 S2 PTE；mm 对它失明，只能 KVM 标。"S1 有原生收割器、S2 没有"
  比的是**两张表里各一个 bit 51 的命运**（host S1 的 PTE_WRITE==DBM 与 KVM S2 的 DBM
  是不同表里的不同位）：mm 收前者，KVM 必须自己收后者（= harvest patch，S2 版的
  zap_present_folio_ptes）。

**写回编舞**（两扇门如何一起关，维持不变量"S2 PTE 存在 ⇒ 后续写必被记账"）：

```
mm 写回 file-backed folio: folio_mkclean → rmap walk
  1. rmap 只找到门 A 的 S1 PTE → pte_wrprotect + pte_mkclean (rmap.c:1139)
     —— QEMU 再写走 S1 fault
  2. 每处理一个 PTE 发射 MMU_NOTIFY_PROTECTION_PAGE (rmap.c:1118)
  3. KVM notifier 收到 → kvm_mmu_unmap_gfn_range (kvm_main.c:729)
     —— 把该范围 S2 PTE 拆掉，门 B 也关了
  4. guest 再写 → S2 缺页 → fault 路径 SetPageDirty 重新标脏
```

门 A mm 自己关；门 B 靠 notifier 逼 KVM 关——mm 原生机制只认识门 A，门 B 是 KVM 打的补丁。
ext4 教训（cc5095747edf，mmu.c:1740-1753 注释）的根因正是门 B 游离在 rmap 之外：mkclean
失明 → mm 认为 folio 干净而 guest 持续写 → KVM unpin 时补标又与 fs 时序错位 → BUG。
**DBM/HAFDBS/HDBSS 动的全是门 B**：经典方案门 B 每写必 fault（记账免费），硬件接管后
写静默通过（记账改收割 S2AP_W）——F2/harvest 就是把门 B 的账本逻辑重新对齐。

---

## 1. 嵌套虚拟化（nested）

### 1.1 背景知识：嵌套下其实有三张 stage-2 表

| 表 | 谁建 | 谁走查 | 格式 |
|---|---|---|---|
| L0 为 L1 建的 S2 | L0（host 内核） | 硬件（L1 运行时的 IPA 翻译） | L0 的编码，patch 后 = DBM 编码 |
| **L1 为 L2 建的 S2** | L1（guest 内核里的 KVM） | **L0 软件**（`walk_nested_s2_pgd`） | L1 自己决定，L0 无法控制！ |
| L0 为 L2 建的影子 S2 | L0 | 硬件（L2 运行时） | L0 的编码 |

Leo 唯一动到的嵌套代码是第二张表的读法：

```c
/* arch/arm64/kvm/nested.c, walk_nested_s2_pgd() */
	out->readable = desc & KVM_PTE_LEAF_ATTR_LO_S2_S2AP_R;
	/* Takes care of both RO/RW and RO/WC/WD encodings */
	out->writable = desc & (KVM_PTE_LEAF_ATTR_HI_S2_DBM |
				KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W);
```

`out->writable` 的消费链（影子表权限 = L1 表与 L0 表的交集）：

```
kvm_handle_guest_abort()
  +-> kvm_walk_nested_s2()                 /* 软件走 L1 的表 */
    +-> walk_nested_s2_pgd()               /* writable = DBM | S2AP_W 联合判断 */
  +-> user_mem_abort()
    +-> kvm_s2_fault_compute_prot()        /* 先按 L0 事实源算 prot */
    +-> adjust_nested_fault_perms()        /* L1 表不可写则摘掉 W|DIRTY */
        prot &= ~(KVM_PGTABLE_PROT_W | KVM_PGTABLE_PROT_DIRTY);
    +-> map / relax                        /* 影子表落位 */
```

### 1.2 Leo 的意图：兼容 L1 也用新编码

设想 L1 里跑的内核**同样合入了这套系列**（L1 的 KVM 建表也用 DBM 编码）：

- L1 建的 WC 页 = (DBM=1, S2AP_W=0)。若 L0 只看 S2AP_W，会误判只读 → 影子表无 W → L2 的每次写都注回 L1（`kvm_s2_handle_perm_fault` 的 forward_fault），L1 的 relax 再放行——功能不坏，但 L1 精心构造的 WC 语义在 L2 层面完全失效，性能塌方。
- 联合判断 `DBM | S2AP_W` 同时认两种编码：传统 RW (0,1) 与新 WC/WD (1,x)。

这就是注释 "Takes care of both RO/RW and RO/WC/WD encodings" 的意思。**它改的不是"L0 要不要给 L2 用 DBM"，而是"L0 怎么解读 L1 的表"**——L0 影子表本身仍是 L0 编码。

### 1.3 sashiko 指出的安全漏洞（High）：bit 51 的身份不明

L0 通过 ID 寄存器陷阱把 L1 可见的 HAFDBS 能力**限制为 AF-only**：

```c
/* arch/arm64/kvm/nested.c:1783 */
	val = ID_REG_LIMIT_FIELD_ENUM(val, ID_AA64MMFR1_EL1, HAFDBS, AF);
```

也就是说 L1 规格上"被告知"：硬件不支持 stage-2 dirty 更新。后果链：

1. **bit 51 对 L1 是 RES0**。一个诚实的 L1 内核可能把它当普通 RES0 位，甚至挪作软件用途（RES0 = "应写 0"，但 L1 是 guest，L0 不能信任它写 0）。
2. L1 若在 bit 51 上放了 1（软件标记），且该描述符 S2AP_W=0（L1 本意只读）：
3. L0 联合判断读出 `writable = 1` → 影子表给 W → **L2 可以写穿 L1 设定的只读页**（典型如共享固件区），L1→L2 安全边界被击穿。
4. 附带伤害：L2 的写不再 fault 到 L1，L1 自己若在做 dirty logging 则跟踪失效。

Leo 的回复："for this to work on NV we need Oliver's patch series enabling HAFDBS emulation"——即这个改动的正确性**前置依赖一个尚未合入的嵌套 HAFDBS 模拟系列**（L0 模拟 L1 的 VTCR_EL2.HD，包括在 L1 表上代硬件做 WC→WD 提升与脏报告）。模拟系列落地后，"L1 的 bit 51 是不是 DBM"有了权威来源（L1 是否真的设了 VTCR.HD），L0 的解读才有依据。

### 1.4 结论与修复方向

- **当前形态下这行是超前且带安全洞的**：`kvm_supports_hafdbs()` 的 `!kvm_vcpu_has_nv(kvm)` 只保证 L0 不给嵌套 VM 开 HD、不建 WC 影子页，但**不保护 walk 的联合判断**——后者对任何嵌套 guest 都生效，与 gate 无关。
- 短期修复（若 Oliver 系列未到）：revert 成只看 S2AP_W。代价只是"L1 用新编码时 WC 被误判只读"的性能回退（写 fault 多注回一层，安全无损）。
- 正确修复（配合模拟系列）：判断 gate 在 "L1 的虚拟 VTCR_EL2.HD == 1" 上——只有 L1 明确启用了 S2 DBM 管理，bit 51 才是 DBM，否则按 RES0 忽略。
- **回答"L2 虚机要不要考虑 DBM / HDBSS 支不支持 L2"**：L0 侧整套 HD/HAFDBS/HDBSS 都被 `!kvm_vcpu_has_nv(kvm)` 排除，**本系列（以及当前 HDBSS v5）都不覆盖 L2 虚机**。walk 的联合判断只是"读懂 L1 的表"的前向兼容，不是 L2 使能。嵌套要吃到 DBM/HDBSS 红利，依赖：① 嵌套 HAFDBS 模拟系列；② 影子表fault路径对 WC/HD 的完整处理（含 §7 的全部风险在嵌套下的变体）。

---

## 2. 设备页：device 与 ioremap

### 2.1 两个入口

| 入口 | 触发者 | 页来源 | prot |
|---|---|---|---|
| `user_mem_abort` 的 `s2vi->device` | guest fault | VMA 带 `VM_PFNMAP/VM_MIXEDMAP` 且 pfn 不在正常内存（VFIO BAR 直通等） | compute_prot 现算 |
| `kvm_phys_addr_ioremap` | VMM ioctl（VGIC 等内核模拟设备） | 传入的物理地址 | 常量拼装 |

两处 Leo 的改法完全一致——**W 和 DIRTY 一起给，落表恒 WD**：

```c
/* arch/arm64/kvm/mmu.c, kvm_phys_addr_ioremap() */
	enum kvm_pgtable_prot prot = KVM_PGTABLE_PROT_DEVICE |
				     KVM_PGTABLE_PROT_R |
				     (writable ?
				      (KVM_PGTABLE_PROT_W | KVM_PGTABLE_PROT_DIRTY) :
				      0);

/* arch/arm64/kvm/mmu.c, kvm_s2_fault_compute_prot() */
	if (s2vi->map_writable) {
		*prot |= KVM_PGTABLE_PROT_W;
		if (s2vi->device || ... )          /* device 恒给 DIRTY */
			*prot |= KVM_PGTABLE_PROT_DIRTY;
	}
```

### 2.2 为什么设备页必须 WD（回答"是不是因为 SMMU 没有 DBM？"）

**不是因为 SMMU**——SMMU 根本不走 KVM 的 stage-2 表（详见 §6），设备页的写者是 **guest CPU 的 MMIO 访问**，走的还是 CPU 的 stage-2 walk。真正的理由有三条：

1. **设备页不参与脏跟踪**：`kvm_arch_prepare_memory_region()` 对 `VM_PFNMAP` + `KVM_MEM_LOG_DIRTY_PAGES` 直接 `-EINVAL` 拒绝。既然永远没有"让写 fault 出来标脏"的需求，就没有任何理由 withheld DIRTY（建 WC）。
2. **WC 对设备页收益为零**：WC 的唯一价值是"硬件按需升脏，只有真写过的页进脏集"——设备页的脏位没人收割，收益不存在。
3. **WC 的代价对设备页是真实的**：只要 HD=0（任一**其他** memslot 在 logging、或系统不支持 HAFDBS、或嵌套/nVHE），WC 就等同 RO，每个设备页首次写多一次 Permission Fault。MMIO 写虽然架构上可安全重放（fault 时写尚未发生），但纯属浪费。

结论：`W|DIRTY` 一起加 = 保持旧行为（恒 RW）的最小改动。这也顺便回答了"为什么有些地方两个 flag 一起加、有些单独加"——**规则是统一的**：

> 单独加 W（建 WC）的唯一场景：**HAFDBS 机器、非迁移、非 device 的普通 RAM 读 fault**——因为"第一次写有人接"（硬件接）。其余一切可写场景都是 `W|DIRTY` 一起给：要么写已发生（写 fault），要么没人接（device、不支持 HAFDBS、HD 被全局关掉但 compute 还在按静态能力判断——见 §7.3 的坑）。

---

## 3. gmem_abort：guest_memfd

### 3.1 gmem 是什么

guest_memfd 是机密虚拟化（CoCo）的私有内存后端：GPA **不对应 host 用户态 HVA**，页从 `kvm_gmem_get_pfn()` 拿，host 用户态（QEMU）看不到内容。因此权限事实源比普通内存简化——**没有 GUP/VMA 两层查证，只看 memslot 的 `KVM_MEM_READONLY`**：

```c
/* arch/arm64/kvm/mmu.c, gmem_abort() */
	if (!(s2fd->memslot->flags & KVM_MEM_READONLY))
		prot |= KVM_PGTABLE_PROT_W | KVM_PGTABLE_PROT_DIRTY;   /* 恒 WD */

	if (s2fd->nested)
		prot = adjust_nested_fault_perms(s2fd->nested, prot);  /* 嵌套: L1 表说不行就摘 */
```

后续与 user_mem_abort 同构：perm fault 走 `kvm_pgtable_stage2_relax_perms`，缺页走 `kvm_pgtable_stage2_map`，收尾同样改成 DIRTY 门控：

```c
	kvm_release_faultin_page(kvm, page, !!ret, prot & KVM_PGTABLE_PROT_DIRTY);
	if ((prot & KVM_PGTABLE_PROT_DIRTY) && !ret)
		mark_page_dirty_in_slot(kvm, s2fd->memslot, gfn);
```

### 3.2 分析

- **行为与旧版完全一致**：gmem 的 prot 从不产生 WC（`W|DIRTY` 恒成对），落表恒 WD。改动只是"旧 W 的语义在新编码下需要 DIRTY 补齐"的机械翻译。
- **不受 §7.1 folio 脏记账风险影响**：正因为 gmem 恒 WD，`prot & PROT_DIRTY` 恒真（除非 nested 摘掉，而摘掉时本来就不可写），`kvm_release_faultin_page` 恒走 dirty 分支，folio 记账不缺。gmem 的 folio 是 guest_memfd 的页，host 侧回收入口（punch hole 等）同样依赖 dirty 标记。
- **为什么 gmem 不做 WC 化**：gmem 的共享/私有转换走 `KVM_SET_MEMORY_ATTRIBUTES`，脏跟踪语义由 CoCo 迁移方案另行设计；在 HAFDBS 机器上把 gmem 读 fault 建成 WC 理论可行（写由硬件升脏），但没有任何消费者，徒增 HD=0 时的 fault。
- **嵌套 gmem**：`adjust_nested_fault_perms` 现在同时摘 `W|DIRTY`——保持语义正确（L1 不给写，影子既不可写也不标脏）。

---

## 4. pKVM：PROT_RW 家族与"W 位到底从哪来"

### 4.1 先回答核心疑问：普通虚机的 prot.W 是什么时候"配进来"的？

**答案：从来没有"存进 KVM"。** 这正是博客《写权限的下传链路》的核心结论，在 DBM 系列下依然成立：

- KVM/arm64 对普通 VM 的可写性**没有任何持久字段**（`kvm_arch_memory_slot` 是空结构体）。prot 是**单次 fault 内的局部变量**：
  ```
  fault 进入 → kvm_s2_fault_compute_prot() 现算
    （来源: map_writable ← memslot flags + GUP/VMA 两层查证）
  → map/relax 编码进 PTE → 丢弃
  ```
- 所以"编码器读 prot.W、解码器回 prot.W"**不构成循环依赖**：链条的源头永远是 fault 时刻的 VMA/memslot 现算，PTE 只是投影。唯二从 PTE 读回 prot 的路径是：
  1. **eager split 的继承链**（`kvm_pgtable_stage2_pte_prot(父pte)` → 再编码给子页）——它能成立是因为编码器先写过这些位（round-trip 自洽）；
  2. pKVM 的状态查询（只取 SW 位，见下）。

你迷路的那条链 `__pkvm_init_finalise → fix_host_ownership → fix_host_ownership_walker → kvm_pgtable_hyp_pte_prot` **是 pKVM（nVHE）自己的事，与普通虚机无关**：它解码的是 **hyp stage-1 表**（hyp 自己的 VA 空间），用途是"hyp stage-1 里登记的页归属，要在 host stage-2 里补登记"：

```c
/* arch/arm64/kvm/hyp/nvhe/setup.c, fix_host_ownership_walker() */
	prot = kvm_pgtable_hyp_pte_prot(ctx->old);   /* 解码 hyp S1: AP 字段 → R/RW */
	state = pkvm_getstate(prot);                  /* 只取 SW 位的页归属状态 */
```

### 4.2 KVM_PGTABLE_PROT_RW 改动后，nVHE/hyp 侧到底变了什么

patch 2 的改动：

```c
/* arch/arm64/include/asm/kvm_pgtable.h */
-#define KVM_PGTABLE_PROT_RW	(KVM_PGTABLE_PROT_R | KVM_PGTABLE_PROT_W)
+#define KVM_PGTABLE_PROT_RW	(KVM_PGTABLE_PROT_R | KVM_PGTABLE_PROT_W | \
+				 KVM_PGTABLE_PROT_DIRTY)
/* DEVICE: BIT(4)→BIT(5), NORMAL_NC: BIT(5)→BIT(6), DIRTY 占 BIT(4) */
```

逐消费者分析（这是"nVHE 是否也要按 DBM 表示 W"的完整答案）：

| 消费者 | 编码器 | DIRTY 的下场 | 结论 |
|---|---|---|---|
| hyp stage-1（`PAGE_HYP` 家族） | `hyp_set_prot_attr()` → **S1 AP 字段** | **被无视**（它只判 `prot & PROT_W` 决定 AP_RW/AP_RO，S1 格式没有 DIRTY 槽位） | hyp 自身映射**零变化** |
| pKVM host stage-2（`PKVM_HOST_MEM/MMIO_PROT`） | `stage2_set_prot_attr()`（同一份 pgtable.c 编进 nVHE 镜像） | **被消费**：落 S2AP_W | 见下——**这是必须加 DIRTY 的原因** |
| pKVM guest 映射（`pkvm_mem_abort` 用 `PROT_RWX`） | 同上 | 同上 | 同下 |

**关键推理**：host stage-2 和 pKVM guest S2 的 VTCR **从不设置 HD**（全树 `VTCR_EL2_HD` 只出现在 Leo 新增的 arm.c/mmu.c 普通 VM 路径）。若 `PROT_RW` 不补 DIRTY：

```
PKVM_HOST_MEM_PROT = R|W|X → 编码: DBM=1, S2AP_W=0 → WC → HD=0 → 等同 RO
→ host 内核写自己的内存 / pKVM guest 写自己的内存 → 全部 Permission Fault
→ pkvm_mem_abort 的 map 循环 old==new 恒 -EAGAIN → 无限 fault 死循环
```

所以：**不是"nVHE 也要用 DBM 表示 W"，而是"stage-2 编码器换了 W 的落表语义后，所有想保持'可写'的复合宏必须补 DIRTY 才能落成 WD"。** DIRTY 补进宏是给 stage-2 消费者的保险；stage-1 消费者（hyp S1）天然忽略它。

已核对过等值比较点，无破坏：
- `pkvm.c:425` 的 `WARN_ON_ONCE(prot != KVM_PGTABLE_PROT_RWX)`：比较对象是调用者传的**常量**（`pkvm_mem_abort` 用同一宏），非解码值；
- `fix_host_ownership_walker` 的 `prot == PAGE_HYP_EXEC`：hyp 代码段解码为 R|X（AP_RO，无 RW），与 DIRTY 无关；
- `mem_protect.c` 的 `pkvm_getstate()`：只 FIELD_GET SW 位。

### 4.3 pKVM guest 路径行为核对

`pkvm_mem_abort()` 用 `KVM_PGTABLE_PROT_RWX` 直接 map（无 compute_prot）——现在含 DIRTY → WD，**与旧行为等价**（旧编码 W → S2AP_W）。pKVM guest 不走 `kvm_supports_hafdbs()` 分支（protected 模式 host 在 EL1，`has_vhe()` 为假），HD 恒 0，页恒 WD 恒可写。

---

## 5. SMMU 侧影响（新增重点分析）

### 5.1 直接回答：SMMU 有没有 DBM 位？

**有，而且内核已经在用。** SMMUv3 的对应特性叫 **HTTU（Hardware Translated Table Update）**：

```c
/* drivers/iommu/arm/arm-smmu-v3/arm-smmu-v3.h */
#define IDR0_HTTU_ACCESS		1      /* 仅 AF 更新 */
#define IDR0_HTTU_ACCESS_DIRTY		2      /* AF + Dirty 更新 ← 有 DBM 能力 */
#define IDR0_HTTU_ACCESS_DIRTY_HAFT	3      /* 再加 HAFT */

/* drivers/iommu/arm/arm-smmu-v3/arm-smmu-v3.c */
static bool arm_smmu_dbm_capable(struct arm_smmu_device *smmu)
{
	u32 features = (ARM_SMMU_FEAT_HD | ARM_SMMU_FEAT_COHERENCY);
	return (smmu->features & features) == features;   /* 需要 HD + TLU 一致性 */
}
```

描述符层面与 CPU **完全同构**——DBM 同样在 bit 51，脏状态同样藏在权限位：

```c
/* drivers/iommu/io-pgtable-arm.c */
#define ARM_LPAE_PTE_DBM		(((arm_lpae_iopte)1) << 51)
#define ARM_LPAE_PTE_AP_RDONLY_BIT	7
#define iopte_writeable_dirty(pte)					\
	(((pte) & (ARM_LPAE_PTE_AP_RDONLY | ARM_LPAE_PTE_DBM)) == ARM_LPAE_PTE_DBM)
#define iopte_set_writeable_clean(ptep)					\
	set_bit(ARM_LPAE_PTE_AP_RDONLY_BIT, (unsigned long *)(ptep))
```

即 SMMU 的脏跟踪（IOMMUFD/VFIO 热迁移用，`IOMMU_CAP_DIRTY_TRACKING`）就是"bit51=DBM 修饰位 + bit7 权限位兼任脏位"——**与 Leo 给 stage-2 做的事是同一个把戏**（极性不同：S1 的 AP[2] 是 1=干净，S2 的 S2AP[1] 是 1=脏）。HTTU 需要按 CD/STE 逐级软件使能：SVA 路径已默认 `CD.TCR.HA|HD` 一起开（arm-smmu-v3-sva.c:108 注释："PTE_WRITE and PTE_DBM share the same bit"）。

注意：**当前 SMMU 脏跟踪只支持 stage-1 domain**（arm-smmu-v3.c:2938 `stage == ARM_SMMU_DOMAIN_S1` 才挂 dirty_ops）。

### 5.1.1 SVA 深挖：共享 stage-1 表下"默认用 DBM"的真实机制

SVA（Shared Virtual Addressing）是"CPU 与 SMMU 共享页表"**已经上线**的场景——共享的是**进程 stage-1 页表**（SMMU 的 SVA CD 把 TTBR0 指向进程 pgd，设备 DMA 用与 CPU 相同的 VA）。它虽与 KVM stage-2 无关（Leo 系列不改它），但完整演示了"共享表 + DBM 编码"必须满足的契约。

**关键事实一：Linux stage-1 早就"默认用 DBM"了，这不是 Leo 发明的新开关。** 每个可写 PTE 恒带 `PTE_WRITE == PTE_DBM`（bit 51）；脏状态藏在 PTE_RDONLY（bit 7）里，由 pte 族函数维护：

```c
/* arch/arm64/include/asm/pgtable.h */
#define pte_write(pte)		(!!(pte_val(pte) & PTE_WRITE))       /* PTE_WRITE == PTE_DBM */
#define pte_hw_dirty(pte)	(pte_write(pte) && !pte_rdonly(pte)) /* 硬件脏 = RDONLY 清零 */

static inline pte_t pte_mkclean(pte_t pte)        /* 写回完成: 变 clean-writable */
{
	pte = clear_pte_bit(pte, __pgprot(PTE_DIRTY));
	pte = set_pte_bit(pte, __pgprot(PTE_RDONLY));  /* → (RDONLY=1, DBM=1) */
	return pte;
}
static inline pte_t pte_mkdirty(pte_t pte)        /* 变 dirty-writable */
{
	pte = set_pte_bit(pte, __pgprot(PTE_DIRTY));
	if (pte_write(pte))
		pte = clear_pte_bit(pte, __pgprot(PTE_RDONLY)); /* → (RDONLY=0, DBM=1) */
	return pte;
}
static inline pte_t pte_wrprotect(pte_t pte)      /* 收权前先把硬件脏折算成 sw 脏 */
{
	if (pte_hw_dirty(pte))
		pte = set_pte_bit(pte, __pgprot(PTE_DIRTY));
	pte = clear_pte_bit(pte, __pgprot(PTE_WRITE));
	pte = set_pte_bit(pte, __pgprot(PTE_RDONLY));
	return pte;
}
```

stage-1 版三态（与 S2 版对照着看，编码极性相反）：

| 状态 | PTE_RDONLY(7) | PTE_WRITE/DBM(51) | **不懂 DBM 的 walker 眼中** |
|---|---|---|---|
| dirty-writable | 0 | 1 | RW（碰巧读对） |
| **clean-writable**（写回后出现） | **1** | **1** | **RO（读错！）** |
| read-only | 1 | 0 | RO（读对） |

clean-writable 不是罕见态：**file-backed 页每次写回（writeback → rmap → page_mkclean → pte_mkclean）都会进入这个编码**。它对 CPU 无害，因为：

**关键事实二：CPU 侧的 TCR_EL1.HA|HD 是内核自己开的。** proc.S 在 early CPU setup 无条件开 HA（HAFDBS 存在时）；HD 由 `ARM64_HW_DBM` capability 延迟开启（cpufeature.c `cpu_enable_hw_dbm()`：置 TCR_EL1.HD + `local_flush_tlb_all()`，带 broken-DBM erratum 排除）——**这正是 Leo `kvm_supports_hafdbs()` 检查的那个 cap**。所以 CPU 把 (RDONLY=1, DBM=1) 读成可写·干净，写时硬件清 RDONLY，全程无 fault。

**关键事实三：SMMU 被 SVA 拉进了同一契约。** SVA CD 无条件使能 HTTU（硬件支持时）：

```c
/* drivers/iommu/arm/arm-smmu-v3/arm-smmu-v3-sva.c:107-113 */
	/*
	 * Enable Hardware Access and Dirty updates (DBM) if supported. This is
	 * safe to enable by default, as PTE_WRITE and PTE_DBM share the same bit,
	 * ...
	 */
	if (master->smmu->features & ARM_SMMU_FEAT_HA)
		target->data[0] |= cpu_to_le64(CTXDESC_CD_0_TCR_HA);
	if (master->smmu->features & ARM_SMMU_FEAT_HD)
		target->data[0] |= cpu_to_le64(CTXDESC_CD_0_TCR_HD);
```

设备写 clean-writable 页：HTTU SMMU 与 CPU 完全对称（免 fault + 硬件置脏），注释里"safe to enable by default"的底气正来自"PTE_WRITE 就是 PTE_DBM"——同一张表、同一种解释。

**回答"会不会有这种问题"**：

- **HTTU SMMU（IDR0.HTTU≥2）上：没有问题**，机制如上，CPU/SMMU 对称。
- **非 HTTU SMMU 上：同类问题真实存在**——CD 开不了 HD，clean-writable 页对设备就是 RO，DMA 写触发 SMMU translation fault。且设备没有 CPU 那样的兜底（CPU 写 RO-but-writable PTE 会 fault 到内核，fault handler 看 `pte_write()==true` 就清 RDONLY 重试；设备 fault 只能报给驱动/PRI，没人替进程改 PTE）。现实缓解因素：① SVA 主流负载（GPU/NPU 计算）用**匿名内存**，匿名页恒 dirty-writable（RDONLY=0），任何 walker 都读对；② 部署 SVA 的现代服务器 SoC 的 SMMU 基本都有 HTTU。但这是"负载恰好躲开"，不是架构保证。

**回答"默认用 DBM，正常场景会不会没写权限"**：

- 不会。DBM 编码是 arm64 Linux stage-1 的**既有默认**（PTE_WRITE==PTE_DBM 已存在多年），CPU walker 一定解释它（HD gate 就是为此存在）。
- "写权限丢失"只出现在**第二个 walker 介入共享表却不解释 DBM**的组合里：SVA 的解法是把 SMMU 拉进契约（CD.TCR.HA|HD）；将来的 KVM S2 共享同理（STE 级 HTTU 使能），或将该 walker gate 掉（§5.3 的两条前置约束）。
- 对 Leo 系列本身：S2 表的 walker 今天只有 CPU（HD 由 `kvm_supports_hafdbs()` 保证），所以不踩这个坑；未来共享 S2 时按 SVA 样板处理即可。**SVA 就是 S2 共享的样板工程：CD.TCR.HA|HD 之于进程 stage-1 表 = STE HTTU 之于 KVM stage-2 表。**

### 5.2 但今天没有影响：SMMU 不走 KVM 的 stage-2

本树（及当前主线）**没有 SMMU↔KVM stage-2 共享代码**。设备直通的数据面：

```
设备 DMA: IOVA → SMMU 自己的 io-pgtable（iova→pa，SMMU 驱动建） → HPA
guest CPU: GPA → KVM stage-2（ipa→pa，KVM 建） → HPA
```

两套表独立存在、独立编码、独立脏跟踪（QEMU 迁移时合并两份脏集）。**Leo 的编码改动只落在 KVM 的表上，设备 DMA 路径零影响**。"SMMU 还没有做使能"在今天是准确的描述，但准确的原因是"没有东西可使能"——SMMU 从不解释 KVM 的 PTE。

### 5.3 真正的风险窗口：S2 共享（上游推进方向）

风险在未来：**SMMU 直挂 KVM stage-2**（shared stage-2 / iommufd 方向，避免两套表内存翻倍与映射不同步）一旦落地，SMMU 硬件就开始 walk KVM 建的表：

- WC 页（S2AP=01, DBM=1）被 SMMU walk 时：需要该 STE 的 stage-2 HTTU-dirty **已使能** 且 SMMU **支持** dirty 更新（IDR0.HTTU≥2）。两者齐备时行为正确：DMA 写免 fault、硬件升 S2AP[1]。
- 任一不满足：**WC 对 DMA 就是 RO → 设备写直接 SMMU event/fault**（设备 DMA 不可 fault-replay，无法像 CPU fault 那样 relax 补救——直接数据面错误）。
- 现存大量 SMMUv3 实现的 IDR0.HTTU < 2（老 SoC），硬件层面就无解。

**给共享方案的前置约束（建议写进 HDBSS/rebase 的 cover letter 或 review 回复）**：

1. `kvm_supports_hafdbs()` 增加 gate：VM 无直通设备，或其所有设备所在 SMMU `dbm_capable` 且 STE 已使能 HTTU-dirty；
2. 或 attach 共享 S2 时一次性把全 VM 的 WC 页升 WD（相当于反向 wp），此后该 VM 的 fault 恒给 DIRTY——退化为旧行为，正确性优先；
3. SVA 的先例说明这是同构问题：SMMU 共享**进程 stage-1** 表时，驱动就必须开 HA|HD 才能正确理解 CPU 写的 PTE（DBM 位）——详见 §5.1.1；共享 **KVM stage-2** 时只是方向反过来（KVM 建表、SMMU walk），要求完全对称。

### 5.4 顺带澄清一个容易混淆的点

"SMMU 没有 DBM 所以设备页必须 WD"（§2 已反驳）与"SMMU 有 HTTU-DBM 但没使能"（本节）是两回事：

- 设备页（guest CPU 的 MMIO 访问）：写者走 CPU S2 walk，与 SMMU 无关；
- SMMU 表（设备 DMA 的 IOVA 翻译）：SMMU 驱动自建，编码由 io-pgtable 决定，与 KVM 的 DBM 编码无关；
- 只有"共享 S2"才把两者接通——而那是还没发生的事。

---

## 6. 与 HDBSS v5（本仓库 code_v5_2_tested 分支）的 rebase 冲突清单

对照 v5 分支已有 commit，逐项给 rebase 决策：

| v5 侧 | Leo 侧 | 决策 |
|---|---|---|
| `db21f07bc10a` Set DBM unconditionally on writable stage-2 PTEs | patch 1+2 | **丢 v5 保 Leo**。v5 是两态版（WD 恒 DBM\|W），等价 Leo step1 中间态；v5 把 block strip DBM 放在共享 `stage2_attr_walker`，会让 relax 误伤（block 粒度 relax 被剥 DBM → S2AP_W=1 但 DBM=0，软硬件判断分裂），Leo 的专属 walker 更对 |
| `a274bea30ac2` KVM_REQ_HDBSS_RELOAD_VTCR | patch 4 KVM_REQ_RELOAD_STAGE2 | **丢 v5 保 Leo**（更通用），邮件已确认 |
| `f497b018c022` auto HDBSS enable/disable on dirty logging change | patch 5 `kvm_set_hafdbs()` | **合并成一个开关函数**：同一事件（logging 开/关）翻 HD/HDBSS 两位、发一次 RELOAD。v5 的 `kvm_arm_enable_hdbss_global()` 设的是 `HD\|HDBSS\|HA` 三位——见 §7.2，HA 必须带上 |
| v5 fault 路径的 DIRTY 判断 | patch 5 compute_prot 的 `!(logging \|\| kvm_supports_hafdbs)` | **重写条件**：HDBSS 开启时即使 logging 中也该建 WC（免 fault 跟踪是 HDBSS 的立身之本），条件要进化成"logging 且 HDBSS 未接管时才给 DIRTY" |
| v5 HDBSS drain（buffer 收割） | （无对应） | **决策：drain 不做 folio 收割**（曾实现后撤除）。F2 投机标脏 + wp/unmap 收割已覆盖 WD 全部出口，drain 收割冗余且会给 flush 引入 mmu 锁；详证 `hdbss_v5_unmap_harvest.md` §1.2 |
| v5 lazy split 依赖"block 清 DBM" | patch 3 wrprotect walker | 一致，无冲突（v4 sashiko S4 与 Leo patch3 是同题共解） |

---

## 7. 风险清单（含 sashiko 未覆盖项，按严重度排序）

### 7.1 [Critical] host folio 脏记账缺口 → 内存回收静默丢数据（sashiko Critical，最重）

**问题链**：

```
CPU0 (fault)                       CPU1 (guest 运行, HD=1)
─────────────────────────────      ─────────────────────────────
kvm_s2_fault_map()
  读 fault, prot = W (无 DIRTY)
  map → PTE = WC
  kvm_release_faultin_page(...,
      dirty = prot & DIRTY = false)
  → kvm_release_page_clean()
  → folio 不标脏                     HAFDBS 免 fault 放行写
                                    → 硬件置 S2AP_W=1 (WC→WD)
                                    → KVM 全程无感知
─────────────────────────────      ─────────────────────────────
host MM 视角: folio 是干净的
→ 内存压力下回收: page-cache 页直接丢弃 / 不回写
→ guest 写过的数据丢失（静默数据损坏）
```

arm64 KVM 的 unmap/mmu-notifier 路径**不回收 S2 脏位**（`stage2_unmap_walker` 只 put_page，无 SetPageDirty 逻辑），所以没有任何兜底把硬件脏同步回 folio。

**x86 的先例**（`kvm_release_faultin_page` 的现成注释）：

> "KVM must (somewhat) **speculatively mark the folio dirty if KVM could locklessly make the SPTE writable**."

x86 的硬件脏位同样免锁写脏，x86 的解法就是"凡是可能被免锁写脏的映射，fault 时就投机标脏"。

**修复（Leo 邮件已认，但要拆两用）**：

```c
/* 两种脏分开: folio 记账用 W(宽容), bitmap 记账用 DIRTY(精确) */
kvm_release_faultin_page(kvm, page, !!ret, prot & KVM_PGTABLE_PROT_W);
...
if ((prot & KVM_PGTABLE_PROT_DIRTY) && !ret)
	mark_page_dirty_in_slot(...);
```

- folio dirty 过标是安全的（多几次回写而已）；bitmap 必须精确（读 fault 不该进迁移脏集）。
- **gmem_abort 同样要改**（虽然 gmem 当前恒 WD 不触发，改动保持两处对称）。
- 长期方案：unmap/mmu-notifier 收割 S2AP_W → `kvm_set_page_dirty`；已实现于 code_v5_3_leo
  （F2 投机标脏 + wp/unmap 两点收割，drain 侧经冗余分析放弃，见 `hdbss_v5_unmap_harvest.md` §1.2）。
  **stage-1 样板**：`zap_present_folio_ptes()`（mm/memory.c:1780）在拆映射时收割 PTE 脏位
  `folio_mark_dirty(folio)`，机制与此完全同构（详见 `stage1_dbm_reference.md` §2.4）。

### 7.2 [High] HD=1 却不开 HA：疑似规格违规（新发现，sashiko 未提）

patch 5 只 `vtcr |= VTCR_EL2_HD`，HA 仍为 0。两条反证：

1. SMMU 驱动同场景注释（arm-smmu-v3.c:1676）："**To enable dirty flag update, set both Access flag and dirty state update**"——CD.TCR 的 HA|HD 永远成对设；
2. 本仓库 HDBSS v5 设计引用的 spec 条款（D8.5.2.3）："**HDBSS is enabled only if VTCR_EL2.{HDBSS,HA,HD} are {1,1,1}**"，v5 代码也是三位齐设；
3. **stage-1 样板**：内核自家 stage-1 也是 HA 先行（proc.S `__cpu_setup`）、HD 经 `ARM64_HW_DBM` cap 补开（cpufeature.c），从未出现单开 HD 的写法（详见 `stage1_dbm_reference.md` §2.5）。

若 VTCR_EL2.HD 同样要求 HA（大概率，需对着 ARM ARM DDI 0487 的 VTCR_EL2.HD field description 核实），patch 5 单设 HD 轻则 HD 不生效（优化失效但行为安全——写照常 fault），重则 CONSTRAINED UNPREDICTABLE。

**修复**：`vtcr |= VTCR_EL2_HD | VTCR_EL2_HA`。附带收益：硬件自动置 AF，`handle_access_fault` 的 AF fault exit 大幅消失（mmu-notifier mkold 清 AF 后，下次访问硬件直接置回）。

### 7.3 [High] 单 memslot logging 全局关 HD + 静态能力判断 = 常态性能悬崖（sashiko High，现实场景比 Leo 想的普遍）

QEMU 的 std VGA **默认长期**对 VRAM memslot 开 `KVM_MEM_LOG_DIRTY_PAGES`（显示刷新跟踪），这不是"特殊场景"，是**带显示的桌面包 VM 的常态**。后果链：

```
VGA slot 开 logging
→ kvm_set_hafdbs(kvm, 0)          /* VTCR 是 per-VM 的, 全局关 */
→ 全 VM HD=0
→ 普通 RAM slot 读 fault:
     compute_prot 判据是静态 kvm_supports_hafdbs(kvm) == true
     → 仍然 withheld DIRTY → 建 WC
→ HD=0 下 WC == RO → 每页首次写一次多余的 Permission Fault
```

讽刺的是：优化的目标场景（非迁移免 fault）里最常见的 VM（带 VGA），反而全体退化成"每页一 fault"。存量 WC 页（logging 开之前建的）也要各付一次 fault。

**修复方向**：

1. compute_prot 的 WC 决策改看**动态**状态（当前 `kvm->arch.mmu.vtcr & VTCR_EL2_HD` 是否真的开着）而非静态能力——HD 关了之后新建的页全部 WD，只有存量 WC 页付一次性代价。**stage-1 样板**：`finish_fault`（mm/memory.c:5716）的同类投机判断看的是 `folio_test_dirty(folio)` 这个**动态事实**，不是任何静态能力位（详见 `stage1_dbm_reference.md` §2.2）；
2. 或接受"任一 slot logging 即全局退出 WC 模式"并在 kvm_set_hafdbs(0) 里顺手把存量 WC 批量升 WD（一次遍历换常态零 fault）。

### 7.4 [Critical] vtcr 无锁 RMW 数据竞争（sashiko Critical）

`kvm_setup_vcpu()`（持 config_lock）与 `kvm_set_hafdbs()`（持 slots_lock）对 `kvm->arch.mmu.vtcr` 做交错 RMW。极端交错：setup 读到 `nr_memslots_dirty_logging==0`（logging 尚未提交）→ 稍后写 HD=1，恰好覆盖 set_hafdbs(0) 的清位 → **HD=1 与 logging 并存** → 硬件静默置脏、绕过 fault 标脏 → 迁移丢脏页。

Leo 已认加 slots_lock。更稳的做法：把 HD 状态做成**纯推导量**（`cap && nr_memslots_dirty_logging == 0`）每次重算，消灭 RMW 覆盖窗口，而不是给两把锁调序。

### 7.5 [High] RELOAD_STAGE2 无 TLBI（sashiko High）——方向性分析后：开 logging 方向安全，关 logging 方向有"收益延迟"

- **HD 1→0（开 logging）**：RELOAD 后 vCPU 立即回 guest，旧 TLB 里还缓存着 HD=1 时代硬件提升过的可写翻译 → 这段窗口的写免 fault、无脏记录。但后续 `kvm_mmu_wp_memory_region()` 末尾的 `kvm_flush_remote_tlbs_memslot()` 兜底清掉；且窗口内的写在迁移协议上属于"快照前写入"，由第一轮全量拷贝覆盖。**功能安全**（Leo 邮件回复成立），建议补注释说明依赖此顺序。
- **HD 0→1（关 logging，迁移结束）**：旧 TLB 缓存着 WC 页的 RO 翻译（HD=0 时代 walk 出的），继续拦写 → relax 每页再付一次 fault 才回到免 fault 世外桃源。功能无害，**收益打折**。讲究的做法是 set_hafdbs 后补一次 VMID 级 TLBI。
- RELOAD 请求本身 `KVM_REQUEST_WAIT | KVM_REQUEST_NO_WAKEUP`：睡眠中的 vCPU 不被唤醒——它们没在跑 guest，没有旧 HD 的硬件 walk，下次进 guest 前自然会处理请求再加载新 VTCR。这个组合是**安全且正确**的设计。
- **stage-1 样板**：`cpu_enable_hw_dbm()`（cpufeature.c:1978）翻 TCR_EL1.HD 配 `isb() + local_flush_tlb_all()`——内核自家翻 HD 从不裸奔，Leo 的 VTCR 翻转没做 TLBI 连这个先例都没跟（详见 `stage1_dbm_reference.md` §2.5）。

### 7.6 [Medium] 新 wrprotect walker 的并发原语降级

旧实现经 `stage2_attr_walker` → `stage2_try_set_pte`（SHARED 走 cmpxchg，竞争返回 -EAGAIN）。新 `stage2_wrprotect_walker` 裸 `WRITE_ONCE`：

- 当前唯一调用方 `kvm_stage2_wp_range` 在 **mmu 写锁**下（`stage2_apply_range` 循环持写锁），安全；
- 但 API 从此**不再容忍共享锁调用**。HDBSS v5 的 drain 后 wp 若在 read lock + SHARED 语境下调用，会引入"裸写 vs cmpxchg relax"的丢失更新竞态。rebase 时要么给 walker 恢复 cmpxchg+EAGAIN 重试，要么在函数头注释声明 exclusive-only 契约。

### 7.7 [Low/Info] 杂项

- sashiko Low（KVM_MR_DELETE 死代码）：pre-existing，非 Leo 引入；
- `kvm_vcpu_has_nv()` 重构：per-vcpu 判断变 per-KVM（任一 vcpu 有 EL2 → 全 VM 视为 nv）。对 HAFDBS gating 是保守方向（安全），但混合 feature 配置的 VM 语义有变，review 时值得点一句；
- patch 2 有双空行等风格瑕疵；
- patch 1 的 wrprotect 版本（clr DBM|S2AP_W）是两步走的中间态，被 patch 3 覆盖——review 时若有人只拿 patch 1 会问"清 DBM 岂不废了硬件升脏"，答案：page 级最终版只清 S2AP_W（WD→WC，硬件可再升），block 级清 DBM 是为了逼出 lazy split 的 fault。

---

## 8. sashiko 问题处置总表

| # | 位置 | 级别 | 问题 | 处置 |
|---|---|---|---|---|
| 1 | patch1 nested.c | High | 无条件认 DBM → L1 的 RO 页被读成可写，L1→L2 边界击穿；L1 脏跟踪失效 | 成立。依赖 Oliver 嵌套 HAFDBS 模拟系列，gate 在 L1 的 VTCR.HD；短期 revert 为只读 S2AP_W |
| 2 | patch2 编码器 | Critical(误报) | "PROT_W 无 DIRTY → WC 是 DBM bypass" | **by design**，Leo 已答：这正是要硬件接手的目的 |
| 3 | patch2 folio 记账 | Critical(真) | WC + 硬件免锁写脏 → host folio 永不标脏 → 回收丢数据 | §7.1：release_faultin_page 改回用 W；wp/unmap 收割已落地 code_v5_3_leo |
| 4 | patch5 vtcr 竞态 | Critical(真) | setup_vcpu vs set_hafdbs 无锁 RMW | §7.4：slots_lock 或纯推导重算 |
| 5 | patch5 TLBI | High(半真) | RELOAD 后无 TLBI | §7.5：开 logging 方向由 wp 的 flush 兜底；关方向补 VMID TLBI 更优 |
| 6 | patch5 单 slot 性能 | High(真且低估) | VGA 常态 logging → 全局 HD off → 每页一 fault | §7.3：compute_prot 动态化 / 批量升 WD |
| 7 | patch5 KVM_MR_DELETE | Low | 死代码 | pre-existing，顺手清理即可 |

---

## 9. 疑问快答表（原邮件 inline 疑问汇总）

| 疑问 | 答案（详见） |
|---|---|
| patch1 wrprotect clr 清 DBM，硬件 WC→WD 失效？ | 中间态如此，patch 3 终态：page 只清 S2AP_W（WD→WC，硬件可再升），block 清 DBM 逼 lazy split（§7.7） |
| L2 也要用 DBM？HDBSS/HACDBS 支持 L2 吗？ | 不支持。`!kvm_vcpu_has_nv` gate 排除；walk 的联合判断只是"读懂 L1 的表"的前向兼容，且自身带安全洞（§1） |
| PROT_RW 在 nVHE 也要按 DBM 表示 W？ | 不是。hyp S1 忽略 DIRTY；补 DIRTY 是给 host S2/pKVM guest S2 落 WD 用的，否则退化为 RO 死循环（§4.2） |
| 编码器/解码器循环依赖？prot.W 谁配的？ | 无环。prot 是单次 fault 的局部变量，源头是 VMA/memslot 现算；PTE 是投影。你追的 kvm_pgtable_hyp_pte_prot 链是 pKVM 自己的 hyp S1（§4.1） |
| device 页也 WD？W/DIRTY 何时进 prot？ | device 恒 `W\|DIRTY`（旧行为保持）；普通 RAM 仅 HAFDBS 机器非迁移读 fault 单独给 W（§2.2） |
| 加 patch 前两态 RW 全转译为 WD，WC 只出现在热迁移？ | 差一点：WC 出现在 ①HAFDBS 机器非迁移的读 fault（新行为）②logging 期读 fault（此时 WC==RO 等价旧行为）。其余 RW 场景确实都转译 WD（§0.2） |
| ioremap 必须加 DIRTY？SMMU 没 DBM？ | 必须加，但与 SMMU 无关：设备页不参与脏跟踪、WC 零收益、HD=0 时纯亏（§2.2、§5.4） |
| 有些地方两 flag 一起加有些单独加？ | 规则统一："写已发生或没人接第一次写 → W\|DIRTY；只有 HAFDBS 机器非迁移普通 RAM 读 fault 单独 W"（§2.2） |
| kvm_release_faultin_page 没看懂？ | 它是 **host folio** 脏记账（SetPageDirty，回收正确性），与 mark_page_dirty_in_slot 的 **KVM 脏位图**（迁移正确性）是两套账；当前代码把两套账绑在同一 DIRTY 判断上，是 §7.1 的根源 |
| mark_page_dirty_in_slot 按 D 位语义？ | 对，bitmap 记账用 DIRTY 精确门控是对的；要修的只有 folio 那半（§7.1） |
| 为什么 dirty logging 开始要关 HD？ | HD=1 时 WC 页的写被硬件静默升脏、无 fault——"写 fault 出来标脏"的经典跟踪循环就不成立了。必须先关 HD（RELOAD 生效）再 wp（§7.5 的顺序依赖） |
| 芯片必须支持 DBM？SMMU 有 DBM 吗？ | CPU 侧：`kvm_supports_hafdbs()` gate 保证不支持时全走 WD 旧路径；SMMU 有 HTTU-DBM（IDR0.HTTU≥2）且驱动已用，但今天不共享 KVM S2 所以无影响；S2 共享落地时必须 gate 或批量 WD 化（§5） |
| SVA 共享 stage-1 表会不会有同样问题？默认用 DBM 正常场景会不会没写权限？ | 不会，且这正是现成先例：Linux stage-1 的 PTE_WRITE 本来就等于 PTE_DBM（每个可写 PTE 恒带 bit51），CPU 开 TCR_EL1.HA\|HD 解释它，SVA 的 SMMU 被 CD.TCR.HA\|HD 拉进同一契约（硬件支持时）。唯一坑：非 HTTU SMMU 上 clean-writable 页（写回后出现）对设备是 RO，DMA 写 fault 且无兜底——靠"匿名页恒 dirty-writable"的负载特性躲开（§5.1.1） |

---

## 附：本仓库关键代码索引

| 主题 | 位置 |
|---|---|
| S2 DBM 位定义 | arch/arm64/include/asm/kvm_pgtable.h `KVM_PTE_LEAF_ATTR_HI_S2_DBM` |
| 编码器 W/DIRTY 分离 | arch/arm64/kvm/hyp/pgtable.c `stage2_set_prot_attr()` |
| 解码器 | arch/arm64/kvm/hyp/pgtable.c `kvm_pgtable_stage2_pte_prot()` |
| wrprotect 专属 walker | arch/arm64/kvm/hyp/pgtable.c `stage2_wrprotect_walker()` |
| HAFDBS 资格/开关 | arch/arm64/include/asm/kvm_mmu.h `kvm_supports_hafdbs()`；arch/arm64/kvm/mmu.c `kvm_set_hafdbs()` |
| VTCR 重载请求 | arch/arm64/kvm/arm.c `check_vcpu_requests()` `KVM_REQ_RELOAD_STAGE2` |
| 嵌套联合判断 / L1 能力限制 | arch/arm64/kvm/nested.c `walk_nested_s2_pgd()` / :1783 `ID_REG_LIMIT_FIELD_ENUM(...HAFDBS, AF)` |
| L1 权限收窄 | arch/arm64/kvm/mmu.c `adjust_nested_fault_perms()` |
| gmem | arch/arm64/kvm/mmu.c `gmem_abort()` |
| ioremap | arch/arm64/kvm/mmu.c `kvm_phys_addr_ioremap()` |
| pKVM guest map | arch/arm64/kvm/mmu.c `pkvm_mem_abort()`；arch/arm64/kvm/pkvm.c:425 |
| hyp S1 编/解码（DIRTY 无关） | arch/arm64/kvm/hyp/pgtable.c `hyp_set_prot_attr()` / `kvm_pgtable_hyp_pte_prot()` |
| 页归属迁移（你迷路的链） | arch/arm64/kvm/hyp/nvhe/setup.c `fix_host_ownership_walker()` |
| folio 记账 | include/linux/kvm_host.h `kvm_release_faultin_page()`；virt/kvm/kvm_main.c `kvm_set_page_dirty()` |
| SMMU HTTU/DBM | drivers/iommu/arm/arm-smmu-v3/arm-smmu-v3.c `arm_smmu_dbm_capable()`、:1676 CD.TCR HA|HD；drivers/iommu/io-pgtable-arm.c `ARM_LPAE_PTE_DBM`、`visit_dirty()` |
| SVA CD 使能 HTTU | drivers/iommu/arm/arm-smmu-v3/arm-smmu-v3-sva.c:107-113（"PTE_WRITE and PTE_DBM share the same bit"） |
| stage-1 DBM 状态机 | arch/arm64/include/asm/pgtable.h:395-404 状态表、`pte_mkwrite_novma/pte_mkclean/pte_mkdirty/pte_wrprotect` |
| CPU 开 TCR_EL1.HA/HD | arch/arm64/mm/proc.S `__cpu_setup`（HA）；arch/arm64/kernel/cpufeature.c `cpu_enable_hw_dbm()`（HD，= ARM64_HW_DBM cap，含 `local_flush_tlb_all()`——注意 Leo 的 VTCR 翻转没做 TLBI，见 §7.5） |
| 三态模型架构表述 | 本仓库 commit db21f07bc10a commit message（FEAT_HAFDBS/FEAT_HDBSS） |
