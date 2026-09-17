# 回复 Leo DBM RFC:发送稿定案(2026-09-17)

> **定位**:对外发送的动作稿。三封可直接粘贴的英文邮件(B/A/C)+ 一个可选跟帖(D)
> + 发送/发系列前清单。深度分析不在此重复,权威依据是
> [leo_review_reply_draft.md](leo_review_reply_draft.md)(§0.5 maintainer 对账、§0.6 一页总览)。
> **线程状态(对账至 9/17)**:最后一封是 Leo 9/17 14:40(`<aqvt2gnlBZeNsaf4@LeoBrasDK>`,
> PATCH 5/5 线程:认领性能数据 + 问 pKVM),此后无人回复。旧稿(附录 A 邮件一/二)未发;
> 本文的 B 取代旧邮件一,C 在旧邮件二基础上定稿。
> **发送人署名**:Tian Zheng \<zhengtian10@huawei.com\>(下文邮件落款统一 Tian)。
> **spec 核查(2026-09-17,kunpeng MCP / DDI 0487 M.b 全文)**:邮件 A 首段升级为第一手
> 核实——四处定位均无 "HD=0 时 bit51 为 RES0" 明文;并新增 D8.4.2.1 Table D8-76
> (stage 2 写权限只由 S2AP 决定)作为 NV revert 的直接条文依据。详见 §2 核查记录。

## 0. 发送计划总览

| 序 | 邮件 | 回复哪封(In-Reply-To) | 收件人 | 一句话内容 | 时机 |
|---|---|---|---|---|---|
| 1 | **B 合并通告** | Leo 9/16 12:22 [`aqp73SxO78o7LJTs`](https://lore.kernel.org/linux-arm-kernel/aqp73SxO78o7LJTs@LeoBrasDK/) | Oliver + Leo | 下周 HDBSS v5 随系列合并发布(dirty ring + bitmap 已适配);请求 SoB/pickup;性能分工 | **先发**(回应 maintainer 点名) |
| 2 | **A NV revert 提议** | Leo 9/16 14:25 [`aqqY1QiB0ZBAQkwc`](https://lore.kernel.org/linux-arm-kernel/aqqY1QiB0ZBAQkwc@LeoBrasDK/) | Leo(cc Marc/Oliver) | 同样没找到 RES0 条文;NV 联合读先 revert 回 S2AP[1]-only | 与 B 同日 |
| 3 | **C 技术细节 review** | Leo 9/15 18:33 [`aqmBY_v74r4GMttY`](https://lore.kernel.org/linux-arm-kernel/aqmBY_v74r4GMttY@LeoBrasDK/)(PATCH 2/5 线程) | Leo(cc Oliver/Marc) | #1–#5 / N1 / N2+N7 / N9 / N10 + 0014 实证 | 随系列或前一天 |
| 4 | D(可选)pKVM 跟帖 | Leo 9/17 14:40 [`aqvt2gnlBZeNsaf4`](https://lore.kernel.org/linux-arm-kernel/aqvt2gnlBZeNsaf4@LeoBrasDK/) | Leo(cc Oliver) | HDBSS 寄存器 EL2-only / hyp 管道;编码本身 pKVM 中性 | 任意 |

**顺序理由**:B 先回答 Oliver 的 combined-series 点名(唯一 maintainer 行动项,也是 A/C
的语境);A 直接响应 Leo 的求助并给出我们已做的修复;C 承载 B 里提到的
"details in my reply on patch 2",须在系列定稿后发(内容引用了 0014 实证)。

**公共 Cc 列表**(各邮件沿用线程原样,去掉自己):

```
Marc Zyngier <maz@kernel.org>, Fuad Tabba <fuad.tabba@linux.dev>,
Joey Gouly <joey.gouly@arm.com>, Steffen Eiden <seiden@linux.ibm.com>,
Suzuki K Poulose <suzuki.poulose@arm.com>, Zenghui Yu <yuzenghui@huawei.com>,
Catalin Marinas <catalin.marinas@arm.com>, Will Deacon <will@kernel.org>,
Mark Rutland <mark.rutland@arm.com>, Raghavendra Rao Ananta <rananta@google.com>,
linux-arm-kernel@lists.infradead.org, kvmarm@lists.linux.dev,
linux-kernel@vger.kernel.org
```

---

## 1. 邮件 B:回 Oliver——合并系列通告 + Signed-off-by 请求(先发)

**背景**:Oliver 9/15 在 PATCH 1/5 线程
([`aqnku2TcFzIKhjQl`](https://lore.kernel.org/linux-arm-kernel/aqnku2TcFzIKhjQl@kernel.org/))点名
"Can you please work with Tian to get a combined series out for this?";
Leo 9/16 12:22 当众同意
([`aqp73SxO78o7LJTs`](https://lore.kernel.org/linux-arm-kernel/aqp73SxO78o7LJTs@LeoBrasDK/),
"Sure, one of the reasons I sent like this is so Tian could use it as a base
for his next version."),且早在 patch 4 线程说过 "rebase as much as you want"。
因此 B 是**确认 + 通告**,不是重新请求;礼貌上仍借 SoB 问题给 Leo 一个否决窗口。

**头信息**:

```
To: Oliver Upton <oupton@kernel.org>
Cc: Leonardo Bras <leo.bras@arm.com>, <§0 公共 Cc 列表>
Subject: Re: [RFC PATCH 1/5] KVM: arm64: pgtables: Change write bit from S2AP_W to DBM
In-Reply-To: <aqp73SxO78o7LJTs@LeoBrasDK>
```

**挂靠邮件**(lore):[aqp73SxO78o7LJTs@LeoBrasDK](https://lore.kernel.org/linux-arm-kernel/aqp73SxO78o7LJTs@LeoBrasDK/)

**正文**:

```
On Wed, Sep 16, 2026 at 12:22:05PM +0100, Leonardo Bras wrote:
> Sure, one of the reasons I sent like this is so Tian could use it as a base 
> for his next version.

Hi Oliver, Leo,

Works for us. I plan to send HDBSS v5 next week with this series merged
into it. Both dirty-tracking consumers are already built on top of the
three-state encoding: the dirty bitmap (the buffer drains into the
memslot bitmap on VM exit) and the dirty ring (the flush feeds
KVM_DIRTY_RING, with space reserved so a full buffer flush always
fits).

Leo, with your blessing, I'd like to pick patches 1-4 up into the HDBSS
tree with my Signed-off-by added, and rework patch 5 into a derived
hardware dirty mode — a pure function of the static capabilities and
the number of logging memslots, replacing both its kvm_set_hafdbs()
and our earlier HDBSS enable/disable hooks. On top we carry a few fixes
found while testing: splitting the host folio account from the bitmap
one (and harvesting S2AP_W/DBM back into the folio on unmap and
write-protect), pairing HD with HA, flushing the VMID on the mode
flip, and deriving the writable-clean decision from the live HD state
rather than the static capability. Details are in my reply on patch 2;
equally happy to hand any of these over for your v2 if you'd rather
keep the encoding series self-contained.

On the performance question from patch 5: Leo, glad you're getting a
machine — we'll contribute numbers from the HDBSS side (migration with
dirty ring and dirty bitmap, where the encoding pays off), plus the
desktop shape with an always-logged VGA slot, before and after the
live-HD-state fix.

Thanks,
Tian
```

**中文要点**(逐段核对用):

1. 引 Leo 的 "Sure" 开场 → "Works for us":正式接下 Oliver 的合并要求。
2. 通告:下周发 HDBSS v5,Leo 系列并入;两个标脏消费者已适配——
   dirty bitmap(VM exit 时 buffer 排入 memslot bitmap)和 dirty ring
   (flush 喂 KVM_DIRTY_RING,预留空间保证整 buffer 一次 flush 装得下)。
3. 请求 Leo:p1–4 pickup + 我的 SoB;p5 改造成 derived hardware dirty mode
   (纯推导:静态能力 + logging memslot 数,同时取代其 kvm_set_hafdbs() 和
   我们原来的 HDBSS enable/disable 双钩子);随系列携带修复清单
   (folio 拆账 + unmap/wp 收割 / HD|HA 成对 / 翻转后 VMID flush /
   WC 判断改看动态 HD)。细节指向 patch 2 线程回复(= 邮件 C);
   也乐意把修复移交他的 v2,由他选。
4. 性能分工:Leo 找机器测(9/17 已认领);我们出 HDBSS 腿(迁移 + dirty
   ring/bitmap,编码真正受益处)+ desktop VGA 形态 live-HD 修复前后。

**措辞说明**:

- **SoB 礼仪**:按内核惯例,pickup 他人 patch 保留原 SoB、追加自己的 SoB 即可
  (我们 0001–0004 已是双 SoB + `[zhengtian: ...]` 注记 + Link)。即使 Leo 不回,
  合并也成立;但他在场,问一句更稳,也给他在"v2 自含"与"并入 HDBSS"之间选边。
- **"next week" 是硬承诺**:发出即倒计时,§6 工程清单必须在下周前完成。
- 第三段顺带把 N8(性能)的分工当众定下来,呼应 Oliver 的
  "not expecting the performance gains to justify the behavior change"——
  我们补的正是他要看的数据(HDBSS 这个 meaningful user)。
- 不提 bit51/RES0、不提 vcpu_has_nv:那是 Leo/Marc 的架构讨论(见 §5)。

---

## 2. 邮件 A:回 Leo——NV 联合读 revert 提议

**背景**:Leo 在 PATCH 1/5 线程对 Marc 9/13 review 的 "Absolutely NOT"
([`86bja17cg7`](https://lore.kernel.org/linux-arm-kernel/86bja17cg7.wl-maz@kernel.org/),
walk_nested_s2_pgd() 联合读把 L1 只读页读成可写 = 内存损坏)连番表示困惑:
9/15 "Sorry, not really... please help me understand it"
([`aql8jY4o8SzjJuFU`](https://lore.kernel.org/linux-arm-kernel/aql8jY4o8SzjJuFU@LeoBrasDK/)),
9/16 14:25([`aqqY1QiB0ZBAQkwc`](https://lore.kernel.org/linux-arm-kernel/aqqY1QiB0ZBAQkwc@LeoBrasDK/))
承认在 Arm ARM M.cc 里找不到 "HD=0 时 bit51 为 RES0" 的条文(Table D8-53 只讲
位分配),请 Marc 给出处。
我们的立场:**条文出处已于 9/17 用 DDI 0487 M.b 第一手核查(四处定位均无,见下
核查记录),继续等 Marc 的指针;但 NV 部分不需要等架构答案**——KVM 对 L1 可见的 ID_AA64MMFR1_EL1.HAFDBS 限为 AF-only,bit51 对
L1 无架构含义,诚实 L1 拿它当软件元数据就会被联合读误判可写。NV 今天没有 HAFDBS
模拟,这段 hunk 直接 revert 回只读 S2AP[1],等模拟系列落地再回来(并 gate 在
L1 的 effective VTCR_EL2.HD 上)。**这正是我们 0001 已做的事**(不携带 nested.c
hunk,cover letter 已声明),可顺手移交给 Leo。

**spec 核查记录(2026-09-17,kunpeng MCP,DDI 0487 M.b 全文;PDF 页号 = 印刷页号)**:

| 位置 | 页码 | 关键内容 | "HD=0 时 bit51 RES0" 明文 |
|---|---|---|---|
| Stage 2 descriptor 字段表(Leo 的 M.cc "Table D8-53" 对应物) | D8-7735/7736 | bit[51]: **DBM**(Direct)/ **PIIndex[1]**(Indirect);bit[7]: S2AP[1]/Dirty 同款二选一 | 无 |
| D8.4.2.1.1 Stage 2 data accesses using Direct permissions | D8-7757 | **Table D8-76:S2AP[1:0] 定读写权限**(00 无/01 RO/10 WO/11 RW);INTJRL:HD=1 时硬件可置 S2AP[1] | 无 |
| D8.5.2.1 Hardware management of the dirty state(RXZFQH/RBRFGY/IMHJZP/IDLNSK) | D8-777x | 所有规则以 "dirty state hardware update **enabled**" 为前提 | 无 |
| VTCR_EL2.HD 字段描述(D24.2.223) | D24-10139 | 只有 HA 依赖("HA=0 时 HD behaves as 0") | 无 |

- **Table D8-76 为关键新发现**(Leo/Marc 均未引):stage 2 写权限只由 S2AP 决定,
  DBM 不是权限位;WC 在 HD=1 时可写靠 RTYCNM 例外("HW 脏管理使能时对 WC 描述符的
  写不产生 Permission fault"),不是 DBM 授予写。同时支持两方:Leo 的行为表
  (WC→RO 的机理是 S2AP[1]=0)成立;Marc 的软件 walker 论点(读 DBM 为可写 = 错)
  得到比 R_XZFQH 更直接的依据。
- caveat:核查基于 **M.b**;Leo 查的是 M.cc(表号体系不同,M.b 中上述 Stage 2 表
  不叫 "D8-53")。若 Marc 引的是更新修订版的条文,此处未覆盖。

**头信息**:

```
To: Leonardo Bras <leo.bras@arm.com>
Cc: Marc Zyngier <maz@kernel.org>, Oliver Upton <oupton@kernel.org>, <§0 公共 Cc 列表>
Subject: Re: [RFC PATCH 1/5] KVM: arm64: pgtables: Change write bit from S2AP_W to DBM
In-Reply-To: <aqqY1QiB0ZBAQkwc@LeoBrasDK>
```

**挂靠邮件**(lore):[aqqY1QiB0ZBAQkwc@LeoBrasDK](https://lore.kernel.org/linux-arm-kernel/aqqY1QiB0ZBAQkwc@LeoBrasDK/)

**正文**:

```
On Wed, Sep 16, 2026 at 02:25:41PM +0100, Leonardo Bras wrote:
> So I am possibly missing the proper place to look for that information. 
> Could you please share that with me so I can improve and maybe avoid being 
> a inconvenience in the future?

Hi Leo,

I'm afraid I can't find that either: I checked the Stage 2 descriptor
field table, D8.4.2.1, D8.5.2, and the VTCR_EL2.HD field description —
none of them says bit 51 is RES0 when VTCR_EL2.HD == 0; the descriptor
table only picks between DBM and PIIndex[1] based on Indirect
permissions. Looking forward to Marc's pointer.

For what it's worth, D8.4.2.1 already settles the permission side of
the NV discussion: stage 2 write permission is determined by S2AP
alone (Table D8-76 in the M.b release), so a software walker reading
DBM as writability is wrong regardless of HD — which is the
walk_nested_s2_pgd() issue in disguise.

Either way, the NV side does not need to wait for that answer.
KVM limits the L1-visible ID_AA64MMFR1_EL1.HAFDBS to AF-only, so bit 51
has no architectural meaning to L1, and an L1 using it as software
metadata would have its read-only pages misread as writable by the
union read in walk_nested_s2_pgd() — the memory corruption Marc
described. Since NV has no HAFDBS emulation today, I'd suggest simply
reverting this hunk for now and keep reading writability from S2AP[1]
alone:

	out->writable = desc & KVM_PTE_LEAF_ATTR_LO_S2_S2AP_W;

The union read can come back once nested HAFDBS emulation exists,
gated on the L1's effective VTCR_EL2.HD. That's what I did when
picking the series up for HDBSS v5 (patch 1 in our tree drops the
nested.c hunk and says so in the cover letter) — happy to hand the
hunk over if you want it for your v2.

Thanks,
Tian
```

**中文要点**:

1. 第一段(**已升级为第一手核实**):四个位置(Stage 2 descriptor 字段表 /
   D8.4.2.1 / D8.5.2 / VTCR_EL2.HD 字段描述)都查过,均无 "HD=0 时 bit51 RES0"
   明文——只陈述已核实的事实,**不抢答 RES0 出处**(等 Marc 指针)。
2. 第二段(新增,建设性输入):D8.4.2.1 Table D8-76——stage 2 写权限只由 S2AP
   决定,DBM 不是权限位 → 软件 walker 读 DBM 为可写在任何 HD 值下都是错的,正是
   walk_nested_s2_pgd() 的问题本身——revert 提议的最直接条文依据。
3. 第三段:NV 部分不必等答案。论据链:HAFDBS 对 L1 限 AF-only → bit51 对 L1
   无架构含义 → 联合读会把"L1 拿 bit51 当软件元数据的只读页"误判可写
   (= Marc 说的内存损坏)。NV 无 HAFDBS 模拟 → 先 revert,只看 S2AP[1]。
4. 第四段:回来条件(嵌套 HAFDBS 模拟落地 + gate 在 L1 的 effective
   VTCR_EL2.HD);我们 0001 已这么做,愿意移交 hunk。

**与 leo_review_reply_draft.md N5 处置的关系**:N5 原判定"闭环不再发"指
**不重复报问题**(Marc/Oliver 已定性)。本邮件不是报问题,而是 Leo 主动求助 +
我们有现成修复的顺水推舟:确认困惑 + 提出短期动作 + 移交已验证的 hunk,
三者都是增量信息。注意范围:只谈 NV 这一个 hunk 的 revert,**不**对
"HD=0 时 DBM 能否当软件编码位"(patch 1 全局 always-set-DBM)表态——那是
Leo/Marc 之间未决的架构讨论,Oliver 已引 stage-1 先例,见 §5。

---

## 3. 邮件 C:回 Leo——技术细节 review(随系列发)

**与旧稿的关系**:`leo_review_reply_draft.md` 附录 A 邮件二的**终版**,两处增量:

1. 开头改为衔接邮件 B("下周发系列"的通告),替代原来的
   "We've had this series under our HDBSS tree for a while";
2. Minor 第二条(RELOAD 顺序注释)追加 **0014 实证**:RELOAD 只重载 stage-2
   翻译寄存器,HDBSSBR/HDBSSPROD_EL2 跨 mid-run 使能陈旧、脏状态静默丢失——
   "RELOAD 管什么不管什么"需要文档化的最强新证据。

其余段落与旧稿一致(内容依据:leo_review_reply_draft.md 第一、二部分,
对应 §0.6 一页总览 #1–#5 / N1 / N2+N7 / N9 / N10)。

**头信息**:

```
To: Leonardo Bras <leo.bras@arm.com>
Cc: Oliver Upton <oupton@kernel.org>, Marc Zyngier <maz@kernel.org>, <§0 公共 Cc 列表>
Subject: Re: [RFC PATCH 2/5] KVM: arm64: Add KVM_PGTABLE_PROT_DIRTY
In-Reply-To: <aqmBY_v74r4GMttY@LeoBrasDK>
```

**挂靠邮件**(lore):[aqmBY_v74r4GMttY@LeoBrasDK](https://lore.kernel.org/linux-arm-kernel/aqmBY_v74r4GMttY@LeoBrasDK/)
—— PATCH 2/5 线程最新一封,Leo 对 Marc 9/13 patch-2 review
([86a4pl7c1m](https://lore.kernel.org/linux-arm-kernel/86a4pl7c1m.wl-maz@kernel.org/))的回应。

**正文(全文终版)**:

```
Hi Leo,

As mentioned in my reply on patch 1, we're sending HDBSS v5 next week
with this series merged in, carrying a few fixups on top. Comments
below — none of this overlaps with what Marc and Oliver already
raised.

The dirty accounting in kvm_s2_fault_map() needs to be split; both
consumers are currently gated on PROT_DIRTY:

	bool dirty = prot & KVM_PGTABLE_PROT_DIRTY;

	kvm_release_faultin_page(kvm, s2vi->page, !!ret, dirty);
	...
	if (dirty && !ret)
		mark_page_dirty_in_slot(...);

These are two ledgers with opposite precision requirements. The folio
one must stay speculative — the comment above kvm_release_faultin_page()
says exactly that, and x86 relies on the same property for its
hardware dirty bit. The bitmap one must stay exact, or pre-copy ships
clean pages. Your "use writable" from the sashiko thread fixes the
fault side; the account still needs closing on the way out —
zap_present_folio_ptes() does folio_mark_dirty() on pte_dirty(), and
the S2 unmap/wp walkers want the same treatment for S2AP_W/DBM.

On the VTCR flip: HD alone is architecturally a no-op. The VTCR_EL2.HD
field description reads "When the Effective value of VTCR_EL2.HA is 0,
this field behaves as 0 for all purposes other than a direct read of
the value of this bit" — so as it stands, patch 5 never enables
stage-2 dirty management at all. HA has to come along regardless:
FEAT_HDBSS requires VTCR_EL2.{HDBSS,HA,HD} = {1,1,1} (D8.5.2.3,
ITMYVQ).

Also on the flip: cpu_enable_hw_dbm() pairs it with isb() +
local_flush_tlb_all(). The enable-logging direction happens to be
covered by the subsequent wp+flush, but that ordering is implicit, and
the disable-logging direction keeps faulting through stale RO
translations page by page. A kvm_flush_remote_tlbs() in
kvm_set_hafdbs() — or at least a comment on the caller's TLBI
responsibility — would make both directions robust.

kvm_s2_fault_compute_prot() gates WC on the static
kvm_supports_hafdbs(), which stays true once HD is flipped off. A
single logging memslot does that: QEMU keeps LOG_DIRTY_PAGES on the
VGA VRAM slot for the whole lifetime of a desktop VM, so this is the
common non-migrating case, not an edge. Every new read fault then
installs WC, which is RO under HD=0 — one extra fault per page,
indefinitely. Reading vtcr & VTCR_EL2_HD instead keeps the
optimization honest.

On the setup_vcpu vs set_hafdbs race: rather than adding slots_lock to
kvm_setup_vcpu(), making HD a derived value (capability &&
!nr_memslots_dirty_logging, recomputed on each event) gets rid of the
RMW window entirely, with no lock ordering to audit.

Minor:

- stage2_wrprotect_walker() plain-WRITE_ONCEs where the old path
  cmpxchg'd for SHARED walks. Fine while the only caller holds the
  write lock, but the contract is now silent. Either keep the cmpxchg
  or state exclusive-only at the function.

- The plain store is only safe because RELOAD (KVM_REQUEST_WAIT)
  quiesces all vCPUs before wp runs, so no hardware WC->WD update can
  race it. That ordering in kvm_arch_commit_memory_region() is
  load-bearing and undocumented — worth comments in both places.
  We've since hit the flip side of this in the HDBSS leg:
  KVM_REQ_RELOAD_STAGE2 only reloads the stage-2 translation
  registers, and the HDBSS buffer registers went stale across a
  mid-run enable — hardware kept writing dirtied IPAs through a stale
  buffer address, and the dirty state was lost silently. We fixed it
  by binding HDBSSBR/HDBSSPROD_EL2 to buffer ownership rather than
  enablement; either way, it's worth documenting what RELOAD does and
  does not reload.

Forward-looking: once S2 sharing with the SMMU lands, WC pages are RO
to any SMMU without HTTU dirty support, and device faults have no
relax path. If that's in sight, kvm_supports_hafdbs() probably wants a
gate for assigned devices / dbm-capable SMMUs.

Any selftests plans for v2? Happy to contribute three-state round-trip
cases.

Thanks,
Tian
```

**内容对照**(段落 → leo_review_reply_draft.md 条目):拆账+收割 → #1;
HD|HA → #2;TLBI → #3;静态判断 → #4;推导式 HD → #5;walker → N1;
RELOAD 顺序 + 0014 → N2+N7;SMMU → N9;selftests → N10。

---

## 4. 可选邮件 D:回 Leo——pKVM 跟帖

**背景**:Leo 9/17 在 PATCH 5/5 线程问 Oliver "Would that make sense in pKVM
as well?"([`aqvt2gnlBZeNsaf4`](https://lore.kernel.org/linux-arm-kernel/aqvt2gnlBZeNsaf4@LeoBrasDK/),
nVHE/hVHE 语境下 HAFDBS 如何工作),Oliver 尚未回答。问题链:Leo 9/16 15:00 问
"Would this work in nVHE?"
([`aqqhDs3NyjtkZzXK`](https://lore.kernel.org/linux-arm-kernel/aqqhDs3NyjtkZzXK@LeoBrasDK/))
→ Oliver 9/16 16:27 反问 "How is this any different?"
([`aqsl1_IqnV2r8kUL`](https://lore.kernel.org/linux-arm-kernel/aqsl1_IqnV2r8kUL@kernel.org/))
→ Leo 9/17 追问 pKVM。全线程唯一没人接、且我们有独家素材的悬置点。**注意**:
Oliver 对 nVHE 本身的反问("We already pass a stage-2 MMU configuration to EL2
from EL1 in nVHE and hVHE")是问 Leo 的,我们只补 pKVM 事实,不替 Leo 答 nVHE。

**素材出处**:dbm_blindspots_and_risks.md §4(pKVM:PROT_RW 家族)、cover letter
"restricted to VHE systems; nested guests are excluded"。

**头信息**:

```
To: Leonardo Bras <leo.bras@arm.com>
Cc: Oliver Upton <oupton@kernel.org>, <§0 公共 Cc 列表>
Subject: Re: [RFC PATCH 5/5] KVM: arm64: Enable HAFDBS for guests not on migration
In-Reply-To: <aqvt2gnlBZeNsaf4@LeoBrasDK>
```

**挂靠邮件**(lore):[aqvt2gnlBZeNsaf4@LeoBrasDK](https://lore.kernel.org/linux-arm-kernel/aqvt2gnlBZeNsaf4@LeoBrasDK/)

**正文(短稿)**:

```
On Thu, Sep 17, 2026 at 02:40:42PM +0100, Leonardo Bras wrote:
> Would that make sense in pKVM as well?

For HDBSS at least, it needs hyp-side plumbing: the buffer registers
(HDBSSBR_EL2, HDBSSPROD_EL2) are EL2-only, and under pKVM the host
doesn't own VTCR_EL2 either — the hypervisor does. The buffer would
have to live in EL2 memory, be shared with the host for the flush,
and the mode flip would have to be requested through a hypercall.
We've restricted HDBSS v5 to VHE and excluded pKVM for exactly that
reason (noted in the cover letter).

The encoding patches themselves are pKVM-neutral though: PROT_RW keeps
mapping WD (patch 2 adds PROT_DIRTY to the RW family, so host stage-2
and pKVM guest mappings still land writable-dirty), and HD stays 0
there — no behavior change for protected guests.

Thanks,
Tian
```

**发送判断**:可与 B 同发(展示我们想清楚了 pKVM 边界),也可等 Oliver 先答。
若发,建议在 B 之后,保持"B 通告 → 细节补充"的节奏。

---

## 5. 明确不发 / 不接的话头(及理由)

| 话头 | 为什么不接 |
|---|---|
| bit51 RES0 条文出处(Leo 9/16 14:25 问 Marc,R_XZFQH/R_BRFGY/I_MHJZP) | 让 Marc 回。已在 DDI 0487 M.b 四处定位核查(§2 核查记录:D8-7735/7736、D8-7757、D8-777x、D24-10139),均无该明文;邮件 A 陈述已核实事实并引 D8.4.2.1 Table D8-76,但不替 Marc 下结论(M.b ≠ M.cc,修订版条文未覆盖) |
| "HD=0 时 DBM 能否当软件编码位"(patch 1 always-set-DBM 的架构合法性) | Leo/Marc 之间未决;Oliver 已引 stage-1 先例。我们没有增量论据,不带立场 |
| vcpu_has_nv 粒度(N3) | 暂停等 v2:Oliver 已指出 NV gate 本身不该存在(canonical S2 可独立用 HAFDBS),Leo 9/17 已提议改名 kvm_has_nv();v2 若删 gate,问题消失 |
| HAFDBS always-on vs opt-in(N4) | 归我们设计:合并后由 0011 事件驱动状态机承担,不是问 Leo 的问题 |
| Leo 的嵌套 HAFDBS 模拟长推理(9/17,L0/L1/L2 各层开关) | Oliver 已用 "shadow S2 当 TLB 看" 回应并给了方向(pseudo-TLB 内部脏态、relax before evaluating permissions),不掺和 |
| Oliver 问 Leo 的 nVHE 反问("How is this any different?") | 问 Leo 的;我们只在邮件 D 补 pKVM 事实 |

---

## 6. 发送与发系列前清单(下周前必须完成)

### 6.1 工程动作(发系列硬前置)

| # | 动作 | 说明 |
|---|---|---|
| 1 | **0014 折入决策** | 建议 squash 进 **0007**(HDBSS per-vCPU buffer management):buffer 寄存器编程本属 0007 主题;v5 尚未上游,系列内自修复应折叠而非独立携带。0014 的 commit message(竞态机理 + 实证回溯 d52cdc8ea269)择要并入 0007 |
| 2 | **清理 `Co-Authored-By: Claude`** | 0014 第 50 行;社区提交规范(无论 squash 与否) |
| 3 | **cover letter 重生成** | squash 方案保持 `00/13`;diffstat 变化(dirty_bit.c、hyp/vhe/switch.c);作者统计不变(均为 Tian)。若独立保留则 `00/13`→`00/14` 且 Tian Zheng (7)→(8),双 diffstat 更新 |
| 4 | **复验** | 改动后 patch 跑 checkpatch;干净 worktree `git am` 全系列;编译检查点(0007/0011/HEAD) |
| 5 | **文档同步** | readme.md "验证状态"段更新;发送后将 leo_review_reply_draft.md §0.6 表外跟踪标记 B/A/C 已发、附录 A 标注已被本文取代 |

### 6.2 内容动作

- 邮件 B/A 可立即发(不依赖系列定稿;B 的"下周"承诺开始计时);
- 邮件 C 引用 0014 实证,**必须在 0014 折入完成后发**,建议随系列当天或前一天;
- 邮件 D 自主决定(见 §4 发送判断)。

### 6.3 性能数据认领的兑现(B 发出后即为承诺)

| 数据组 | 形态 | 说明 |
|---|---|---|
| HDBSS 腿 | 迁移 + dirty ring / dirty bitmap | Oliver 要的 meaningful user;编码真正受益处 |
| desktop VGA 形态 | 常开 LOG_DIRTY_PAGES 的 VRAM slot,live-HD 修复(0011)前后 | 证明 F4 修复前是悬崖、修复后收益剩余多少 |
| headless server | 无 VGA,HD 常开 | Leo 认领的 HAFDBS 基础形态,我们顺带覆盖 |

---

## 附:引用邮件速查(本文涉及)

| 角色 | 时间 | Message-ID(lore 链接) | 要点 |
|---|---|---|---|
| Marc | 9/13 10:00 +0100 | [86bja17cg7.wl-maz](https://lore.kernel.org/linux-arm-kernel/86bja17cg7.wl-maz@kernel.org/) | patch 1 review:"What makes it acceptable to always set DBM?";nested 联合读 "Absolutely NOT" |
| Leo | 9/15 18:12 +0100 | [aql8jY4o8SzjJuFU](https://lore.kernel.org/linux-arm-kernel/aql8jY4o8SzjJuFU@LeoBrasDK/) | WC/WD 编码设计意图;"Sorry, not really... please help me understand it" |
| Leo | 9/15 18:33 +0100 | [aqmBY_v74r4GMttY](https://lore.kernel.org/linux-arm-kernel/aqmBY_v74r4GMttY@LeoBrasDK/) | PATCH 2/5 线程最新一封(邮件 C 的挂靠点) |
| Oliver | 9/15 17:10 -0700 | [aqneWnlsdpocLIl6](https://lore.kernel.org/linux-arm-kernel/aqneWnlsdpocLIl6@kernel.org/) | PATCH 5/5 review:"Do you have any performance numbers?";VHE-only / NV gate 质疑 |
| Oliver | 9/15 17:37 -0700 | [aqnku2TcFzIKhjQl](https://lore.kernel.org/linux-arm-kernel/aqnku2TcFzIKhjQl@kernel.org/) | stage-1 先例;walker 消费 DBM 无视 HD = bug;"work with Tian"(邮件 B 的语境) |
| Leo | 9/16 12:22 +0100 | [aqp73SxO78o7LJTs](https://lore.kernel.org/linux-arm-kernel/aqp73SxO78o7LJTs@LeoBrasDK/) | "Sure" 同意合并(邮件 B 挂靠点);"DBM 只在 HD=1 才算 writable?" |
| Marc | 9/16 13:20 +0100 | [86fqz95qwe.wl-maz](https://lore.kernel.org/linux-arm-kernel/86fqz95qwe.wl-maz@kernel.org/) | "RES0, RES0, or RES0";规则号 R_XZFQH/R_BRFGY/I_MHJZP |
| Leo | 9/16 14:25 +0100 | [aqqY1QiB0ZBAQkwc](https://lore.kernel.org/linux-arm-kernel/aqqY1QiB0ZBAQkwc@LeoBrasDK/) | R_XZFQH "if not only if" 之辩;找不到 RES0 条文,请 Marc 给出处(邮件 A 挂靠点) |
| Leo | 9/16 15:00 +0100 | [aqqhDs3NyjtkZzXK](https://lore.kernel.org/linux-arm-kernel/aqqhDs3NyjtkZzXK@LeoBrasDK/) | PATCH 5/5:认领找机器测性能;"Would this work in nVHE?" |
| Oliver | 9/16 16:27 -0700 | [aqsl1_IqnV2r8kUL](https://lore.kernel.org/linux-arm-kernel/aqsl1_IqnV2r8kUL@kernel.org/) | "micro-optimization" 定性;nVHE 反问;shadow S2 当 TLB 看的嵌套机理 |
| Leo | 9/17 14:40 +0100 | [aqvt2gnlBZeNsaf4](https://lore.kernel.org/linux-arm-kernel/aqvt2gnlBZeNsaf4@LeoBrasDK/) | "Would that make sense in pKVM as well?"(邮件 D 挂靠点,Oliver 未答) |
